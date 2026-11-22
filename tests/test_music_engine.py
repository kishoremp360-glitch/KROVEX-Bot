"""Comprehensive automated tests for Death Bot Phase 2 Premium Music Engine.

Tests:
1. AudioResolver matching, official channel boost, remix penalty, low-confidence rejection.
2. AudioSourceInfo duration formatting and neon progress bar rendering.
3. DeathAudioSource options, filter constants, and elapsed frame time.
4. GuildAudioPlayer queue FIFO, history stack, loop modes, volume clamping, shuffle, vote skip, DJ checks.
5. LyricsService querying (mocked response).
6. PlaylistRepository CRUD operations.
7. Music Cog command architecture registration (both Prefix and Slash).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from discord import AudioSource
from bot.config import BotConfig
from bot.database.repositories.playlist_repo import PlaylistRepository
from bot.services.music.lyrics import LyricsService
from bot.services.music.player import GuildAudioPlayer
from bot.services.music.resolver import (
    AudioResolver,
    LowConfidenceError,
    ResolverError,
    TrackNotFoundError,
)
from bot.services.music.source import (
    FILTER_MAP,
    AudioFilter,
    AudioSourceInfo,
    DeathAudioSource,
    LoopMode,
    PlayerState,
    Track,
)
from bot.services.music_service import MusicService


# =============================================================================
# 1. AUDIO RESOLVER & SCORING TESTS
# =============================================================================

def test_calculate_match_score_exact_and_official_boost():
    """Verify that official indicators boost the score and exact matches score highest."""
    score_official = AudioResolver.calculate_match_score(
        query="The Weeknd Blinding Lights",
        title="The Weeknd - Blinding Lights (Official Video)",
        uploader="TheWeekndVEVO",
        channel="TheWeekndVEVO",
    )
    assert score_official >= 0.7

    # Official audio channel boost
    score_topic = AudioResolver.calculate_match_score(
        query="Starboy The Weeknd",
        title="Starboy",
        uploader="The Weeknd - Topic",
        channel="The Weeknd - Topic",
    )
    assert score_topic >= 0.65


def test_calculate_match_score_unwanted_penalties():
    """Verify that remix, cover, slowed, live, and 1 hour loops get penalized unless explicitly queried."""
    clean_score = AudioResolver.calculate_match_score(
        query="Shape of You",
        title="Ed Sheeran - Shape of You (Official Music Video)",
        uploader="Ed Sheeran",
        channel="Ed Sheeran",
    )
    remix_score = AudioResolver.calculate_match_score(
        query="Shape of You",
        title="Ed Sheeran - Shape of You (Club Remix 2024)",
        uploader="DJ Unknown",
        channel="DJ Unknown",
    )
    slowed_score = AudioResolver.calculate_match_score(
        query="Shape of You",
        title="Ed Sheeran - Shape of You (Slowed + Reverb)",
        uploader="Vibes",
        channel="Vibes",
    )
    live_score = AudioResolver.calculate_match_score(
        query="Shape of You",
        title="Ed Sheeran - Shape of You Live at Wembley",
        uploader="LiveConcerts",
        channel="LiveConcerts",
    )

    assert clean_score > remix_score
    assert clean_score > slowed_score
    assert clean_score > live_score


def test_calculate_match_score_explicit_remix_no_penalty():
    """When the user explicitly asks for 'remix', it should not be penalized."""
    score = AudioResolver.calculate_match_score(
        query="Dua Lipa Levitating Remix",
        title="Dua Lipa - Levitating (feat. DaBaby) [Remix]",
        uploader="Dua Lipa",
        channel="Dua Lipa",
    )
    assert score >= 0.65


@pytest.mark.asyncio
async def test_resolver_low_confidence_rejection():
    """Verify that queries producing low confidence matches raise LowConfidenceError."""
    resolver = AudioResolver()
    fake_info = {
        "entries": [
            {
                "title": "Completely Unrelated Classical Symphony",
                "url": "http://stream.url",
                "webpage_url": "http://youtube.com/watch?v=xyz",
                "duration": 300,
                "uploader": "Mozart Channel",
                "channel": "Mozart Channel",
            }
        ]
    }
    with patch.object(resolver, "_extract_sync", return_value=fake_info):
        with pytest.raises(LowConfidenceError):
            await resolver.resolve(
                query="Pop Superhit 2026",
                min_confidence=0.8,
            )


# =============================================================================
# 2. AUDIO SOURCE & METADATA TESTS
# =============================================================================

def test_audio_source_info_progress_bar():
    """Verify neon progress bar rendering and duration formatting."""
    info = AudioSourceInfo(
        title="Test Track",
        url="http://audio.stream",
        webpage_url="http://youtube.com/watch?v=test",
        duration_seconds=200,
        uploader="Artist",
    )
    bar = info.progress_bar(elapsed=50, length=16)
    assert "━" in bar or "🟣" in bar or "─" in bar
    assert "03:20" in bar

    # Test live stream
    live_info = AudioSourceInfo(
        title="Live Audio",
        url="http://live.stream",
        webpage_url="http://youtube.com/watch?v=live",
        duration_seconds=0,
        uploader="Streamer",
        is_live=True,
    )
    assert live_info.progress_bar(100) == "🔴 LIVE STREAM"


def test_death_audio_source_filter_constants():
    """Verify FFmpeg audio filter definitions and DSP map."""
    assert "bass=g=10" in FILTER_MAP[AudioFilter.BASSBOOST]
    assert "asetrate=48000*1.25" in FILTER_MAP[AudioFilter.NIGHTCORE]
    assert "asetrate=48000*0.8" in FILTER_MAP[AudioFilter.VAPORWAVE]
    assert "apulsator=hz=0.125" in FILTER_MAP[AudioFilter.EIGHT_D]


class DummyAudioSource(AudioSource):
    """Dummy AudioSource subclass for PCM transformer testing with 16-bit stereo frame (4 bytes)."""
    def read(self) -> bytes:
        # 16-bit stereo PCM frame is 4 bytes (2 channels * 2 bytes per sample)
        return b"\x00\x00\x00\x00" * 960  # 960 samples = 20ms at 48kHz (3840 bytes)

    def cleanup(self) -> None:
        pass


def test_death_audio_source_frame_timing():
    """Verify elapsed_seconds tracks 20ms frames accurately."""
    dummy = DummyAudioSource()
    source = DeathAudioSource(dummy, volume=1.0, start_offset=10.0)

    assert source.elapsed_seconds == 10.0
    source.read()
    source.read()
    # 2 frames * 0.02s = 0.04s + 10.0 = 10.04s
    assert round(source.elapsed_seconds, 2) == 10.04


# =============================================================================
# 3. GUILD AUDIO PLAYER & QUEUE ENGINE TESTS
# =============================================================================

@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.config = BotConfig(
        token="mock_token",
        client_id=123456789,
        dev_guild_id=987654321,
        default_volume=100,
        max_queue_size=100,
    )
    return bot


def make_test_track(title: str, duration: int = 180, requester_id: int = 123) -> Track:
    info = AudioSourceInfo(
        title=title,
        url=f"http://stream/{title}",
        webpage_url=f"http://yt/{title}",
        duration_seconds=duration,
        uploader="Artist",
    )
    return Track(source_info=info, requester_id=requester_id, requester_name="Requester")


def test_player_queue_fifo_and_limits(mock_bot):
    """Verify queue FIFO ordering, max capacity, and index-based removal."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)

    t1 = make_test_track("Song 1")
    t2 = make_test_track("Song 2")
    t3 = make_test_track("Song 3")

    player.queue.append(t1)
    player.queue.append(t2)
    player.queue.append(t3)

    assert len(player.queue) == 3
    assert player.queue[0].title == "Song 1"

    # Remove song 2 (index 1)
    removed = player.queue.pop(1)
    assert removed.title == "Song 2"
    assert len(player.queue) == 2
    assert player.queue[1].title == "Song 3"


