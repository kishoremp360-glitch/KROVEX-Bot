"""Integration and lifecycle tests for Discord Gateway, Intents, Cog loading, and Error Handling."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord
from discord.ext import commands
from discord import app_commands

from bot.config import BotConfig
from bot.core.bot import DeathBot, get_prefix
from bot.core.checks import (
    UserNotInVoiceError,
    is_bot_owner,
    require_voice_channel,
)
from bot.core.error_handler import GlobalErrorHandler


def get_mock_config() -> BotConfig:
    """Helper creating a test configuration."""
    return BotConfig(
        token="mock_token",
        client_id=123456789,
        dev_guild_id=987654321,
        owner_ids=[111, 222],
        mongodb_uri="mongodb://localhost:27017",
        default_prefix="!",
    )


def test_bot_intents_configuration():
    """Verify DeathBot requests the required gateway intents."""
    config = get_mock_config()
    bot = DeathBot(config=config)

    intents = bot.intents
    # Privileged intents
    assert intents.members is True, "Guild Members intent must be enabled"
    assert intents.message_content is True, "Message Content intent must be enabled"
    # Standard intents
    assert intents.voice_states is True, "Voice States intent must be enabled"
    assert intents.guilds is True, "Guilds intent must be enabled"


@pytest.mark.asyncio
async def test_get_prefix_safe_when_bot_user_is_none():
    """Verify get_prefix does not crash when bot.user is None."""
    config = get_mock_config()
    bot = DeathBot(config=config)
    bot._user = None  # Simulates disconnected or pre-login state

    mock_msg = MagicMock()
    mock_msg.guild = None

    prefixes = await get_prefix(bot, mock_msg)
    assert "!" in prefixes


@pytest.mark.asyncio
async def test_cog_loading_and_unloading():
    """Verify cogs can be loaded and unloaded without errors."""
    config = get_mock_config()
    bot = DeathBot(config=config)

    # Load Utility cog
    await bot.load_extension("bot.cogs.utility.cog")
    assert "Utility" in bot.cogs

    # Verify commands registered
    cmd = bot.get_command("ping")
    assert cmd is not None
    assert cmd.name == "ping"

    # Unload Utility cog
    await bot.unload_extension("bot.cogs.utility.cog")
    assert "Utility" not in bot.cogs
    assert bot.get_command("ping") is None


@pytest.mark.asyncio
async def test_global_error_handler_prefix_cooldown():
    """Verify GlobalErrorHandler replies with warning on command cooldown."""
    config = get_mock_config()
    bot = DeathBot(config=config)
    handler = GlobalErrorHandler(bot)

    mock_ctx = MagicMock()
    mock_ctx.reply = AsyncMock()

    cooldown_error = commands.CommandOnCooldown(commands.Cooldown(1, 60), retry_after=12.5, type=commands.BucketType.user)
    await handler.handle_prefix_error(mock_ctx, cooldown_error)

    mock_ctx.reply.assert_awaited_once()
    call_args = mock_ctx.reply.call_args
    embed = call_args.kwargs["embed"]
    assert "Cooldown" in embed.title
    assert "12.5" in embed.description


@pytest.mark.asyncio
async def test_global_error_handler_prefix_missing_permissions():
    """Verify GlobalErrorHandler formats missing permissions clearly."""
    config = get_mock_config()
    bot = DeathBot(config=config)
    handler = GlobalErrorHandler(bot)

    mock_ctx = MagicMock()
    mock_ctx.reply = AsyncMock()

    perm_error = commands.MissingPermissions(["manage_guild", "ban_members"])
    await handler.handle_prefix_error(mock_ctx, perm_error)

    mock_ctx.reply.assert_awaited_once()
    call_args = mock_ctx.reply.call_args
    embed = call_args.kwargs["embed"]
    assert "Permission Denied" in embed.title
    assert "Manage Guild" in embed.description


@pytest.mark.asyncio
async def test_global_error_handler_unhandled_exception_gives_ref_id():
    """Verify unhandled exceptions generate an error reference ID without leaking tracebacks."""
    config = get_mock_config()
    bot = DeathBot(config=config)
    handler = GlobalErrorHandler(bot)

    mock_ctx = MagicMock()
    mock_ctx.command = MagicMock()
    mock_ctx.command.qualified_name = "test_broken_command"
    mock_ctx.reply = AsyncMock()

    unhandled = RuntimeError("Simulated internal explosion")
    await handler.handle_prefix_error(mock_ctx, unhandled)

    mock_ctx.reply.assert_awaited_once()
    call_args = mock_ctx.reply.call_args
    embed = call_args.kwargs["embed"]
    assert "System Error" in embed.title
    assert "Error Reference:" in embed.footer.text
    # Internal trace or exception string must NOT be leaked to user embed
    assert "Simulated internal explosion" not in embed.description


@pytest.mark.asyncio
async def test_require_voice_check_raises_when_not_in_vc():
    """Verify require_voice_channel predicate raises UserNotInVoiceError."""
    check_predicate = require_voice_channel().predicate

    mock_ctx = MagicMock()
    mock_author = MagicMock(spec=discord.Member)
    mock_author.voice = None
    mock_ctx.author = mock_author

    with pytest.raises(UserNotInVoiceError):
        await check_predicate(mock_ctx)
