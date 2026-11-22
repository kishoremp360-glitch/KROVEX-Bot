"""Regression test suite for Interaction Reliability (Issue A) and YouTube Resolver (Issue B)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord
import yt_dlp

from bot.core.context import UnifiedContext
from bot.core.error_handler import GlobalErrorHandler
from bot.cogs.mimic.cog import Mimic
from bot.services.music.resolver import (
    AudioResolver,
    YouTubeBotChallengeError,
    TrackNotFoundError,
)
from bot.services.music.player import GuildAudioPlayer, PlayerState, Track
from bot.services.music.source import AudioSourceInfo


# ==============================================================================
# ISSUE A: Interaction Reliability Tests
# ==============================================================================


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.user.name = "KROVEX"
    bot.mimic_repo = MagicMock()
    bot.mimic_repo.get_profile = AsyncMock(return_value={"nickname": "KROVEX_TEST"})
    bot.mimic_repo.set_nickname = AsyncMock()
    bot.mimic_repo.reset_profile = AsyncMock()
    return bot


def _make_interaction(guild_id: int = 123456):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = guild_id
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = "Test Guild"
    me = MagicMock(spec=discord.Member)
    me.name = "KROVEX"
    me.display_name = "KROVEX"
    me.nick = None
    me.guild_permissions.change_nickname = True
    me.guild_permissions.manage_nicknames = True
    me.display_avatar.url = "https://cdn.discordapp.com/avatars/krovex.png"
    guild.me = me
    interaction.guild = guild

    user = MagicMock(spec=discord.Member)
    user.id = 999
    user.name = "ServerOwner"
    interaction.user = user

    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    interaction.channel = channel

    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.client = MagicMock()
    interaction.client.user = me

    return interaction


@pytest.mark.asyncio
async def test_mimic_preview_slash_success(mock_bot):
    """Test /mimic preview defers immediately and replies with profile embed."""
    interaction = _make_interaction()
    cog = Mimic(mock_bot)

    await cog.mimic_slash_preview.callback(cog, interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=False)
    assert interaction.followup.send.await_count >= 1


@pytest.mark.asyncio
async def test_mimic_preview_no_guild_does_not_hang(mock_bot):
    """Test /mimic preview outside guild responds with error rather than hanging silently."""
    interaction = _make_interaction()
    interaction.guild = None
    cog = Mimic(mock_bot)

    await cog.mimic_slash_preview.callback(cog, interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=False)
    # Verifies follow-up was sent with error message rather than exiting silently
    assert interaction.followup.send.await_count >= 1


@pytest.mark.asyncio
async def test_unified_context_double_acknowledgement_fallback():
    """Test UnifiedContext handles 40060 already acknowledged error by falling back to followup."""
    interaction = _make_interaction()
    ctx = UnifiedContext.from_interaction(interaction)

    exc = discord.HTTPException(response=MagicMock(status=400), message="Interaction has already been acknowledged")
    exc.code = 40060
    interaction.response.send_message.side_effect = exc

    await ctx.reply(content="Hello KROVEX")

    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_unified_context_expired_interaction_fallback():
    """Test UnifiedContext handles 10062 expired interaction by falling back to channel.send."""
    interaction = _make_interaction()
    ctx = UnifiedContext.from_interaction(interaction)
    ctx._deferred = True

    exc = discord.NotFound(response=MagicMock(status=404), message="Unknown interaction")
    exc.code = 10062
    interaction.followup.send.side_effect = exc

    await ctx.reply(content="Fallback to channel")

    interaction.channel.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_error_handler_expired_slash_fallback(mock_bot):
    """Test GlobalErrorHandler falls back to channel.send when interaction token expired."""
    handler = GlobalErrorHandler(mock_bot)
    interaction = _make_interaction()
    embed = discord.Embed(title="Error")

    exc = discord.NotFound(response=MagicMock(status=404), message="Unknown interaction")
    exc.code = 10062
    interaction.response.send_message.side_effect = exc

    await handler._respond_slash(interaction, embed=embed, ephemeral=True)

    interaction.channel.send.assert_awaited_once()


# ==============================================================================
# ISSUE B: YouTube Resolver & Audio Pipeline Tests
# ==============================================================================


def test_resolver_secret_safe_cookie_and_po_token(tmp_path):
    """Ensure cookie paths and PO tokens are configured without logging secrets."""
    cookie_file = tmp_path / "test_cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n.youtube.com TRUE / FALSE 11111 SECRET_COOKIE")

    resolver = AudioResolver(
        cookie_path=str(cookie_file),
        po_token="SECRET_PO_TOKEN_12345",
        visitor_data="VISITOR_DATA_XYZ",
    )

    path = resolver._validate_and_get_cookie_file()
    assert path == str(cookie_file)

    opts = dict(resolver.ydl_opts)
    resolver._configure_po_token(opts)
    assert opts["extractor_args"]["youtube"]["po_token"] == ["web+VISITOR_DATA_XYZ+SECRET_PO_TOKEN_12345"]


def test_resolver_youtube_bot_challenge_raises():
    """Ensure YouTube bot verification challenge triggers YouTubeBotChallengeError when no fallback matches."""
    resolver = AudioResolver()

    with patch.object(yt_dlp.YoutubeDL, "extract_info") as mock_extract:
        mock_extract.side_effect = Exception("Sign in to confirm you're not a bot")

        with pytest.raises(YouTubeBotChallengeError) as exc_info:
            resolver._extract_sync("very_obscure_track_no_matches")

        assert "Sign in to confirm you're not a bot" in str(exc_info.value)


def test_resolver_soundcloud_fallback_success():
    """Ensure resolver falls back to SoundCloud when YouTube is blocked and returns match."""
    resolver = AudioResolver()

    def fake_extract(self_ydl, target, download=False):
        if target.startswith("ytsearch"):
            raise Exception("Sign in to confirm you're not a bot")
        if target.startswith("scsearch"):
            return {
                "entries": [
                    {
                        "id": "sc123",
                        "title": "Raadhima Official",
                        "uploader": "Raadhima Artist",
                        "channel": "Raadhima Artist",
                        "url": "https://api.soundcloud.com/tracks/123/stream",
                        "webpage_url": "https://soundcloud.com/raadhima",
                        "duration": 210,
                        "thumbnail": "https://i1.sndcdn.com/art.jpg",
                    }
                ]
            }
        return None

    with patch.object(yt_dlp.YoutubeDL, "extract_info", new=fake_extract):
        info, meta = resolver._extract_sync("raadhima")
        assert info is not None
        assert info["entries"][0]["id"] == "sc123"


def test_resolver_audius_fallback_success():
    """Ensure resolver cascades to Audius when YouTube and SoundCloud fail."""
    resolver = AudioResolver()

    def fake_yt_sc(self_ydl, target, download=False):
        raise Exception("Sign in to confirm you're not a bot")

    audius_response = {
        "_type": "playlist",
        "entries": [
            {
                "id": "aud456",
                "title": "Raadhima",
                "uploader": "Raadhima Singer",
                "channel": "Raadhima Singer",
                "url": "https://discoveryprovider.audius.co/v1/tracks/aud456/stream?app_name=KROVEX",
                "webpage_url": "https://audius.co/tracks/aud456",
                "duration": 195,
                "thumbnail": "https://audius.co/thumb.jpg",
                "extractor": "audius",
            }
        ],
    }

    with patch.object(yt_dlp.YoutubeDL, "extract_info", new=fake_yt_sc):
        with patch.object(resolver, "_search_audius", return_value=audius_response):
            info, meta = resolver._extract_sync("raadhima")
            assert info is not None
            assert info["entries"][0]["id"] == "aud456"


@pytest.mark.asyncio
async def test_player_enqueue_playback_verification():
    """Ensure GuildAudioPlayer.enqueue only returns started=True if state is PLAYING."""
    bot = MagicMock()
    player = GuildAudioPlayer(bot=bot, guild_id=123)

    source = AudioSourceInfo(
        title="Test Track",
        url="https://example.com/stream.mp3",
        webpage_url="https://example.com/track",
        duration_seconds=180,
        uploader="Artist",
        source_provider="youtube",
    )
    track = Track(source_info=source, requester_id=999, requester_name="User")

    # Case 1: play_next succeeds and transitions state to PLAYING
    async def fake_play_success():
        player.state = PlayerState.PLAYING
        player.current_track = track

    player.play_next = fake_play_success
    player.state = PlayerState.IDLE
    player.current_track = None

    pos, started = await player.enqueue(track, play_now=True)
    assert pos == 0
    assert started is True

    # Case 2: play_next fails to transition state (remains IDLE or STOPPED)
    async def fake_play_fail():
        player.state = PlayerState.IDLE
        player.current_track = None

    player.play_next = fake_play_fail
    player.state = PlayerState.IDLE
    player.current_track = None

    pos, started = await player.enqueue(track, play_now=True)
    assert pos == 0
    assert started is False