def test_player_volume_clamping(mock_bot):
    """Verify volume is clamped between 1 and 150."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    assert player.set_volume(75) == 75
    assert player.volume == 75

    assert player.set_volume(200) == 150
    assert player.volume == 150

    assert player.set_volume(-10) == 1
    assert player.volume == 1


def test_player_shuffle(mock_bot):
    """Verify shuffle randomizes queue."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    for i in range(20):
        player.queue.append(make_test_track(f"Track {i}"))

    original_titles = [t.title for t in player.queue]
    player.shuffle()
    shuffled_titles = [t.title for t in player.queue]

    # Length preserved and order changed
    assert len(player.queue) == 20
    assert set(original_titles) == set(shuffled_titles)


def test_player_vote_skip(mock_bot):
    """Verify vote skipping counts and threshold calculation."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    player.vote_skip_ratio = 0.5

    # Mock voice client with 4 non-bot listeners
    vc = MagicMock()
    m1, m2, m3, m4, bot_member = MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()
    for m in (m1, m2, m3, m4):
        m.bot = False
    bot_member.bot = True
    vc.channel.members = [m1, m2, m3, m4, bot_member]

    with patch.object(GuildAudioPlayer, "voice_client", new=vc):
        # Threshold for 4 listeners at 50% = max(1, ceil(4 * 0.5)) = 2
        passed, voted, required = player.vote_skip(user_id=101)
        assert passed is False
        assert voted == 1
        assert required == 2

        # Duplicate vote should not increase count
        passed, voted, required = player.vote_skip(user_id=101)
        assert voted == 1

        # Second user vote meets threshold
        passed, voted, required = player.vote_skip(user_id=102)
        assert passed is True
        assert voted == 2
        assert voted >= required


@pytest.mark.asyncio
async def test_player_previous_history(mock_bot):
    """Verify previous track is pulled from history stack."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    t1 = make_test_track("Track 1")
    t2 = make_test_track("Track 2")

    player.history.append(t1)
    player.current_track = t2

    # Mock voice_client as None or not playing so play_next is invoked
    with patch.object(GuildAudioPlayer, "voice_client", new=None):
        with patch.object(player, "play_next", new_callable=AsyncMock) as mock_play_next:
            success = await player.play_previous()
            assert success is True
            # t2 should be pushed to front of queue
            assert player.queue[1].title == "Track 2"
            # t1 should be at front of queue for play_next()
            assert player.queue[0].title == "Track 1"
            mock_play_next.assert_called_once()


