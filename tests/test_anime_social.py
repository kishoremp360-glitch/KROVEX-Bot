"""Comprehensive Automated Tests for Batch 2A: Anime & Social Interactions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.config import BotConfig
from bot.core.bot import DeathBot
from bot.core.context import UnifiedContext
from bot.cogs.social.interactions import AnimeSocial
from bot.cogs.social._anime_data import (
    calculate_ship_score,
    format_ship_result,
    ANIME_ACTION_GIFS,
)
from bot.cogs.utility.help import ZerinaHelpView


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 999999999
    bot.user.name = "Death Bot"
    bot.session = MagicMock()
    return bot


def _make_ctx(guild_id: int = 123456, author_id: int = 1111):
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock(spec=discord.Guild)
    ctx.guild.id = guild_id
    ctx.guild.name = "Anime Test Guild"
    ctx.channel = MagicMock(spec=discord.TextChannel)
    ctx.channel.is_nsfw = MagicMock(return_value=False)
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = author_id
    ctx.author.name = "TestAuthor"
    ctx.author.display_name = "TestAuthor"
    ctx.author.mention = f"<@{author_id}>"
    ctx.reply = AsyncMock()
    ctx.send_error = AsyncMock()
    ctx.send_success = AsyncMock()
    return ctx


EXPECTED_49_COMMANDS = {
    "ship", "shipp", "couple", "mydog", "boy", "anime",
    "hug", "kiss", "cuddle", "pat", "pats", "slap", "punch",
    "bite", "boop", "bonk", "bully", "greet", "handholding",
    "handhold", "hold", "kill", "lick", "nom", "poke", "highfive",
    "tickle", "stare", "cheer", "fuck", "lewd", "blush", "cry",
    "dance", "deredere", "grin", "happy", "pout", "sleepy", "smile",
    "smug", "scoff", "teehee", "thinking", "thumbs", "thumbsup",
    "triggered", "wag", "wave",
}


@pytest.mark.asyncio
async def test_anime_social_all_49_commands_registered():
    """Verify all 49 requested commands are genuinely registered in the cog."""
    bot = DeathBot(config=BotConfig.from_env(validate=False))
    await bot.load_extension("bot.cogs.social.interactions")

    cog = bot.cogs.get("Anime & Social Interactions")
    assert cog is not None, "Anime & Social Interactions cog failed to load."

    registered_cmds = {cmd.name for cmd in cog.get_commands()}
    assert len(registered_cmds) == 49, f"Expected exactly 49 commands, got {len(registered_cmds)}"
    assert registered_cmds == EXPECTED_49_COMMANDS


@pytest.mark.asyncio
async def test_slash_commands_under_limit():
    """Verify total top-level Slash commands stay strictly under Discord's 100 limit."""
    bot = DeathBot(config=BotConfig.from_env(validate=False))
    await bot.load_cogs()

    top_level_cmds = bot.tree.get_commands()
    assert len(top_level_cmds) <= 100, f"Exceeded Discord 100 limit: {len(top_level_cmds)}"

    # Verify /interact and /react groups
    interact_group = next((cmd for cmd in top_level_cmds if cmd.name == "interact"), None)
    react_group = next((cmd for cmd in top_level_cmds if cmd.name == "react"), None)

    assert interact_group is not None, "/interact command group must be registered"
    assert react_group is not None, "/react command group must be registered"
    assert len(interact_group.commands) >= 15
    assert len(react_group.commands) >= 15


@pytest.mark.asyncio
async def test_ship_calculation_and_formatting(mock_bot):
    """Test romance compatibility algorithm, deterministic score, and self-ship."""
    cog = AnimeSocial(mock_bot)
    ctx = _make_ctx()

    # 1. Test Self-Ship
    await cog._execute_ship(ctx, ctx.author)
    ctx.reply.assert_awaited()
    embed = ctx.reply.call_args[1]["embed"]
    assert "Self-Love Meter • 100%" in embed.title
    assert "Self-Care Champion" in embed.description

    # 2. Test Duo-Ship
    ctx.reply.reset_mock()
    target = MagicMock(spec=discord.Member)
    target.id = 2222
    target.name = "TargetUser"
    target.display_name = "TargetUser"
    target.mention = "<@2222>"
    target.display_avatar.url = "https://example.com/avatar.png"

    await cog._execute_ship(ctx, target)
    ctx.reply.assert_awaited()
    duo_embed = ctx.reply.call_args[1]["embed"]
    assert "Love Calculator" in duo_embed.title
    assert "<@1111> + <@2222>" in duo_embed.description
    assert "Compatibility:" in duo_embed.description

    # 3. Test Algorithm Determinism
    score1 = calculate_ship_score(1111, 2222)
    score2 = calculate_ship_score(2222, 1111)
    assert score1 == score2, "Ship score must be commutative"
    assert 0 <= score1 <= 100

    name, bar, verdict = format_ship_result("Alice", "Bob", score1)
    assert len(bar) == 10
    assert "█" in bar or "░" in bar


