"""Comprehensive Automated Tests for Batch 2B: Ratings & Fun Module (20 Commands)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.config import BotConfig
from bot.core.bot import DeathBot
from bot.core.context import UnifiedContext
from bot.cogs.fun.ratings import RatingsFun
from bot.cogs.fun._ratings_data import (
    get_user_metric,
    get_pair_metric,
    generate_bar,
    ROAST_POOL,
    RELATIONSHIP_STATUSES,
)
from bot.cogs.utility.help import ZerinaHelpView


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 999999999
    bot.user.name = "Death Bot"
    return bot


def _make_ctx(guild_id: int = 123456, author_id: int = 1111):
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock(spec=discord.Guild)
    ctx.guild.id = guild_id
    ctx.guild.name = "Ratings Test Guild"
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = author_id
    ctx.author.name = "TestAuthor"
    ctx.author.display_name = "TestAuthor"
    ctx.author.mention = f"<@{author_id}>"
    ctx.author.display_avatar.url = "https://example.com/author.png"
    ctx.reply = AsyncMock()
    ctx.send_error = AsyncMock()
    ctx.send_success = AsyncMock()
    return ctx


EXPECTED_COMMANDS = {
    "gay", "howgay", "gaymeter", "lesbian",
    "cute", "intelligence", "horny", "tharki", "iq", "dumb",
    "simprate", "toxic", "genius", "brainrate", "howhot",
    "chutiya", "autorelationship", "roast",
}


@pytest.mark.asyncio
async def test_ratings_fun_all_commands_registered():
    """Verify all 18 commands are genuinely registered in the cog (love/lovemeter unified into AnimeSocial ship)."""
    bot = DeathBot(config=BotConfig.from_env(validate=False))
    await bot.load_extension("bot.cogs.fun.ratings")

    cog = bot.cogs.get("Ratings & Fun")
    assert cog is not None, "Ratings & Fun cog failed to load."

    registered_cmds = {cmd.name for cmd in cog.get_commands()}
    assert len(registered_cmds) == 18, f"Expected exactly 18 commands, got {len(registered_cmds)}"
    assert registered_cmds == EXPECTED_COMMANDS


@pytest.mark.asyncio
async def test_slash_commands_under_limit():
    """Verify total top-level Slash commands stay strictly under Discord's 100 limit."""
    bot = DeathBot(config=BotConfig.from_env(validate=False))
    await bot.load_cogs()

    top_level_cmds = bot.tree.get_commands()
    assert len(top_level_cmds) <= 100, f"Exceeded Discord 100 limit: {len(top_level_cmds)}"

    # Verify /rate group and subcommands
    rate_group = next((cmd for cmd in top_level_cmds if cmd.name == "rate"), None)
    assert rate_group is not None, "/rate command group must be registered"
    assert len(rate_group.commands) >= 12


@pytest.mark.asyncio
async def test_meter_score_range_and_progress_bars():
    """Test score calculation range (0-100), determinism, and bar generator."""
    score1 = get_user_metric(12345, "cute")
    score2 = get_user_metric(12345, "cute")
    assert score1 == score2, "Metric must be deterministic per day"
    assert 0 <= score1 <= 100

    bar_full = generate_bar(100, 0, 100, 10)
    assert bar_full == "██████████"

    bar_half = generate_bar(50, 0, 100, 10)
    assert bar_half == "█████░░░░░"

    bar_zero = generate_bar(0, 0, 100, 10)
    assert bar_zero == "░░░░░░░░░░"


@pytest.mark.asyncio
async def test_optional_target_and_self_targeting(mock_bot):
    """Test optional target handling: defaults to author when target is None."""
    cog = RatingsFun(mock_bot)
    ctx = _make_ctx()

    # Call with target=None
    await cog._execute_meter(ctx, "cute", target=None)
    ctx.reply.assert_awaited()
    embed = ctx.reply.call_args[1]["embed"]
    assert "<@1111>" in embed.description
    assert "Cuteness Rating" in embed.title

    # Call with explicit target
    ctx.reply.reset_mock()
    target = MagicMock(spec=discord.Member)
    target.id = 8888
    target.mention = "<@8888>"
    target.display_avatar.url = "https://example.com/target.png"

    await cog._execute_meter(ctx, "cute", target=target)
    ctx.reply.assert_awaited()
    embed = ctx.reply.call_args[1]["embed"]
    assert "<@8888>" in embed.description


@pytest.mark.asyncio
async def test_love_and_lovemeter(mock_bot):
    """Test love compatibility calculation, self-love, and commutativity."""
    cog = RatingsFun(mock_bot)
    ctx = _make_ctx()

    # 1. Self love test
    await cog._execute_love(ctx, user1=None, user2=None)
    ctx.reply.assert_awaited()
    self_embed = ctx.reply.call_args[1]["embed"]
    assert "Self-Love Affinity • 100%" in self_embed.title
    assert "TestAuthor" in self_embed.description

    # 2. Two user compatibility test
    ctx.reply.reset_mock()
    t1 = MagicMock(spec=discord.Member)
    t1.id = 1001
    t1.mention = "<@1001>"
    t2 = MagicMock(spec=discord.Member)
    t2.id = 1002
    t2.mention = "<@1002>"
    t2.display_avatar.url = "https://example.com/t2.png"

    await cog._execute_love(ctx, user1=t1, user2=t2)
    ctx.reply.assert_awaited()
    duo_embed = ctx.reply.call_args[1]["embed"]
    assert "Love Meter" in duo_embed.title
    assert "<@1001> + <@1002>" in duo_embed.description

    # 3. Commutativity test
    score1 = get_pair_metric(1001, 1002, "love")
    score2 = get_pair_metric(1002, 1001, "love")
    assert score1 == score2, "Love score must be commutative"


