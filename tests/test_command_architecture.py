"""Unit tests for UnifiedContext and shared command architecture."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from bot.core.context import UnifiedContext


@pytest.mark.asyncio
async def test_unified_context_from_prefix():
    """Verify UnifiedContext correctly wraps commands.Context."""
    mock_bot = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.bot = mock_bot
    mock_ctx.guild = MagicMock()
    mock_ctx.guild.name = "Test Guild"
    mock_ctx.author = MagicMock()
    mock_ctx.author.name = "Tester"
    mock_ctx.channel = MagicMock()
    mock_ctx.reply = AsyncMock()

    unified = UnifiedContext.from_prefix(mock_ctx)
    assert unified.is_prefix is True
    assert unified.is_interaction is False
    assert unified.guild.name == "Test Guild"
    assert unified.author.name == "Tester"

    # Test reply
    await unified.reply("Hello from Prefix!")
    mock_ctx.reply.assert_awaited_once()

    # Test send_success
    await unified.send_success("Success Title", "Success Desc")
    assert mock_ctx.reply.await_count == 2


@pytest.mark.asyncio
async def test_unified_context_from_interaction():
    """Verify UnifiedContext correctly wraps discord.Interaction."""
    mock_interaction = MagicMock()
    mock_interaction.client = MagicMock()
    mock_interaction.guild = MagicMock()
    mock_interaction.guild.name = "Slash Guild"
    mock_interaction.user = MagicMock()
    mock_interaction.user.name = "SlashUser"
    mock_interaction.response.is_done.return_value = False
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.response.defer = AsyncMock()
    mock_interaction.original_response = AsyncMock()

    unified = UnifiedContext.from_interaction(mock_interaction)
    assert unified.is_interaction is True
    assert unified.is_prefix is False
    assert unified.guild.name == "Slash Guild"
    assert unified.author.name == "SlashUser"

    # Test reply
    await unified.reply("Hello from Slash!")
    mock_interaction.response.send_message.assert_awaited_once()

    # Test defer
    await unified.defer(ephemeral=True)
    mock_interaction.response.defer.assert_awaited_once_with(ephemeral=True)


@pytest.mark.asyncio
async def test_unified_context_edit():
    """Verify UnifiedContext.edit works with messages and interactions."""
    mock_msg = MagicMock()
    mock_msg.edit = AsyncMock()

    unified = UnifiedContext(bot=MagicMock())
    await unified.edit(message=mock_msg, content="Updated Content")
    mock_msg.edit.assert_awaited_once()

    # Test editing via interaction
    mock_interaction = MagicMock()
    mock_interaction.edit_original_response = AsyncMock()
    unified_interaction = UnifiedContext.from_interaction(mock_interaction)
    await unified_interaction.edit(content="Interaction Content")
    mock_interaction.edit_original_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_shared_command_execution_consistency():
    """Verify that Slash and Prefix execute identical underlying command logic."""
    from bot.cogs.utility.cog import Utility

    mock_bot = MagicMock()
    mock_bot.uptime_seconds = 3665.0
    mock_bot.start_time = MagicMock()
    mock_bot.start_time.timestamp.return_value = 1700000000

    cog = Utility(mock_bot)

    # 1. Prefix Invocation
    prefix_ctx = MagicMock()
    prefix_ctx.bot = mock_bot
    prefix_ctx.reply = AsyncMock()
    await cog._execute_uptime(UnifiedContext.from_prefix(prefix_ctx))

    # 2. Slash Invocation
    slash_interaction = MagicMock()
    slash_interaction.client = mock_bot
    slash_interaction.response.is_done.return_value = False
    slash_interaction.response.send_message = AsyncMock()
    slash_interaction.original_response = AsyncMock()
    await cog._execute_uptime(UnifiedContext.from_interaction(slash_interaction))

    # Both must have sent an embed with the exact same title and uptime text
    prefix_call_args = prefix_ctx.reply.call_args
    slash_call_args = slash_interaction.response.send_message.call_args

    prefix_embed = prefix_call_args.kwargs["embeds"][0]
    slash_embed = slash_call_args.kwargs["embeds"][0]

    assert prefix_embed.title == slash_embed.title
    assert "1h 1m 5s" in prefix_embed.description
    assert "1h 1m 5s" in slash_embed.description
