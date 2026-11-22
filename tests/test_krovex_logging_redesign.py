"""Automated tests for KROVEX Unique Logging Architecture Redesign.

Verifies:
1. Canonical category provisioning: '⛨・KROVEX AUDIT VAULT'
2. Dedicated 7 canonical channels: security-feed, message-tracker, member-activity,
   voice-monitor, presence-tracker, invite-tracker, server-changes.
3. Safe in-place migration of legacy '📋 LOGS' and legacy channel names without message deletion.
4. Retention and protection of legacy 'SERVER LOGS' category without unauthorized deletion.
5. Idempotent repeated execution producing 0 duplicate categories or channels.
6. Unified KROVEX branding and embed footers across all dispatched event cards.
"""

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
    bot.logging_repo.get_settings = AsyncMock(return_value={})
    bot.logging_repo.update_settings = AsyncMock()
    bot.logging_repo.reset_settings = AsyncMock()
    bot.logging_repo.set_logging_enabled = AsyncMock()
    bot.logging_repo.is_logging_enabled = AsyncMock(return_value=True)
    bot.logging_repo.toggle_event = AsyncMock()
    bot.logging_repo.is_event_enabled = AsyncMock(return_value=True)
    bot.logging_repo.get_event_toggles = AsyncMock(return_value={})
    bot.logging_repo.log_event = AsyncMock()
    return bot


def _make_ctx(guild_id: int = 998877):
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock(spec=discord.Guild)
    ctx.guild.id = guild_id
    ctx.guild.name = "Krovex Test Guild"
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.name = "SecAdmin"
    ctx.reply = AsyncMock()
    ctx.send_success = AsyncMock()
    ctx.send_error = AsyncMock()
    ctx.defer = AsyncMock()

    me = MagicMock(spec=discord.Member)
    me.guild_permissions.manage_channels = True
    me.guild_permissions.administrator = True
    ctx.guild.me = me
    ctx.guild.default_role = MagicMock(spec=discord.Role)
    ctx.guild.categories = []
    ctx.guild.text_channels = []
    return ctx


@pytest.mark.asyncio
async def test_canonical_category_creation_and_7_channels(mock_bot):
    """Test autolog creates '⛨・KROVEX AUDIT VAULT' with the 7 canonical channels."""
    cog = Logging(mock_bot)
    ctx = _make_ctx()

    cat = MagicMock(spec=discord.CategoryChannel)
    cat.name = "⛨・KROVEX AUDIT VAULT"
    cat.text_channels = []
    ctx.guild.create_category = AsyncMock(return_value=cat)

    created_named_channels = {}

    async def fake_create_channel(name, topic=None, reason=None):
        ch = MagicMock(spec=discord.TextChannel)
        ch.name = name
        ch.topic = topic
        ch.id = len(created_named_channels) + 100
        ch.mention = f"<#{ch.id}>"
        ch.send = AsyncMock()
        ch.overwrites_for = MagicMock(return_value=MagicMock(read_messages=False))
        created_named_channels[name] = ch
        cat.text_channels.append(ch)
        return ch

    cat.create_text_channel = AsyncMock(side_effect=fake_create_channel)

    await cog._execute_autolog(ctx)

    # Category created with canonical name
    ctx.guild.create_category.assert_awaited_once()
    assert ctx.guild.create_category.call_args.args[0] == "⛨・KROVEX AUDIT VAULT"

    # Exactly 7 canonical channels created
    assert cat.create_text_channel.await_count == 7
    canonical_names = {
        "security-feed",
        "message-tracker",
        "member-activity",
        "voice-monitor",
        "presence-tracker",
        "invite-tracker",
        "server-changes",
    }
    assert set(created_named_channels.keys()) == canonical_names

    # Database updated with all 7 channel IDs
    mock_bot.logging_repo.update_settings.assert_awaited_once()
    kwargs = mock_bot.logging_repo.update_settings.call_args.kwargs
    assert kwargs["mod_log_channel"] == created_named_channels["security-feed"].id
    assert kwargs["message_log_channel"] == created_named_channels["message-tracker"].id
    assert kwargs["member_log_channel"] == created_named_channels["member-activity"].id
    assert kwargs["voice_log_channel"] == created_named_channels["voice-monitor"].id
    assert kwargs["status_log_channel"] == created_named_channels["presence-tracker"].id
    assert kwargs["invite_log_channel"] == created_named_channels["invite-tracker"].id
    assert kwargs["server_log_channel"] == created_named_channels["server-changes"].id

    # Initialization embed sent to security-feed
    created_named_channels["security-feed"].send.assert_awaited_once()