@pytest.mark.asyncio
async def test_autorelationship(mock_bot):
    """Test autorelationship matchmaking and random guild member selector."""
    cog = RatingsFun(mock_bot)
    ctx = _make_ctx()

    # Test error when guild members < 2
    ctx.guild.members = [ctx.author]
    await cog._execute_autorelationship(ctx, None, None)
    ctx.send_error.assert_awaited_with("Not Enough Members", "At least 2 non-bot members are required for autorelationship!")

    # Test random selection when members >= 2
    ctx.send_error.reset_mock()
    m1 = MagicMock(spec=discord.Member)
    m1.id = 2001
    m1.mention = "<@2001>"
    m1.bot = False
    m1.display_avatar.url = "https://example.com/m1.png"

    m2 = MagicMock(spec=discord.Member)
    m2.id = 2002
    m2.mention = "<@2002>"
    m2.bot = False
    m2.display_avatar.url = "https://example.com/m2.png"

    ctx.guild.members = [m1, m2]
    await cog._execute_autorelationship(ctx, None, None)
    ctx.reply.assert_awaited()
    embed = ctx.reply.call_args[1]["embed"]
    assert "Auto-Relationship Generator" in embed.title
    assert "<@2001>" in embed.description
    assert "<@2002>" in embed.description
    assert any(status.split()[0] in embed.description for status in RELATIONSHIP_STATUSES)


@pytest.mark.asyncio
async def test_roast_variety_and_self_roast_guard(mock_bot):
    """Test witty comedy roasts, variety, and self-roast empathy guard."""
    cog = RatingsFun(mock_bot)
    ctx = _make_ctx()

    # 1. Self-roast attempt -> denied
    await cog._execute_roast(ctx, target=None)
    ctx.reply.assert_awaited()
    embed = ctx.reply.call_args[1]["embed"]
    assert "Self-Roast Denied" in embed.title
    assert "doesn't punch down" in embed.description

    # 2. Roast another user -> delivered
    ctx.reply.reset_mock()
    target = MagicMock(spec=discord.Member)
    target.id = 9991
    target.mention = "<@9991>"
    target.display_avatar.url = "https://example.com/target.png"

    await cog._execute_roast(ctx, target=target)
    ctx.reply.assert_awaited()
    roast_embed = ctx.reply.call_args[1]["embed"]
    assert "Roasted!" in roast_embed.title
    assert "<@9991>" in roast_embed.description
    assert any(r in roast_embed.description for r in ROAST_POOL)


@pytest.mark.asyncio
async def test_iq_intelligence_genius(mock_bot):
    """Test IQ rating range (50-220), progress bar, and commentary."""
    cog = RatingsFun(mock_bot)
    ctx = _make_ctx()

    await cog._execute_iq(ctx, target=None)
    ctx.reply.assert_awaited()
    embed = ctx.reply.call_args[1]["embed"]
    assert "Big Brain / IQ Assessment" in embed.title
    assert "Fictional IQ:" in embed.description

    iq = get_user_metric(1111, "iq_score", 50, 220)
    assert 50 <= iq <= 220


@pytest.mark.asyncio
async def test_sfw_and_harassment_guardrails(mock_bot):
    """Verify SFW compliance, cartoon humor, and fictional disclaimers."""
    cog = RatingsFun(mock_bot)
    ctx = _make_ctx()

    # 1. Gay / Lesbian disclaimer
    await cog._execute_meter(ctx, "gay", None)
    ctx.reply.assert_awaited()
    embed = ctx.reply.call_args[1]["embed"]
    assert "Fictional rating for entertainment purposes only" in embed.footer.text

    # 2. Horny / Tharki SFW cartoon humor
    ctx.reply.reset_mock()
    await cog._execute_meter(ctx, "horny", None)
    ctx.reply.assert_awaited()
    horny_embed = ctx.reply.call_args[1]["embed"]
    assert "Horny / Mischief Rating" in horny_embed.title

    ctx.reply.reset_mock()
    await cog._execute_meter(ctx, "tharki", None)
    ctx.reply.assert_awaited()
    tharki_embed = ctx.reply.call_args[1]["embed"]
    assert "Tharki / Flirty Meter" in tharki_embed.title


@pytest.mark.asyncio
async def test_zerina_help_integration():
    """Verify Zerina help menu integration for Ratings & Fun module."""
    bot = DeathBot(config=BotConfig.from_env(validate=False))
    await bot.load_extension("bot.cogs.fun.ratings")
    await bot.load_extension("bot.cogs.utility.help")

    author = MagicMock(spec=discord.Member)
    author.id = 1234
    author.mention = "<@1234>"

    view = ZerinaHelpView(bot, author, prefix=",")

    # Verify home embed shows Ratings & Fun
    home_embed = view.build_home_embed()
    assert any("Ratings & Fun" in f.value for f in home_embed.fields)

    # Verify category embed lists commands
    cat_embed = view.build_category_embed("Ratings & Fun", page=1)
    assert "🎯 Ratings & Fun Meters" in cat_embed.title
    assert "**Total Commands in this Module:** `18`" in cat_embed.description
    assert len(cat_embed.fields) == 8

    # Verify page 2
    cat_embed_p2 = view.build_category_embed("Ratings & Fun", page=2)
    assert len(cat_embed_p2.fields) == 8

