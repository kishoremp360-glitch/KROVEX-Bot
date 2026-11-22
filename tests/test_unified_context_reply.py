"""Unit tests for Finding P1-01: UnifiedContext.reply double acknowledgement protection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.core.context import UnifiedContext


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    return bot


@pytest.mark.asyncio
async def test_fresh_interaction_uses_send_message(mock_bot):
    """A fresh interaction with is_done()=False must use response.send_message."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()
    interaction.original_response = AsyncMock(return_value="sent_message")
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    ctx = UnifiedContext(bot=mock_bot, interaction=interaction)
    res = await ctx.reply(content="Hello world")

    interaction.response.send_message.assert_awaited_once()
    interaction.original_response.assert_awaited_once()
    interaction.followup.send.assert_not_called()
    assert res == "sent_message"


@pytest.mark.asyncio
async def test_deferred_interaction_uses_followup_only(mock_bot):
    """An interaction that was deferred must route reply to followup.send."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = True
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock(return_value="followup_message")

    ctx = UnifiedContext(bot=mock_bot, interaction=interaction)
    res = await ctx.reply(content="Deferred followup", ephemeral=True)

    interaction.response.send_message.assert_not_called()
    interaction.followup.send.assert_awaited_once()
    assert res == "followup_message"


@pytest.mark.asyncio
async def test_concurrent_40060_falls_back_to_followup(mock_bot):
    """If send_message raises HTTP 40060 (already acknowledged), reply must fallback to followup.send."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False  # Looked fresh locally

    # Simulate Discord 40060 error
    response_mock = MagicMock()
    response_mock.status = 400
    http_err = discord.HTTPException(response_mock, "Interaction has already been acknowledged.")
    http_err.code = 40060

    interaction.response.send_message = AsyncMock(side_effect=http_err)
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock(return_value="fallback_msg")

    ctx = UnifiedContext(bot=mock_bot, interaction=interaction)
    res = await ctx.reply(content="Concurrent message")

    interaction.response.send_message.assert_awaited_once()
    interaction.followup.send.assert_awaited_once()
    assert res == "fallback_msg"


@pytest.mark.asyncio
async def test_interaction_responded_falls_back_to_followup(mock_bot):
    """If discord.InteractionResponded is raised, reply must fallback to followup.send."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False

    interaction.response.send_message = AsyncMock(side_effect=discord.InteractionResponded(interaction))
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock(return_value="fallback_msg_2")

    ctx = UnifiedContext(bot=mock_bot, interaction=interaction)
    res = await ctx.reply(content="Responded message")

    interaction.response.send_message.assert_awaited_once()
    interaction.followup.send.assert_awaited_once()
    assert res == "fallback_msg_2"


@pytest.mark.asyncio
async def test_prefix_context_uses_prefix_reply(mock_bot):
    """Prefix context must invoke prefix_ctx.reply without author mention."""
    prefix_ctx = MagicMock()
    prefix_ctx.reply = AsyncMock(return_value="prefix_msg")

    ctx = UnifiedContext(bot=mock_bot, prefix_ctx=prefix_ctx)
    res = await ctx.reply(content="Prefix response")

    prefix_ctx.reply.assert_awaited_once_with(
        content="Prefix response",
        embeds=[],
        view=discord.utils.MISSING,
        mention_author=False,
    )
    assert res == "prefix_msg"


@pytest.mark.asyncio
async def test_ephemeral_flag_propagation(mock_bot):
    """Ephemeral flag set in defer() must propagate to followup.send."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock(return_value="ephemeral_followup")

    ctx = UnifiedContext(bot=mock_bot, interaction=interaction)
    await ctx.defer(ephemeral=True)

    interaction.response.is_done.return_value = True  # now deferred
    await ctx.reply(content="Protected data")

    interaction.followup.send.assert_awaited_once_with(
        content="Protected data",
        embeds=[],
        view=discord.utils.MISSING,
        ephemeral=True,
        wait=True,
    )