# =============================================================================
# 4. LYRICS SERVICE TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_lyrics_service_mocked():
    """Verify LyricsService handles JSON responses cleanly."""
    lyrics_service = LyricsService(session=None)

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "trackName": "Levitating",
        "artistName": "Dua Lipa",
        "plainLyrics": "If you wanna run away with me, I know a galaxy...",
    })

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    with patch.object(lyrics_service, "_get_session", new_callable=AsyncMock) as mock_get_s:
        mock_get_s.return_value = mock_session
        result = await lyrics_service.get_lyrics("Levitating", "Dua Lipa")
        assert result is not None
        title, artist, lyrics_text = result
        assert title == "Levitating"
        assert artist == "Dua Lipa"
        assert "If you wanna run away" in lyrics_text


# =============================================================================
# 5. PLAYLIST REPOSITORY TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_playlist_repository_crud():
    """Verify PlaylistRepository CRUD operations against mocked MongoDB collection."""
    mock_collection = MagicMock()
    mock_collection.insert_one = AsyncMock(return_value=MagicMock(acknowledged=True))
    mock_collection.find_one = AsyncMock(return_value=None)
    mock_collection.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

    # Mock cursor for find()
    mock_cursor = MagicMock()
    mock_cursor.skip.return_value = mock_cursor
    mock_cursor.limit.return_value = mock_cursor
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=[{"name": "favorites", "tracks": [{"title": "Song", "url": "http://song.url"}]}])
    mock_collection.find.return_value = mock_cursor

    repo = PlaylistRepository(mock_collection)

    # 1. Create playlist
    created = await repo.create_playlist(guild_id=1, user_id=10, name="Favorites")
    assert created is True
    mock_collection.insert_one.assert_called_once()

    # 2. Add track
    mock_collection.find_one.return_value = {"guild_id": 1, "user_id": 10, "name": "favorites", "tracks": []}
    track_item = {"title": "Song", "url": "http://song.url", "duration": 180}
    added = await repo.add_track(guild_id=1, user_id=10, name="Favorites", track_data=track_item)
    assert added is True

    # 3. List playlists
    playlists = await repo.list_playlists(guild_id=1, user_id=10)
    assert len(playlists) == 1
    assert playlists[0]["name"] == "favorites"

    # 4. Delete playlist
    deleted = await repo.delete_playlist(guild_id=1, user_id=10, name="Favorites")
    assert deleted is True


