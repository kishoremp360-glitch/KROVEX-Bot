"""Unit tests for SetupWizard cog."""

from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.admin.setup_wizard import SetupWizard, WizardCancelView
from bot.core.context import UnifiedContext


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


def _make_ctx():
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock()
    ctx.guild.id = 111111
    ctx.guild.name = "Wizard Server"
    ctx.guild.verification_level = discord.VerificationLevel.medium
    ctx.guild.system_channel = None
    ctx.guild.afk_channel = None
    ctx.guild.roles = []
    ctx.guild.me = MagicMock()
    ctx.guild.me.top_role = MagicMock(mention="<@&1>", position=50)
    ctx.channel = MagicMock(spec=discord.TextChannel)
    ctx.channel.id = 999
    ctx.channel.mention = "<#999>"
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = 12345
    ctx.reply = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_setupserver_and_roles(mock_bot):
    """Test setupserver and setuproles wizard displays."""
    cog = SetupWizard(mock_bot)
    ctx = _make_ctx()

    await cog._execute_setupserver(ctx)
    ctx.reply.assert_awaited()
    assert isinstance(ctx.reply.call_args[1]["view"], WizardCancelView)

    ctx.reply.reset_mock()
    await cog._execute_setuproles(ctx)
    ctx.reply.assert_awaited()


@pytest.mark.asyncio
async def test_setuplogging_and_welcome(mock_bot):
    """Test setuplogging one-click and setupwelcome wizards."""
    cog = SetupWizard(mock_bot)
    ctx = _make_ctx()

    # Setup logging
    await cog._execute_setuplogging(ctx, ctx.channel)
    mock_bot.logging_repo.update_settings.assert_awaited()
    ctx.reply.assert_awaited()

    # Setup welcome
    ctx.reply.reset_mock()
    await cog._execute_setupwelcome(ctx, ctx.channel)
    mock_bot.db.execute.assert_awaited()
    ctx.reply.assert_awaited()

