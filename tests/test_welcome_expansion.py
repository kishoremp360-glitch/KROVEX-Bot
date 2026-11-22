"""Unit tests for Welcome cog expansion commands."""

from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.welcome.cog import Welcome
from bot.core.context import UnifiedContext


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.db = MagicMock()
    bot.db_manager = bot.db
    bot.db.execute = AsyncMock()
    bot.db.fetchone = AsyncMock(return_value={"goodbye_template": "Farewell {user}!"})
    bot.welcome_repo = MagicMock()
    bot.welcome_repo.get_or_create = AsyncMock(return_value=None)
    return bot


def _make_ctx():
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock()
    ctx.guild.id = 111111
    ctx.guild.name = "Welcome Server"
    ctx.guild.member_count = 42
    ctx.guild.me = MagicMock()
    ctx.guild.me.top_role = MagicMock(position=50)
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.name = "TestUser"
    ctx.author.mention = "<@123>"
    ctx.reply = AsyncMock()
    ctx.send_success = AsyncMock()
    ctx.send_error = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_welcome_setup_and_message(mock_bot):
    """Test welcomesetup and welcomemessage configuration."""
    cog = Welcome(mock_bot)
    ctx = _make_ctx()
    mock_ch = MagicMock(spec=discord.TextChannel)
    mock_ch.id = 333
    mock_ch.mention = "<#333>"

    # Setup channel
    await cog._execute_welcomesetup(ctx, mock_ch)
    mock_bot.db.execute.assert_awaited()
    ctx.send_success.assert_awaited()

    # Set template
    await cog._execute_welcomemessage(ctx, "Hello {user} welcome to {server}!")
    mock_bot.db.execute.assert_awaited()
    ctx.send_success.assert_awaited()


@pytest.mark.asyncio
async def test_welcome_color_and_goodbye(mock_bot):
    """Test welcomecolor hex parsing and goodbyetest simulation."""
    cog = Welcome(mock_bot)
    ctx = _make_ctx()

    # Valid color
    await cog._execute_welcomecolor(ctx, "#9D4EDD")
    mock_bot.db.execute.assert_awaited()
    ctx.send_success.assert_awaited()

    # Invalid color
    await cog._execute_welcomecolor(ctx, "invalidhex")
    ctx.send_error.assert_awaited_with("Invalid Color", "Please provide a valid 6-character hex code (e.g. `#9D4EDD`).")

    # Goodbye test preview
    await cog._execute_goodbyetest(ctx)
    ctx.reply.assert_awaited()

