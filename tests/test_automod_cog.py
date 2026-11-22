"""Unit tests for the Advanced AutoMod Cog and Service."""

import json
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.automod.cog import AutoMod
from bot.services.automod_service import AutoModService, INVITE_PATTERN, URL_PATTERN
from bot.core.context import UnifiedContext


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.db = MagicMock()
    bot.db_manager = bot.db
    bot.db.fetchone = AsyncMock(return_value={
        "guild_id": 111111,
        "enabled": 1,
        "bad_words_enabled": 1,
        "bad_words_list": json.dumps(["badword1", "badword2"]),
        "invites_blocked": 1,
        "links_blocked": 0,
        "caps_enabled": 1,
        "caps_min_chars": 10,
        "caps_percentage": 70,
        "emojis_enabled": 1,
        "emoji_limit": 8,
        "mention_limit": 5,
        "repeat_enabled": 1,
        "repeat_threshold": 3,
        "flood_interval_seconds": 1.0,
        "log_channel_id": None,
        "exempt_roles": "[]",
        "exempt_channels": "[]",
    })
    bot.db.execute = AsyncMock()
    bot.db.fetchall = AsyncMock(return_value=[])
    return bot


@pytest.mark.asyncio
async def test_automod_overview(mock_bot):
    """Test automod overview embed display."""
    cog = AutoMod(mock_bot)
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock()
    ctx.guild.id = 111111
    ctx.guild.name = "Test Guild"
    ctx.reply = AsyncMock()

    await cog._execute_automod(ctx)
    ctx.reply.assert_awaited_once()
    kwargs = ctx.reply.call_args[1]
    assert "embed" in kwargs
    embed = kwargs["embed"]
    assert "AutoMod Status" in embed.title


@pytest.mark.asyncio
async def test_badwords_add_and_remove(mock_bot):
    """Test adding and removing bad words to the automod list."""
    cog = AutoMod(mock_bot)
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock()
    ctx.guild.id = 111111
    ctx.reply = AsyncMock()
    ctx.send_success = AsyncMock()

    # Add bad word
    await cog._execute_badwordsadd(ctx, "forbiddenword")
    mock_bot.db.execute.assert_awaited()

    # Remove bad word
    mock_bot.db.execute.reset_mock()
    await cog._execute_badwordsremove(ctx, "badword1")
    mock_bot.db.execute.assert_awaited()


@pytest.mark.asyncio
async def test_capslimit_bounds(mock_bot):
    """Test capslimit validates percentage bounds (50-100)."""
    cog = AutoMod(mock_bot)
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock()
    ctx.guild.id = 111111
    ctx.reply = AsyncMock()
    ctx.send_success = AsyncMock()
    ctx.send_error = AsyncMock()

    # Valid percentage
    await cog._execute_capslimit(ctx, 80)
    mock_bot.db.execute.assert_awaited()

    # Invalid percentage (too low)
    await cog._execute_capslimit(ctx, 20)
    ctx.send_error.assert_awaited_with("Out of Range", "Percentage must be between 50 and 100.")


def test_automod_regex_patterns():
    """Test invite and URL pattern detection."""
    assert INVITE_PATTERN.search("Come join https://discord.gg/testcode today!") is not None
    assert INVITE_PATTERN.search("Check discordapp.com/invite/abcdef for info") is not None
    assert INVITE_PATTERN.search("Hello world, no invite here") is None

    assert URL_PATTERN.search("visit https://malicious-site.com/payload.exe now") is not None
    assert URL_PATTERN.search("just regular conversation") is None


def test_automod_admin_exemption():
    """Test administrators are exempt from automod filters."""
    bot = MagicMock()
    service = AutoModService(bot)

    admin_member = MagicMock(spec=discord.Member)
    admin_member.guild_permissions.administrator = True
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 12345

    assert service._is_exempt(admin_member, channel, [], []) is True


@pytest.mark.asyncio
async def test_automod_punishment_escalation_ladder():
    """Test that repeated infractions within 24 hours trigger automated ladder escalation to timeout."""
    bot = MagicMock()
    bot.db = MagicMock()
    # Mock user having 4 existing violations in the past 24 hours -> 5th infraction
    bot.db.fetchone = AsyncMock(return_value={"cnt": 4})

    service = AutoModService(bot)

    message = MagicMock(spec=discord.Message)
    message.guild = MagicMock(spec=discord.Guild)
    message.guild.id = 999999
    message.guild.name = "Test Guild"
    message.author = MagicMock(spec=discord.Member)
    message.author.id = 888888
    message.author.timeout = AsyncMock()
    message.channel = MagicMock(spec=discord.TextChannel)
    message.channel.send = AsyncMock()
    message.delete = AsyncMock()

    # Apply base "warn" action
    await service._apply_action(message, action="warn", reason="Bad words filter")

    # Message must be deleted
    message.delete.assert_awaited_once()
    # Action must be escalated to 1-hour timeout (3600 seconds)
    message.author.timeout.assert_awaited_once()
    timeout_reason = message.author.timeout.call_args[1].get("reason", "")
    assert "Automated Punishment Ladder" in timeout_reason
    assert "1 hour" in str(message.channel.send.call_args) or "60m" in str(message.channel.send.call_args)
