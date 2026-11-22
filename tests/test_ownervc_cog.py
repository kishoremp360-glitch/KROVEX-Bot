"""Unit tests for the Advanced Owner VC Cog and Dashboard."""

from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.ownervc.cog import OwnerVC
from bot.cogs.ownervc.dashboard import build_vc_embed, VCControlView
from bot.core.context import UnifiedContext


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.db = MagicMock()
    bot.db_manager = bot.db
    bot.db.fetchall = AsyncMock(return_value=[])
    bot.db.fetchone = AsyncMock(return_value=None)
    bot.db.execute = AsyncMock()
    return bot


@pytest.fixture
def mock_channel():
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = 222222
    channel.name = "General VC"
    channel.bitrate = 64000
    channel.user_limit = 10
    channel.rtc_region = "us-east"
    channel.category = MagicMock()
    channel.category.name = "Voice Channels"
    channel.members = []
    channel.guild = MagicMock()
    channel.guild.owner_id = 12345
    channel.guild.default_role = MagicMock()
    channel.overwrites_for = MagicMock(return_value=MagicMock(connect=True, view_channel=True))
    channel.set_permissions = AsyncMock()
    channel.edit = AsyncMock()
    return channel


@pytest.mark.asyncio
async def test_vclock_and_unlock(mock_bot, mock_channel):
    """Test locking and unlocking voice channels via permission overwrites."""
    cog = OwnerVC(mock_bot)
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = mock_channel.guild
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.guild_permissions.manage_channels = True
    ctx.author.voice = MagicMock(channel=mock_channel)
    ctx.reply = AsyncMock()
    ctx.send_success = AsyncMock()

    # Lock
    await cog._execute_vclock(ctx, mock_channel)
    mock_channel.set_permissions.assert_awaited_with(
        mock_channel.guild.default_role, connect=False, reason="VC Lock"
    )

    # Unlock
    mock_channel.set_permissions.reset_mock()
    await cog._execute_vcunlock(ctx, mock_channel)
    mock_channel.set_permissions.assert_awaited_with(
        mock_channel.guild.default_role, overwrite=None, reason="VC Unlock"
    )


@pytest.mark.asyncio
async def test_vchide_and_show(mock_bot, mock_channel):
    """Test hiding and showing voice channels."""
    cog = OwnerVC(mock_bot)
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = mock_channel.guild
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.guild_permissions.manage_channels = True
    ctx.reply = AsyncMock()
    ctx.send_success = AsyncMock()

    # Hide
    await cog._execute_vchide(ctx, mock_channel)
    mock_channel.set_permissions.assert_awaited_with(
        mock_channel.guild.default_role, view_channel=False, reason="VC Hide"
    )

    # Show
    mock_channel.set_permissions.reset_mock()
    await cog._execute_vcshow(ctx, mock_channel)
    mock_channel.set_permissions.assert_awaited_with(
        mock_channel.guild.default_role, overwrite=None, reason="VC Show"
    )


@pytest.mark.asyncio
async def test_vclimit_bounds(mock_bot, mock_channel):
    """Test user limit bounds validation (0-99)."""
    cog = OwnerVC(mock_bot)
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = mock_channel.guild
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.guild_permissions.manage_channels = True
    ctx.reply = AsyncMock()
    ctx.send_success = AsyncMock()
    ctx.send_error = AsyncMock()

    # Valid limit
    await cog._execute_vclimit(ctx, 25, mock_channel)
    mock_channel.edit.assert_awaited_with(user_limit=25, reason="VC Limit Change")

    # Invalid limit (> 99)
    await cog._execute_vclimit(ctx, 150, mock_channel)
    ctx.send_error.assert_awaited()


def test_vc_embed_builder(mock_channel):
    """Test VC control panel embed building."""
    embed = build_vc_embed(mock_channel)
    assert "VC Control Panel" in embed.title
    assert embed.color.value == 0x9D4EDD
    field_names = [f.name for f in embed.fields]
    assert "📊 Status" in field_names
    assert "👥 Members" in field_names
    assert "🌐 Region" in field_names
