"""Unit tests for Logging cog and service."""

from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.logging.cog import Logging
from bot.services.logging_service import LoggingService, _sanitize
from bot.core.context import UnifiedContext


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.logging_repo = MagicMock()
    bot.logging_repo.get_settings = AsyncMock(return_value={
        "mod_log_channel": 111,
        "message_log_channel": 222,
        "member_log_channel": 333,
        "server_log_channel": 444,
        "voice_log_channel": 555,
    })
    bot.logging_repo.update_settings = AsyncMock()
    bot.logging_repo.toggle_event = AsyncMock()
    bot.logging_repo.get_event_toggles = AsyncMock(return_value={"msg_delete": True})
    bot.logging_repo.get_recent_logs = AsyncMock(return_value=[])
    bot.logging_repo.clear_logs = AsyncMock(return_value=5)
    return bot


def _make_ctx():
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock()
    ctx.guild.id = 111111
    ctx.guild.name = "Logging Server"
    ctx.author = MagicMock(spec=discord.Member)
    ctx.reply = AsyncMock()
    ctx.send_success = AsyncMock()
    ctx.send_error = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_logchannel_and_status(mock_bot):
    """Test logchannel assignment and logstatus embed."""
    cog = Logging(mock_bot)
    ctx = _make_ctx()
    mock_ch = MagicMock(spec=discord.TextChannel)
    mock_ch.id = 777

    # Set channel
    await cog._execute_logchannel(ctx, "messages", mock_ch)
    mock_bot.logging_repo.update_settings.assert_awaited_with(111111, message_log_channel=777)
    ctx.send_success.assert_awaited()

    # Show status
    await cog._execute_logstatus(ctx)
    ctx.reply.assert_awaited()


@pytest.mark.asyncio
async def test_log_toggles_and_clear(mock_bot):
    """Test event toggling and log clearance."""
    cog = Logging(mock_bot)
    ctx = _make_ctx()

    # Toggle event
    await cog._execute_logtoggle(ctx, "msg_delete", "disable")
    mock_bot.logging_repo.toggle_event.assert_awaited_with(111111, "msg_delete", False)

    # Clear logs
    await cog._execute_logclear(ctx)
    mock_bot.logging_repo.clear_logs.assert_awaited_with(111111, None)


def test_token_sanitization():
    """Test secret and token redaction from message logs."""
    raw = "Here is my secret token: sample_mock_token_string_24.mock06.sample_mock_secret_string_27chars do not share"
    sanitized = _sanitize(raw)
    assert "sample_mock_token_string_24" not in sanitized
    assert "[REDACTED_TOKEN]" in sanitized

