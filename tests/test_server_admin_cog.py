"""Unit tests for ServerAdmin cog."""

from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.admin.cog import ServerAdmin, _parse_color
from bot.core.context import UnifiedContext


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.db = MagicMock()
    bot.db_manager = bot.db
    bot.admin_repo = MagicMock()
    bot.admin_repo.set_prefix = AsyncMock()
    bot.admin_repo.get_rules = AsyncMock(return_value=[{"rule_index": 1, "title": "Be respectful", "content": "No hate speech"}])
    bot.admin_repo.add_rule = AsyncMock()
    bot.admin_repo.remove_rule = AsyncMock(return_value=True)
    return bot


def _make_admin_ctx(guild=None):
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = guild or MagicMock()
    ctx.guild.id = 111111
    ctx.guild.name = "Admin Test Server"
    ctx.guild.owner_id = 999999
    ctx.guild.me = MagicMock()
    ctx.guild.me.top_role = MagicMock(position=50)
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = 999999  # Owner
    ctx.author.top_role = MagicMock(position=100)
    ctx.reply = AsyncMock()
    ctx.send_success = AsyncMock()
    ctx.send_error = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_setprefix(mock_bot):
    """Test setprefix command updates prefix in repository."""
    cog = ServerAdmin(mock_bot)
    ctx = _make_admin_ctx()

    await cog._execute_setprefix(ctx, "?")
    mock_bot.admin_repo.set_prefix.assert_awaited_with(111111, "?")
    ctx.send_success.assert_awaited()

    # Invalid prefix (too long)
    await cog._execute_setprefix(ctx, "toolongprefix")
    ctx.send_error.assert_awaited_with("Invalid Prefix", "Prefix must be between 1 and 5 characters.")


@pytest.mark.asyncio
async def test_channel_create_and_delete(mock_bot):
    """Test channel creation and deletion operations."""
    cog = ServerAdmin(mock_bot)
    ctx = _make_admin_ctx()
    mock_ch = MagicMock(spec=discord.TextChannel)
    mock_ch.name = "announcements"
    mock_ch.delete = AsyncMock()
    ctx.guild.create_text_channel = AsyncMock(return_value=mock_ch)

    # Create text channel
    await cog._execute_channelcreate(ctx, "announcements", "text")
    ctx.guild.create_text_channel.assert_awaited_with(name="announcements", reason=f"Created by {ctx.author}")
    ctx.send_success.assert_awaited()

    # Delete channel
    await cog._execute_channeldelete(ctx, mock_ch, "Cleanup")
    mock_ch.delete.assert_awaited()
    ctx.send_success.assert_awaited()


@pytest.mark.asyncio
async def test_role_create_and_hierarchy(mock_bot):
    """Test role creation and hierarchy validation."""
    cog = ServerAdmin(mock_bot)
    ctx = _make_admin_ctx()
    mock_role = MagicMock(spec=discord.Role)
    mock_role.name = "Vanguard"
    mock_role.position = 20
    ctx.guild.create_role = AsyncMock(return_value=mock_role)

    # Create role
    await cog._execute_rolecreate(ctx, "Vanguard", "#9D4EDD")
    ctx.guild.create_role.assert_awaited()
    ctx.send_success.assert_awaited()

    # Color parser
    c = _parse_color("#9D4EDD")
    assert c is not None
    assert c.value == 0x9D4EDD


@pytest.mark.asyncio
async def test_rules_crud(mock_bot):
    """Test server rules listing and removing."""
    cog = ServerAdmin(mock_bot)
    ctx = _make_admin_ctx()

    # Add rule
    await cog._execute_rulesadd(ctx, "No Spam", "Do not flood channels")
    mock_bot.admin_repo.add_rule.assert_awaited()

    # Remove rule
    await cog._execute_rulesremove(ctx, 1)
    mock_bot.admin_repo.remove_rule.assert_awaited_with(111111, 1)

    # List rules
    await cog._execute_ruleslist(ctx)
    ctx.reply.assert_awaited()

