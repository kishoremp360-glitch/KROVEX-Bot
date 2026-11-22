"""Unit tests for the complete 15-command Utility Cog."""

from unittest.mock import AsyncMock, MagicMock
import pytest
import discord
from discord.ext import commands

from bot.cogs.utility.cog import Utility
from bot.core.context import UnifiedContext


@pytest.fixture
def mock_bot():
    """Mock DeathBot instance for cog execution."""
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.user.name = "Death Bot"
    bot.user.display_avatar.url = "https://example.com/avatar.png"
    bot.uptime_seconds = 3665.0
    bot.start_time = MagicMock()
    bot.start_time.timestamp.return_value = 1700000000
    bot.latency = 0.042
    bot.guilds = [MagicMock()]
    bot.guilds[0].member_count = 150
    bot.shard_count = 1
    bot.config = MagicMock()
    bot.config.application_id = "1570428426974662718"
    bot.config.owner_ids = [123456789]
    bot.db_manager = MagicMock()
    bot.db_manager.is_connected = True
    return bot


@pytest.mark.asyncio
async def test_utility_ping(mock_bot):
    """Test ping command execution."""
    cog = Utility(mock_bot)
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock()
    ctx.guild.shard_id = 0
    ctx.reply = AsyncMock(return_value=MagicMock())
    ctx.edit = AsyncMock()

    await cog._execute_ping(ctx)
    ctx.reply.assert_awaited_once()
    ctx.edit.assert_awaited_once()


@pytest.mark.asyncio
async def test_utility_uptime(mock_bot):
    """Test uptime command calculation."""
    cog = Utility(mock_bot)
    ctx = MagicMock(spec=UnifiedContext)
    ctx.reply = AsyncMock()

    await cog._execute_uptime(ctx)
    ctx.reply.assert_awaited_once()
    embed = ctx.reply.call_args[1]["embed"]
    assert "Process Uptime" in embed.title


@pytest.mark.asyncio
async def test_utility_botinfo(mock_bot):
    """Test botinfo platform overview."""
    cog = Utility(mock_bot)
    ctx = MagicMock(spec=UnifiedContext)
    ctx.reply = AsyncMock()

    await cog._execute_botinfo(ctx)
    ctx.reply.assert_awaited_once()
    embed = ctx.reply.call_args[1]["embed"]
    assert "System Specifications" in embed.title


@pytest.mark.asyncio
async def test_utility_membercount(mock_bot):
    """Test membercount breakdown."""
    cog = Utility(mock_bot)
    ctx = MagicMock(spec=UnifiedContext)
    guild = MagicMock()
    guild.name = "Test Sanctuary"
    guild.member_count = 100
    m_human = MagicMock()
    m_human.bot = False
    m_bot = MagicMock()
    m_bot.bot = True
    guild.members = [m_human] * 80 + [m_bot] * 20
    ctx.guild = guild
    ctx.reply = AsyncMock()

    await cog._execute_membercount(ctx)
    ctx.reply.assert_awaited_once()
    embed = ctx.reply.call_args[1]["embed"]
    assert "Member Count" in embed.title


@pytest.mark.asyncio
async def test_utility_permissions(mock_bot):
    """Test permissions reporting."""
    cog = Utility(mock_bot)
    ctx = MagicMock(spec=UnifiedContext)
    guild = MagicMock()
    ctx.guild = guild
    author = MagicMock(spec=discord.Member)
    author.display_name = "Kishore"
    author.display_avatar.url = "https://example.com/avatar.png"
    author.guild_permissions = discord.Permissions(administrator=True, manage_guild=True)
    ctx.author = author
    ctx.reply = AsyncMock()

    await cog._execute_permissions(ctx, author)
    ctx.reply.assert_awaited_once()
    embed = ctx.reply.call_args[1]["embed"]
    assert "Key Permissions" in embed.title


@pytest.mark.asyncio
async def test_utility_invite(mock_bot):
    """Test invite link generation with BotConfig."""
    from bot.config import BotConfig
    from bot.utils.permissions import get_krovex_invite_permissions
    cfg = BotConfig(token="fake", client_id=1570428426974662718, dev_guild_id=1560990395666538529)
    mock_bot.config = cfg
    cog = Utility(mock_bot)

    ctx = MagicMock(spec=UnifiedContext)
    ctx.reply = AsyncMock()

    await cog._execute_invite(ctx)
    ctx.reply.assert_awaited_once()
    embed = ctx.reply.call_args[1]["embed"]
    assert "Invite" in embed.title
    assert "1570428426974662718" in embed.description
    assert "permissions=8" not in embed.description
    assert "permissions=1374690864374" in embed.description

    # Assert administrator is strictly False
    perms = get_krovex_invite_permissions()
    assert perms.administrator is False


@pytest.mark.asyncio
async def test_utility_invite_fallback_resilience(mock_bot):
    """Test invite link generation when bot.user and bot.config are completely None."""
    mock_bot.user = None
    mock_bot.config = None
    mock_bot.application_id = None
    cog = Utility(mock_bot)

    ctx = MagicMock(spec=UnifiedContext)
    ctx.reply = AsyncMock()

    # Must execute cleanly without raising TypeError or System Error
    await cog._execute_invite(ctx)
    ctx.reply.assert_awaited_once()
    embed = ctx.reply.call_args[1]["embed"]
    assert "1570428426974662718" in embed.description
    assert "permissions=8" not in embed.description
    assert "permissions=1374690864374" in embed.description