@pytest.mark.asyncio
async def test_couple_selection(mock_bot):
    """Test server couple of the day matchmaking."""
    cog = AnimeSocial(mock_bot)
    ctx = _make_ctx()

    # Test error when < 2 non-bot members
    ctx.guild.members = [ctx.author]
    await cog._execute_couple(ctx)
    ctx.send_error.assert_awaited_with("Not Enough Members", "At least 2 non-bot members are required to find a couple!")

    # Test successful couple pick
    ctx.send_error.reset_mock()
    m1 = MagicMock(spec=discord.Member)
    m1.id = 3001
    m1.display_name = "MemberOne"
    m1.mention = "<@3001>"
    m1.bot = False
    m1.display_avatar.url = "https://example.com/m1.png"

    m2 = MagicMock(spec=discord.Member)
    m2.id = 3002
    m2.display_name = "MemberTwo"
    m2.mention = "<@3002>"
    m2.bot = False
    m2.display_avatar.url = "https://example.com/m2.png"

    bot_m = MagicMock(spec=discord.Member)
    bot_m.bot = True

    ctx.guild.members = [m1, m2, bot_m]
    await cog._execute_couple(ctx)
    ctx.reply.assert_awaited()
    embed = ctx.reply.call_args[1]["embed"]
    assert "Server Couple of the Day" in embed.title
    assert "<@3001>" in embed.description
    assert "<@3002>" in embed.description


@pytest.mark.asyncio
async def test_mydog_and_boy(mock_bot):
    """Test mydog and boy commands."""
    cog = AnimeSocial(mock_bot)
    ctx = _make_ctx()

    # Test mydog with mock API
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"message": "https://images.dog.ceo/test.jpg"})
    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_bot.session = mock_session

    await cog._execute_mydog(ctx)
    ctx.reply.assert_awaited()
    dog_embed = ctx.reply.call_args[1]["embed"]
    assert "Cute Doggo" in dog_embed.title
    assert dog_embed.image.url == "https://images.dog.ceo/test.jpg"

    # Test boy
    ctx.reply.reset_mock()
    await cog._execute_boy(ctx)
    ctx.reply.assert_awaited()
    boy_embed = ctx.reply.call_args[1]["embed"]
    assert "Anime Boy Art" in boy_embed.title
    assert boy_embed.image.url is not None


@pytest.mark.asyncio
async def test_anime_anilist_search(mock_bot):
    """Test AniList anime search, SFW boundary enforcement, and not-found handling."""
    cog = AnimeSocial(mock_bot)
    ctx = _make_ctx()

    # 1. Missing query
    await cog._execute_anime(ctx, "")
    ctx.send_error.assert_awaited_with("Missing Search Query", "Please provide the name of an anime to search for!")

    # 2. Mocked AniList SFW Result
    sfw_anime = {
        "id": 16498,
        "title": {"romaji": "Shingeki no Kyojin", "english": "Attack on Titan"},
        "description": "Centuries ago, mankind was slaughtered by giant titans.",
        "episodes": 25,
        "status": "FINISHED",
        "averageScore": 85,
        "genres": ["Action", "Drama", "Fantasy"],
        "siteUrl": "https://anilist.co/anime/16498",
        "isAdult": False,
        "coverImage": {"large": "https://example.com/cover.jpg"},
        "bannerImage": "https://example.com/banner.jpg",
    }

    with patch("bot.cogs.social._anime_data.fetch_anilist_media", AsyncMock(return_value=sfw_anime)):
        ctx.reply.reset_mock()
        await cog._execute_anime(ctx, "Attack on Titan")
        ctx.reply.assert_awaited()
        embed = ctx.reply.call_args[1]["embed"]
        assert "Attack on Titan" in embed.title
        assert embed.url == "https://anilist.co/anime/16498"
        assert any(f.name == "Episodes" and f.value == "25" for f in embed.fields)
        assert any(f.name == "Average Score" and "85%" in f.value for f in embed.fields)

    # 3. Adult Content in Non-NSFW Channel
    adult_anime = dict(sfw_anime)
    adult_anime["isAdult"] = True
    ctx.channel.is_nsfw.return_value = False

    with patch("bot.cogs.social._anime_data.fetch_anilist_media", AsyncMock(return_value=adult_anime)):
        ctx.send_error.reset_mock()
        await cog._execute_anime(ctx, "Explicit Title")
        ctx.send_error.assert_awaited()
        err_call = ctx.send_error.call_args[0]
        assert "Content Restricted" in err_call[0]

    # 4. Not Found Result
    with patch("bot.cogs.social._anime_data.fetch_anilist_media", AsyncMock(return_value=None)):
        ctx.send_error.reset_mock()
        await cog._execute_anime(ctx, "NonexistentAnime1234567")
        ctx.send_error.assert_awaited()
        err_call = ctx.send_error.call_args[0]
        assert "Not Found" in err_call[0]