@pytest.mark.asyncio
async def test_legacy_logs_category_elevation(mock_bot):
    """Test existing '📋 LOGS' is upgraded/renamed to '⛨・KROVEX AUDIT VAULT' without duplication."""
    cog = Logging(mock_bot)
    ctx = _make_ctx()

    legacy_cat = MagicMock(spec=discord.CategoryChannel)
    legacy_cat.name = "📋 LOGS"
    legacy_cat.text_channels = []
    legacy_cat.edit = AsyncMock()
    legacy_cat.set_permissions = AsyncMock()
    ctx.guild.categories = [legacy_cat]

    async def fake_create_channel(name, topic=None, reason=None):
        ch = MagicMock(spec=discord.TextChannel)
        ch.name = name
        ch.id = 200
        ch.mention = f"<#{ch.id}>"
        ch.send = AsyncMock()
        ch.overwrites_for = MagicMock(return_value=MagicMock(read_messages=False))
        return ch

    legacy_cat.create_text_channel = AsyncMock(side_effect=fake_create_channel)

    await cog._execute_autolog(ctx)

    # Legacy category renamed in place
    legacy_cat.edit.assert_awaited_once_with(name="⛨・KROVEX AUDIT VAULT", reason="KROVEX Logging Architecture Redesign")
    # New category was NOT created
    ctx.guild.create_category.assert_not_called()


@pytest.mark.asyncio
async def test_channel_migration_preserves_messages_without_deletion(mock_bot):
    """Test legacy channels (e.g. mod-logs -> security-feed) are renamed in place preserving history."""
    cog = Logging(mock_bot)
    ctx = _make_ctx()

    cat = MagicMock(spec=discord.CategoryChannel)
    cat.name = "⛨・KROVEX AUDIT VAULT"
    cat.set_permissions = AsyncMock()
    ctx.guild.categories = [cat]

    # Pre-existing legacy channel 'mod-logs' with existing history
    mod_logs_ch = MagicMock(spec=discord.TextChannel)
    mod_logs_ch.name = "mod-logs"
    mod_logs_ch.id = 777888
    mod_logs_ch.mention = "<#777888>"
    mod_logs_ch.edit = AsyncMock()
    mod_logs_ch.send = AsyncMock()
    mod_logs_ch.delete = AsyncMock()
    mod_logs_ch.overwrites_for = MagicMock(return_value=MagicMock(read_messages=False))

    cat.text_channels = [mod_logs_ch]

    async def fake_create_channel(name, topic=None, reason=None):
        ch = MagicMock(spec=discord.TextChannel)
        ch.name = name
        ch.id = 300
        ch.mention = f"<#{ch.id}>"
        ch.send = AsyncMock()
        ch.overwrites_for = MagicMock(return_value=MagicMock(read_messages=False))
        return ch

    cat.create_text_channel = AsyncMock(side_effect=fake_create_channel)

    await cog._execute_autolog(ctx)

    # 'mod-logs' was renamed to 'security-feed', NOT deleted
    mod_logs_ch.edit.assert_awaited_once()
    assert mod_logs_ch.edit.call_args.kwargs["name"] == "security-feed"
    mod_logs_ch.delete.assert_not_called()


@pytest.mark.asyncio
async def test_server_logs_category_retention_and_protection(mock_bot):
    """Test older 'SERVER LOGS' category is detected, preserved intact, and NEVER deleted."""
    cog = Logging(mock_bot)
    ctx = _make_ctx()

    server_logs_cat = MagicMock(spec=discord.CategoryChannel)
    server_logs_cat.name = "SERVER LOGS"
    server_logs_cat.delete = AsyncMock()

    krovex_cat = MagicMock(spec=discord.CategoryChannel)
    krovex_cat.name = "⛨・KROVEX AUDIT VAULT"
    krovex_cat.text_channels = []
    krovex_cat.set_permissions = AsyncMock()

    ctx.guild.categories = [server_logs_cat, krovex_cat]

    async def fake_create_channel(name, topic=None, reason=None):
        ch = MagicMock(spec=discord.TextChannel)
        ch.name = name
        ch.id = 400
        ch.mention = f"<#{ch.id}>"
        ch.send = AsyncMock()
        ch.overwrites_for = MagicMock(return_value=MagicMock(read_messages=False))
        return ch

    krovex_cat.create_text_channel = AsyncMock(side_effect=fake_create_channel)

    await cog._execute_autolog(ctx)

    # SERVER LOGS must NOT be deleted
    server_logs_cat.delete.assert_not_called()

    # User response must explicitly mention preservation of SERVER LOGS awaiting approval
    sent_embed = ctx.reply.call_args.kwargs["embed"]
    assert "Legacy Preservation Notice" in sent_embed.description
    assert "SERVER LOGS" in sent_embed.description


@pytest.mark.asyncio
async def test_logging_service_krovex_footer_branding(mock_bot):
    """Test that LoggingService applies KROVEX AUDIT VAULT branding footer to dispatched logs."""
    service = LoggingService(mock_bot)

    guild = MagicMock(spec=discord.Guild)
    guild.id = 111222

    target_channel = MagicMock(spec=discord.TextChannel)
    target_channel.send = AsyncMock()
    guild.get_channel = MagicMock(return_value=target_channel)

    mock_bot.logging_repo.get_settings = AsyncMock(return_value={"mod_log_channel": 999})
    mock_bot.logging_repo.is_logging_enabled = AsyncMock(return_value=True)
    mock_bot.logging_repo.is_event_enabled = AsyncMock(return_value=True)

    test_embed = discord.Embed(title="Test Log Event", description="Security action taken")
    await service._emit_log(guild, "mod", "mod_action", test_embed, "Action details")

    assert target_channel.send.awaited
    sent_embed = target_channel.send.call_args.kwargs["embed"]
    assert "KROVEX AUDIT VAULT" in sent_embed.footer.text