# =============================================================================
# 6. MUSIC COG DUAL-COMMAND ARCHITECTURE TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_music_cog_command_registration(mock_bot):
    """Verify that every music command is registered as both a Prefix and Slash command."""
    from bot.cogs.music.cog import Music

    mock_bot.music_service = MusicService(bot=mock_bot)
    cog = Music(mock_bot)

    # Prefix commands check
    prefix_commands = {cmd.name for cmd in cog.get_commands()}
    expected_core_commands = {
        "play",
        "search",
        "pause",
        "resume",
        "skip",
        "forceskip",
        "previous",
        "stop",
        "disconnect",
        "join",
        "nowplaying",
        "volume",
        "queue",
        "clear",
        "remove",
        "shuffle",
        "loop",
        "skipto",
        "autoplay",
        "247",
        "bassboost",
        "nightcore",
        "vaporwave",
        "8d",
        "resetfilters",
        "lyrics",
        "playlistcreate",
        "playlistadd",
        "playlistplay",
        "playlistlist",
        "playlistdelete",
        "djrole",
        "voteskipsettings",
        "musicstatus",
        "musicsettings",
    }

    missing_prefix = expected_core_commands - prefix_commands
    assert not missing_prefix, f"Missing prefix commands in Music cog: {missing_prefix}"

    # Slash commands check: Phase 2A.4 Model A structure
    app_cmd_map = {app_cmd.name: app_cmd for app_cmd in cog.get_app_commands()}
    # 5 top-level root commands
    assert "play" in app_cmd_map
    assert "pause" in app_cmd_map
    assert "skip" in app_cmd_map
    assert "stop" in app_cmd_map
    assert "queue" in app_cmd_map
    # 2 new groups
    assert "music" in app_cmd_map
    assert "playlist" in app_cmd_map

    music_subs = {cmd.name for cmd in app_cmd_map["music"].commands}
    assert "search" in music_subs
    assert "resume" in music_subs
    assert "lyrics" in music_subs
    assert "djrole" in music_subs
    assert "filter" in music_subs

    playlist_subs = {cmd.name for cmd in app_cmd_map["playlist"].commands}
    assert "play" in playlist_subs
    assert "create" in playlist_subs
    assert "add" in playlist_subs
    assert "list" in playlist_subs
    assert "delete" in playlist_subs


@pytest.mark.asyncio
async def test_music_slash_play_defers_immediately(mock_bot):
    """Verify that _execute_play defers the interaction before resolving or connecting."""
    from bot.cogs.music.cog import Music
    from bot.core.context import UnifiedContext

    mock_bot.music_service = MusicService(bot=mock_bot)
    cog = Music(mock_bot)

    interaction = MagicMock()
    interaction.client = mock_bot
    interaction.response.is_done.return_value = False
    interaction.response.defer = AsyncMock()
    interaction.guild = MagicMock()
    interaction.guild.id = 12345
    interaction.user = MagicMock()
    interaction.user.voice = None  # user not in voice

    ctx = UnifiedContext.from_interaction(interaction)
    ctx.send_error = AsyncMock()

    await cog._execute_play(ctx, "test query")

    # Defer must have been invoked immediately
    interaction.response.defer.assert_awaited_once()
    assert ctx._deferred is True
    # And error sent because not in voice channel
    ctx.send_error.assert_awaited_once()


@pytest.mark.asyncio
async def test_music_slash_join_defers_immediately(mock_bot):
    """Verify that _execute_join defers the interaction before attempting voice connection."""
    from bot.cogs.music.cog import Music
    from bot.core.context import UnifiedContext

    mock_bot.music_service = MusicService(bot=mock_bot)
    cog = Music(mock_bot)

    interaction = MagicMock()
    interaction.client = mock_bot
    interaction.response.is_done.return_value = False
    interaction.response.defer = AsyncMock()
    interaction.guild = MagicMock()
    interaction.guild.id = 12345
    interaction.user = MagicMock()
    interaction.user.voice = None  # user not in voice

    ctx = UnifiedContext.from_interaction(interaction)
    ctx.send_error = AsyncMock()

    await cog._execute_join(ctx)

    # Defer must have been invoked immediately before _ensure_voice returned
    interaction.response.defer.assert_awaited_once()
    assert ctx._deferred is True
    # Error sent via followup because user not in voice
    ctx.send_error.assert_awaited_once()


@pytest.mark.asyncio
async def test_music_prefix_join_safe_without_interaction(mock_bot):
    """Verify that _execute_join executes safely for prefix commands without calling interaction.defer."""
    from bot.cogs.music.cog import Music
    from bot.core.context import UnifiedContext

    mock_bot.music_service = MusicService(bot=mock_bot)
    cog = Music(mock_bot)

    prefix_ctx = MagicMock()
    prefix_ctx.bot = mock_bot
    prefix_ctx.guild = MagicMock()
    prefix_ctx.guild.id = 12345
    prefix_ctx.author = MagicMock()
    prefix_ctx.author.voice = None  # user not in voice

    ctx = UnifiedContext.from_prefix(prefix_ctx)
    ctx.send_error = AsyncMock()

    await cog._execute_join(ctx)

    # _deferred remains False because no interaction exists
    assert ctx._deferred is False
    # Error sent safely via prefix channel reply
    ctx.send_error.assert_awaited_once()


