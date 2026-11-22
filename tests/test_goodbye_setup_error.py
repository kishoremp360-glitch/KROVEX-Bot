"""Automated tests for /setup goodbye error diagnosis and TransformerError handling.

Verifies:
1. /setup goodbye executes cleanly with a valid TextChannel.
2. /setup goodbye defaults safely to ctx.channel when no channel argument is provided.
3. /setup goodbye handles invalid channel types gracefully without raising unhandled System Error.
4. Error handler catches discord.app_commands.errors.TransformerError and returns an informative user embed.
5. All wizard setup handlers defer immediately to prevent interaction timeouts.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest
import discord
from discord import app_commands

from bot.cogs.admin.setup_wizard import SetupWizard
from bot.core.context import UnifiedContext
from bot.core.error_handler import GlobalErrorHandler


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.db = MagicMock()
    bot.db_manager = bot.db
    bot.db.execute = AsyncMock()
    bot.logging_repo = MagicMock()
    bot.logging_repo.update_settings = AsyncMock()
    return bot


def _make_ctx(channel=None):
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock()
    ctx.guild.id = 112233
    ctx.guild.name = "Goodbye Guild"
    ctx.channel = channel or MagicMock(spec=discord.TextChannel)
    ctx.channel.id = 999
    ctx.channel.mention = "<#999>"
    ctx.reply = AsyncMock()
    ctx.defer = AsyncMock()
    ctx.send_error = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_setupgoodbye_with_valid_channel(mock_bot):
    """Verify /setup goodbye configures the database and replies with confirmation."""
    cog = SetupWizard(mock_bot)
    target_ch = MagicMock(spec=discord.TextChannel)
    target_ch.id = 555
    target_ch.mention = "<#555>"
    ctx = _make_ctx()

    await cog._execute_setupgoodbye(ctx, target_ch)

    # Must defer immediately to avoid timeouts
    ctx.defer.assert_awaited_once_with(ephemeral=True)
    # Must persist channel to sqlite
    mock_bot.db.execute.assert_awaited_once()
    # Must reply with success embed
    ctx.reply.assert_awaited_once()
    sent_embed = ctx.reply.call_args.kwargs["embed"]
    assert "Farewell" in sent_embed.title or "Goodbye" in sent_embed.title
    assert "<#555>" in sent_embed.description


@pytest.mark.asyncio
async def test_setupgoodbye_defaults_to_current_channel(mock_bot):
    """Verify /setup goodbye uses current channel if channel is None."""
    cog = SetupWizard(mock_bot)
    ctx = _make_ctx()

    await cog._execute_setupgoodbye(ctx, None)

    ctx.defer.assert_awaited_once_with(ephemeral=True)
    mock_bot.db.execute.assert_awaited_once()
    ctx.reply.assert_awaited_once()
    sent_embed = ctx.reply.call_args.kwargs["embed"]
    assert "<#999>" in sent_embed.description


@pytest.mark.asyncio
async def test_setupgoodbye_handles_invalid_channel_type(mock_bot):
    """Verify non-text channel input is rejected cleanly with an informative error."""
    cog = SetupWizard(mock_bot)
    ctx = _make_ctx()
    invalid_target = "not-a-channel"

    await cog._execute_setupgoodbye(ctx, invalid_target)

    ctx.defer.assert_awaited_once_with(ephemeral=True)
    ctx.send_error.assert_awaited_once()
    args = ctx.send_error.call_args.args
    assert "Invalid Channel" in args[0]
    # Database execute should not be called with invalid channel
    mock_bot.db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_error_handler_catches_transformer_error(mock_bot):
    """Verify handle_slash_error catches app_commands.TransformerError cleanly."""
    handler = GlobalErrorHandler(mock_bot)
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = 112233
    interaction.user = MagicMock()
    interaction.user.id = 445566
    interaction.command = MagicMock()
    interaction.command.name = "setup"
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.send_message = AsyncMock()

    # Construct TransformerError
    transformer = MagicMock()
    param = MagicMock()
    param.name = "channel"
    error = app_commands.TransformerError("invalid text", discord.AppCommandOptionType.channel, transformer)

    await handler.handle_slash_error(interaction, error)

    interaction.response.send_message.assert_awaited_once()
    sent_embed = interaction.response.send_message.call_args.kwargs["embed"]
    assert "Invalid Channel or Argument" in sent_embed.title
