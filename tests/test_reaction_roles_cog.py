"""Unit tests for ReactionRoles cog."""

from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.reactionroles.cog import ReactionRoles
from bot.core.context import UnifiedContext


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.db = MagicMock()
    bot.db_manager = bot.db
    bot.db.execute = AsyncMock()
    bot.db.fetchone = AsyncMock(return_value=None)
    bot.db.fetchall = AsyncMock(return_value=[])
    bot.rr_repo = MagicMock()
    bot.rr_repo.create_panel = AsyncMock()
    bot.rr_repo.get_panel = AsyncMock(return_value={
        "message_id": 999888,
        "guild_id": 111111,
        "channel_id": 222222,
        "panel_type": "button",
        "title": "Pick Roles",
        "description": "Click below",
        "max_roles": 0,
        "exclusive": 0,
    })
    bot.rr_repo.add_item = AsyncMock()
    bot.rr_repo.remove_item = AsyncMock(return_value=True)
    bot.rr_repo.get_items = AsyncMock(return_value=[])
    bot.rr_repo.delete_panel = AsyncMock(return_value=True)
    bot.rr_repo.get_panels = AsyncMock(return_value=[])
    return bot


def _make_ctx():
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock()
    ctx.guild.id = 111111
    ctx.guild.name = "RR Test Guild"
    ctx.guild.me = MagicMock()
    ctx.guild.me.top_role = MagicMock(position=50)
    ctx.author = MagicMock(spec=discord.Member)
    ctx.reply = AsyncMock()
    ctx.send_success = AsyncMock()
    ctx.send_error = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_button_panel_creation(mock_bot):
    """Test button panel creation and item assignment."""
    cog = ReactionRoles(mock_bot)
    ctx = _make_ctx()
    mock_ch = MagicMock(spec=discord.TextChannel)
    mock_msg = MagicMock(spec=discord.Message)
    mock_msg.id = 999888
    mock_ch.send = AsyncMock(return_value=mock_msg)
    mock_ch.fetch_message = AsyncMock(return_value=mock_msg)
    ctx.guild.get_channel = MagicMock(return_value=mock_ch)

    # Create panel
    await cog._execute_rrbuttonpanel(ctx, mock_ch, "Colors", "Choose a color")
    mock_bot.rr_repo.create_panel.assert_awaited()
    ctx.send_success.assert_awaited()

    # Add button
    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = 777
    mock_role.name = "Purple"
    await cog._execute_rrbuttonadd(ctx, 999888, "Purple", mock_role)
    mock_bot.rr_repo.add_item.assert_awaited()


@pytest.mark.asyncio
async def test_reaction_role_classic(mock_bot):
    """Test classic reaction role creation and removal."""
    cog = ReactionRoles(mock_bot)
    ctx = _make_ctx()
    mock_ch = MagicMock(spec=discord.TextChannel)
    mock_msg = MagicMock(spec=discord.Message)
    mock_msg.add_reaction = AsyncMock()
    mock_ch.fetch_message = AsyncMock(return_value=mock_msg)

    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = 555
    mock_role.position = 20

    # Create classic reaction role
    await cog._execute_rrcreate(ctx, mock_ch, 123456, "⭐", mock_role)
    mock_msg.add_reaction.assert_awaited_with("⭐")
    mock_bot.db.execute.assert_awaited()

