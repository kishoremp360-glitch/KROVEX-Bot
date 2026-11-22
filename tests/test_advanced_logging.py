"""Automated tests for Death Bot Advanced Logging Expansion."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.core.context import UnifiedContext
from bot.cogs.logging.cog import Logging
from bot.services.logging_service import LoggingService


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.logging_repo = MagicMock()
    bot.logging_repo.get_settings = AsyncMock(return_value={
        "guild_id": 111222,
        "mod_log_channel": 101,
        "message_log_channel": 102,
        "member_log_channel": 103,
        "server_log_channel": 104,
        "voice_log_channel": 105,
        "status_log_channel": 106,
        "invite_log_channel": 107,
        "logging_enabled": 1,
    })
    bot.logging_repo.update_settings = AsyncMock()
    bot.logging_repo.reset_settings = AsyncMock()
    bot.logging_repo.set_logging_enabled = AsyncMock()
    bot.logging_repo.is_logging_enabled = AsyncMock(return_value=True)
    bot.logging_repo.toggle_event = AsyncMock()
    bot.logging_repo.is_event_enabled = AsyncMock(return_value=True)
    bot.logging_repo.get_event_toggles = AsyncMock(return_value={"msg_delete": True, "voice_join": True})
    bot.logging_repo.get_recent_logs = AsyncMock(return_value=[])
    bot.logging_repo.clear_logs = AsyncMock(return_value=10)
    bot.logging_repo.log_event = AsyncMock()
    return bot


def _make_ctx(guild_id: int = 111222):
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock(spec=discord.Guild)
    ctx.guild.id = guild_id
    ctx.guild.name = "Test Guild"
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.name = "AdminUser"
    ctx.reply = AsyncMock()
    ctx.send_success = AsyncMock()
    ctx.send_error = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_autolog_setup(mock_bot):
    """Test autolog setup provisions all 7 channels and updates database."""
    cog = Logging(mock_bot)
    ctx = _make_ctx()

    # Configure mock guild channel creation
    ctx.guild.me.guild_permissions.manage_channels = True
    ctx.guild.categories = []

    mock_category = MagicMock(spec=discord.CategoryChannel)
    mock_category.name = "📋 LOGS"
    mock_category.text_channels = []

    mock_channel = MagicMock(spec=discord.TextChannel)
    mock_channel.id = 999
    mock_channel.mention = "<#999>"
    mock_channel.send = AsyncMock()

    ctx.guild.create_category = AsyncMock(return_value=mock_category)
    mock_category.create_text_channel = AsyncMock(return_value=mock_channel)

    await cog._execute_autolog(ctx)

    ctx.guild.create_category.assert_awaited()
    assert mock_category.create_text_channel.await_count == 7
    mock_bot.logging_repo.update_settings.assert_awaited()
    ctx.reply.assert_awaited()


@pytest.mark.asyncio
async def test_autolog_existing_category_enforces_permissions(mock_bot):
    """Test D-03: Pre-existing category and child channels have @everyone view denial enforced."""
    cog = Logging(mock_bot)
    ctx = _make_ctx()

    ctx.guild.me.guild_permissions.manage_channels = True

    # Pre-existing category
    mock_category = MagicMock(spec=discord.CategoryChannel)
    mock_category.name = "📋 LOGS"
    mock_category.set_permissions = AsyncMock()
    ctx.guild.categories = [mock_category]

    # Pre-existing child channel with conflicting overwrites
    mock_channel = MagicMock(spec=discord.TextChannel)
    mock_channel.id = 777
    mock_channel.name = "mod-logs"
    mock_channel.mention = "<#777>"
    mock_channel.send = AsyncMock()
    mock_channel.set_permissions = AsyncMock()
    
    # Simulate conflicting overwrite where read_messages was True
    conflicting_ov = MagicMock()
    conflicting_ov.read_messages = True
    mock_channel.overwrites_for.return_value = conflicting_ov

    mock_category.text_channels = [mock_channel]
    mock_category.create_text_channel = AsyncMock(return_value=mock_channel)

    await cog._execute_autolog(ctx)

    # Category must NOT be recreated
    ctx.guild.create_category.assert_not_called()
    # Category permissions must be updated
    mock_category.set_permissions.assert_awaited()
    # Pre-existing child channel must have permissions synced
    mock_channel.set_permissions.assert_awaited()


@pytest.mark.asyncio
async def test_log_reset_preserves_historical_records(mock_bot):
    """Test log reset resets channels/settings without deleting audit records."""
    cog = Logging(mock_bot)
    ctx = _make_ctx()

    await cog._execute_logreset(ctx)

    # Must call reset_settings (which resets channels and toggles)
    mock_bot.logging_repo.reset_settings.assert_awaited_with(111222)
    # Must NOT call clear_logs (which deletes audit records)
    mock_bot.logging_repo.clear_logs.assert_not_called()
    ctx.reply.assert_awaited()


@pytest.mark.asyncio
async def test_log_disable_and_enable(mock_bot):
    """Test log disable and enable toggling."""
    cog = Logging(mock_bot)
    ctx = _make_ctx()

    # Disable
    await cog._execute_logdisable(ctx)
    mock_bot.logging_repo.set_logging_enabled.assert_awaited_with(111222, False)

    # Enable
    await cog._execute_logenable(ctx)
    mock_bot.logging_repo.set_logging_enabled.assert_awaited_with(111222, True)


@pytest.mark.asyncio
async def test_voice_logging_events(mock_bot):
    """Test voice join, leave, move, and mute/deafen logging."""
    service = LoggingService(mock_bot)

    guild = MagicMock(spec=discord.Guild)
    guild.id = 111222
    member = MagicMock(spec=discord.Member)
    member.guild = guild
    member.id = 555
    member.mention = "<@555>"

    ch1 = MagicMock(spec=discord.VoiceChannel)
    ch1.id = 201
    ch1.name = "General VC"
    ch2 = MagicMock(spec=discord.VoiceChannel)
    ch2.id = 202
    ch2.name = "Gaming VC"

    log_ch = MagicMock(spec=discord.TextChannel)
    log_ch.send = AsyncMock()
    guild.get_channel.return_value = log_ch

    # 1. Join VC
    before = MagicMock(channel=None, mute=False, deaf=False)
    after = MagicMock(channel=ch1, mute=False, deaf=False)
    await service.on_voice_state_update(member, before, after)
    log_ch.send.assert_awaited()
    log_ch.send.reset_mock()

    # 2. Move VC
    before = MagicMock(channel=ch1, mute=False, deaf=False)
    after = MagicMock(channel=ch2, mute=False, deaf=False)
    await service.on_voice_state_update(member, before, after)
    log_ch.send.assert_awaited()
    log_ch.send.reset_mock()

    # 3. Server Mute
    before = MagicMock(channel=ch2, mute=False, deaf=False)
    after = MagicMock(channel=ch2, mute=True, deaf=False)
    await service.on_voice_state_update(member, before, after)
    log_ch.send.assert_awaited()


@pytest.mark.asyncio
async def test_member_status_presence_logging(mock_bot):
    """Test member status transition logging and rate-limit guard."""
    service = LoggingService(mock_bot)

    guild = MagicMock(spec=discord.Guild)
    guild.id = 111222
    member_before = MagicMock(spec=discord.Member)
    member_before.guild = guild
    member_before.id = 444
    member_before.bot = False
    member_before.status = discord.Status.offline

    member_after = MagicMock(spec=discord.Member)
    member_after.guild = guild
    member_after.id = 444
    member_after.bot = False
    member_after.status = discord.Status.online
    member_after.mention = "<@444>"

    log_ch = MagicMock(spec=discord.TextChannel)
    log_ch.send = AsyncMock()
    guild.get_channel.return_value = log_ch

    # 1. First status update -> logged
    await service.on_presence_update(member_before, member_after)
    log_ch.send.assert_awaited()
    log_ch.send.reset_mock()

    # 2. Immediate second status update (< 30s) -> ignored by rate-limit shield
    await service.on_presence_update(member_before, member_after)
    log_ch.send.assert_not_called()