@pytest.mark.asyncio
async def test_roleplay_interactions(mock_bot):
    """Test roleplay interactions like hug, kiss, pat, slap, punch, bonk, etc."""
    cog = AnimeSocial(mock_bot)
    ctx = _make_ctx()

    target = MagicMock(spec=discord.Member)
    target.id = 5555
    target.display_name = "Bestie"

    # Test duo hug
    await cog._execute_action(ctx, "hug", target)
    ctx.reply.assert_awaited()
    hug_embed = ctx.reply.call_args[1]["embed"]
    assert "Warm Hug" in hug_embed.title
    assert "TestAuthor gives Bestie a warm, loving hug!" in hug_embed.description
    assert hug_embed.image.url is not None

    # Test solo slap (self slap)
    ctx.reply.reset_mock()
    await cog._execute_action(ctx, "slap", None)
    ctx.reply.assert_awaited()
    slap_embed = ctx.reply.call_args[1]["embed"]
    assert "Anime Slap" in slap_embed.title
    assert "slaps some sense into themselves" in slap_embed.description

    # Test bonk
    ctx.reply.reset_mock()
    await cog._execute_action(ctx, "bonk", target)
    ctx.reply.assert_awaited()
    bonk_embed = ctx.reply.call_args[1]["embed"]
    assert "Horny Jail Bonk" in bonk_embed.title
    assert "Off to horny jail!" in bonk_embed.description


@pytest.mark.asyncio
async def test_safety_compliance_fuck_lewd(mock_bot):
    """Verify fuck and lewd produce 100% SFW cartoon reactions and memes."""
    cog = AnimeSocial(mock_bot)
    ctx = _make_ctx()

    target = MagicMock(spec=discord.Member)
    target.id = 7777
    target.display_name = "Opponent"

    # Test fuck (SFW cartoon angry outburst)
    await cog._execute_action(ctx, "fuck", target)
    ctx.reply.assert_awaited()
    fuck_embed = ctx.reply.call_args[1]["embed"]
    assert "Angry Outburst" in fuck_embed.title
    assert "Harmless cartoon outburst" in fuck_embed.description

    # Test lewd (SFW blushing/facepalm meme)
    ctx.reply.reset_mock()
    await cog._execute_action(ctx, "lewd", target)
    ctx.reply.assert_awaited()
    lewd_embed = ctx.reply.call_args[1]["embed"]
    assert "Too Lewd!" in lewd_embed.title
    assert "way too lewd!" in lewd_embed.description


@pytest.mark.asyncio
async def test_emotional_reactions(mock_bot):
    """Test emotional reaction commands like cry, dance, blush, pout, sleepy, etc."""
    cog = AnimeSocial(mock_bot)
    ctx = _make_ctx()

    reactions = ["cry", "dance", "blush", "pout", "sleepy", "smile", "smug", "triggered", "wag", "wave"]
    for react in reactions:
        ctx.reply.reset_mock()
        await cog._execute_action(ctx, react, None)
        ctx.reply.assert_awaited()
        embed = ctx.reply.call_args[1]["embed"]
        assert embed.title is not None
        assert embed.description is not None
        assert embed.image.url is not None


@pytest.mark.asyncio
async def test_zerina_help_integration():
    """Verify Zerina help menu integration for Anime & Social Interactions module."""
    bot = DeathBot(config=BotConfig.from_env(validate=False))
    await bot.load_extension("bot.cogs.social.interactions")
    await bot.load_extension("bot.cogs.utility.help")

    author = MagicMock(spec=discord.Member)
    author.id = 1234
    author.mention = "<@1234>"

    view = ZerinaHelpView(bot, author, prefix=",")

    # Verify home embed shows Anime & Social Interactions
    home_embed = view.build_home_embed()
    assert any("Anime & Social Interactions" in f.value for f in home_embed.fields)

    # Verify category embed lists commands
    cat_embed = view.build_category_embed("Anime & Social Interactions", page=1)
    assert "Anime & Social Interactions" in cat_embed.title
    assert "**Total Commands in this Module:** `49`" in cat_embed.description
    assert len(cat_embed.fields) == 8

    # Verify page 2
    cat_embed_p2 = view.build_category_embed("Anime & Social Interactions", page=2)
    assert len(cat_embed_p2.fields) == 8
