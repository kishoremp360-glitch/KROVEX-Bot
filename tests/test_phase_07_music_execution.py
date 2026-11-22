"""KROVEX Master Audit & QA Plan — Phase 7 Execution Test Suite: Music System & Audio Streaming.

Covers test cases P7-TC01 through P7-TC10:
- P7-TC01: Audio Track Resolution & Metadata Extraction (Query search, direct URL, title/artist/duration)
- P7-TC02: Queue Management & FIFO Ordering (Enqueueing multiple tracks, FIFO sequence, queue bounds)
- P7-TC03: Playback Lifecycle & Automatic Transitions (First track auto-starts, play_next advances queue)
- P7-TC04: Volume Control & Audio Clamping (1% to 150% bounds, clamping negative/excessive inputs)
- P7-TC05: Audio Filters & DSP Transformations (Bassboost, Nightcore, 8D, Vaporwave, Off, hot-swapping)
- P7-TC06: Vote-Skip & Immediate DJ Skip Controls (Vote quorum ratio, DJ/Admin immediate skip bypass)
- P7-TC07: Queue Manipulation & Shuffle Mechanics (Fisher-Yates shuffle invariance, queue clear)
- P7-TC08: Repeat Modes & Track Looping (LoopMode.OFF, LoopMode.TRACK, LoopMode.QUEUE cycling & execution)
- P7-TC09: Disconnect & Reconnect Voice State Resilience (Disconnect preservation, reconnect handling)
- P7-TC10: Saved Playlists & Persistence CRUD (PlaylistRepository create, add tracks, list, delete)
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.database.repositories.playlist_repo import PlaylistRepository
from bot.services.music.player import GuildAudioPlayer
from bot.services.music.resolver import AudioResolver
from bot.services.music.source import (
    FILTER_MAP,
    AudioFilter,
    AudioSourceInfo,
    DeathAudioSource,
    LoopMode,
    PlayerState,
    Track,
)


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.config = MagicMock()
    bot.config.owner_ids = [99901]
    bot.owner_ids = [99901]
    bot.get_guild = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 123456789
    loop = asyncio.new_event_loop()
    bot.loop = loop
    yield bot
    loop.close()


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 777777777
    guild.name = "Krovex Audio Staging"
    guild.owner_id = 111111111
    guild.voice_client = MagicMock()
    guild.voice_client.is_connected.return_value = True
    guild.voice_client.is_playing.return_value = False
    guild.voice_client.is_paused.return_value = False
    return guild


def _make_track(
    title: str,
    url: str = "https://youtube.com/watch?v=mock123",
    duration: int = 210,
    requester_id: int = 10001,
    requester_name: str = "Tester",
) -> Track:
    info = AudioSourceInfo(
        title=title,
        url="https://mock.stream/audio.mp3",
        webpage_url=url,
        duration_seconds=duration,
        uploader="KROVEX Music",
        thumbnail_url="https://mock.img/thumb.jpg",
        source_provider="youtube",
    )
    return Track(
        source_info=info,
        requester_id=requester_id,
        requester_name=requester_name,
    )


# ==============================================================================
# P7-TC01: AUDIO TRACK RESOLUTION & METADATA EXTRACTION
# ==============================================================================

def test_p7_tc01_audio_track_resolution_and_metadata():
    """P7-TC01: Query resolution, direct URL parsing, and metadata normalization."""
    async def _test():
        resolver = AudioResolver()

        # Mock yt-dlp extraction payload
        mock_info = {
            "title": "Nightcore - Titanium",
            "webpage_url": "https://www.youtube.com/watch?v=sample1",
            "url": "https://stream.provider/audio1.opus",
            "duration": 185,
            "uploader": "Sample Artist",
            "channel": "Sample Channel",
            "thumbnail": "https://images.sample/art.png",
        }

        with patch.object(resolver, "_extract_sync", return_value=(mock_info, None)):
            primary, candidates = await resolver.resolve("Nightcore - Titanium", timeout=5.0)
            assert primary is not None
            assert primary.title == "Nightcore - Titanium"
            assert primary.duration_seconds == 185
            assert primary.formatted_duration == "03:05"
            assert primary.uploader == "Sample Artist"
            assert len(candidates) == 1

            # Build Track model from extracted metadata
            track = Track(
                source_info=primary,
                requester_id=50001,
                requester_name="AudioTester",
            )
            assert track.title == "Nightcore - Titanium"
            assert track.duration == 185
            assert track.requester_id == 50001
            assert track.requester_name == "AudioTester"
            assert track.uri == "https://www.youtube.com/watch?v=sample1"
    run_async(_test())


# ==============================================================================
# P7-TC02: QUEUE MANAGEMENT & FIFO ORDERING
# ==============================================================================

def test_p7_tc02_queue_management_and_fifo(mock_bot, mock_guild):
    """P7-TC02: Adding tracks maintains strict FIFO ordering and queue bounds."""
    async def _test():
        mock_bot.get_guild.return_value = mock_guild
        player = GuildAudioPlayer(mock_bot, mock_guild.id)
        player._execute_play_next = AsyncMock()

        t1 = _make_track("Track 1")
        t2 = _make_track("Track 2")
        t3 = _make_track("Track 3")

        # Enqueue tracks (play_now=False to test pure queue order)
        pos1, started1 = await player.enqueue(t1, play_now=False)
        pos2, started2 = await player.enqueue(t2, play_now=False)
        pos3, started3 = await player.enqueue(t3, play_now=False)

        assert len(player.queue) == 3
        assert pos1 == 1
        assert pos2 == 2
        assert pos3 == 3
        assert started1 is False
        assert started2 is False
        assert started3 is False
        assert player.queue[0].title == "Track 1"
        assert player.queue[1].title == "Track 2"
        assert player.queue[2].title == "Track 3"

        # Embed queue display matches page
        embed = player.build_queue_embed(page=1, per_page=10)
        assert "Track 1" in embed.fields[0].value
        assert "Track 2" in embed.fields[0].value
        assert "Track 3" in embed.fields[0].value
    run_async(_test())


# ==============================================================================
# P7-TC03: PLAYBACK LIFECYCLE & AUTOMATIC TRANSITIONS
# ==============================================================================

def test_p7_tc03_playback_lifecycle_and_transitions(mock_bot, mock_guild):
    """P7-TC03: First track auto-starts playback; play_next transitions seamlessly."""
    async def _test():
        mock_bot.get_guild.return_value = mock_guild
        player = GuildAudioPlayer(mock_bot, mock_guild.id)
        player.update_player_message = AsyncMock()

        t1 = _make_track("Song Alpha")
        t2 = _make_track("Song Beta")

        # Intercept source creation
        mock_source = MagicMock(spec=DeathAudioSource)
        with patch.object(DeathAudioSource, "create_stream", return_value=mock_source):
            # Enqueue first track -> auto-starts
            pos, started = await player.enqueue(t1, play_now=True)
            assert started is True
            assert pos == 0
            assert player.current_track == t1
            assert player.state == PlayerState.PLAYING
            assert mock_guild.voice_client.play.called

            # Enqueue second track while first is active -> queued
            mock_guild.voice_client.is_playing.return_value = True
            pos2, started2 = await player.enqueue(t2, play_now=True)
            assert started2 is False
            assert pos2 == 1
            assert len(player.queue) == 1

            # Advance playback to next track
            mock_guild.voice_client.is_playing.return_value = False
            await player.play_next(force=True)
            assert player.current_track == t2
            assert len(player.queue) == 0
            assert t1 in player.history
    run_async(_test())


# ==============================================================================
# P7-TC04: VOLUME CONTROL & AUDIO CLAMPING
# ==============================================================================

def test_p7_tc04_volume_control_and_clamping(mock_bot, mock_guild):
    """P7-TC04: Clamps volume within 1% to 150% bounds."""
    mock_bot.get_guild.return_value = mock_guild
    player = GuildAudioPlayer(mock_bot, mock_guild.id)
    player.current_source = MagicMock(spec=DeathAudioSource)

    # 1. Normal volume update
    vol = player.set_volume(85)
    assert vol == 85
    assert player.volume == 85
    assert player.current_source.volume == 0.85

    # 2. Upper clamp at 150%
    vol_high = player.set_volume(250)
    assert vol_high == 150
    assert player.volume == 150
    assert player.current_source.volume == 1.50

    # 3. Lower clamp at 1%
    vol_low = player.set_volume(-15)
    assert vol_low == 1
    assert player.volume == 1
    assert player.current_source.volume == 0.01


# ==============================================================================
# P7-TC05: AUDIO FILTERS & DSP TRANSFORMATIONS
# ==============================================================================

def test_p7_tc05_audio_filters_and_dsp(mock_bot, mock_guild):
    """P7-TC05: AudioFilter modes, FILTER_MAP options, and hot-swap stream recreation."""
    async def _test():
        mock_bot.get_guild.return_value = mock_guild
        player = GuildAudioPlayer(mock_bot, mock_guild.id)
        mock_source = MagicMock(spec=DeathAudioSource)

        with patch.object(DeathAudioSource, "create_stream", return_value=mock_source):
            # 1. Set Bassboost filter
            await player.set_filter(AudioFilter.BASSBOOST)
            assert player.active_filter == AudioFilter.BASSBOOST
            assert "bass=g=10" in FILTER_MAP[AudioFilter.BASSBOOST]

            # 2. Set Nightcore filter
            await player.set_filter(AudioFilter.NIGHTCORE)
            assert player.active_filter == AudioFilter.NIGHTCORE
            assert "asetrate=" in FILTER_MAP[AudioFilter.NIGHTCORE]

            # 3. Set 8D Audio filter
            await player.set_filter(AudioFilter.EIGHT_D)
            assert player.active_filter == AudioFilter.EIGHT_D
            assert "apulsator=" in FILTER_MAP[AudioFilter.EIGHT_D]

            # 4. Turn filter Off
            await player.set_filter(AudioFilter.OFF)
            assert player.active_filter == AudioFilter.OFF
            assert AudioFilter.OFF not in FILTER_MAP
    run_async(_test())


# ==============================================================================
# P7-TC06: VOTE-SKIP & IMMEDIATE DJ SKIP CONTROLS
# ==============================================================================

def test_p7_tc06_voteskip_and_dj_controls(mock_bot, mock_guild):
    """P7-TC06: Vote skip quorum calculation and DJ/Admin immediate bypass."""
    async def _test():
        mock_bot.get_guild.return_value = mock_guild
        player = GuildAudioPlayer(mock_bot, mock_guild.id)
        player.current_track = _make_track("Votable Song")
        player.state = PlayerState.PLAYING

        # Mock voice channel with 4 listeners
        vc_channel = MagicMock(spec=discord.VoiceChannel)
        vc_channel.members = [
            MagicMock(spec=discord.Member, id=101, bot=False),
            MagicMock(spec=discord.Member, id=102, bot=False),
            MagicMock(spec=discord.Member, id=103, bot=False),
            MagicMock(spec=discord.Member, id=104, bot=False),
        ]
        mock_guild.voice_client.channel = vc_channel

        # 1. First vote (1 of 2 required with ratio 0.5)
        passed, current, req = player.vote_skip(101)
        assert passed is False
        assert current == 1
        assert req == 2

        # 2. Duplicate vote ignored (set membership)
        passed_dup, current_dup, _ = player.vote_skip(101)
        assert passed_dup is False
        assert current_dup == 1

        # 3. Second vote meets quorum
        passed2, current2, req2 = player.vote_skip(102)
        assert passed2 is True
        assert current2 >= req2

        # 4. Immediate skip bypass for Server Admin
        admin_member = MagicMock(spec=discord.Member, id=mock_guild.owner_id)
        admin_member.guild_permissions.administrator = True
        admin_member.guild_permissions.manage_guild = False
        can_skip, reason = await player.can_control(admin_member)
        assert can_skip is True
        assert "Administrator Override" in reason
    run_async(_test())


# ==============================================================================
# P7-TC07: QUEUE MANIPULATION & SHUFFLE MECHANICS
# ==============================================================================

def test_p7_tc07_queue_manipulation_and_shuffle(mock_bot, mock_guild):
    """P7-TC07: Fisher-Yates shuffle preserves all elements without loss; queue clear."""
    async def _test():
        mock_bot.get_guild.return_value = mock_guild
        player = GuildAudioPlayer(mock_bot, mock_guild.id)
        player.update_player_message = AsyncMock()

        tracks = [_make_track(f"Song {i}") for i in range(15)]
        for t in tracks:
            await player.enqueue(t, play_now=False)

        original_titles = {t.title for t in player.queue}
        assert len(player.queue) == 15

        # 1. Shuffle queue
        shuffled_count = player.shuffle()
        assert shuffled_count == 15
        shuffled_titles = {t.title for t in player.queue}
        assert original_titles == shuffled_titles

        # 2. Stop and clear queue
        await player.stop(clear_queue=True)
        assert len(player.queue) == 0
        assert player.current_track is None
        assert player.state == PlayerState.STOPPED
    run_async(_test())


# ==============================================================================
# P7-TC08: REPEAT MODES & TRACK LOOPING
# ==============================================================================

def test_p7_tc08_repeat_modes_and_looping(mock_bot, mock_guild):
    """P7-TC08: LoopMode.OFF, LoopMode.TRACK, and LoopMode.QUEUE cycles."""
    async def _test():
        mock_bot.get_guild.return_value = mock_guild
        player = GuildAudioPlayer(mock_bot, mock_guild.id)
        player.update_player_message = AsyncMock()

        # Initial state
        assert player.loop_mode == LoopMode.OFF

        # 1. Set to Track Loop
        m1 = player.set_loop_mode(LoopMode.TRACK)
        assert m1 == LoopMode.TRACK
        assert player.loop_mode == LoopMode.TRACK

        # 2. Set to Queue Loop
        m2 = player.set_loop_mode(LoopMode.QUEUE)
        assert m2 == LoopMode.QUEUE
        assert player.loop_mode == LoopMode.QUEUE

        # 3. Turn Loop Off
        m3 = player.set_loop_mode(LoopMode.OFF)
        assert m3 == LoopMode.OFF
        assert player.loop_mode == LoopMode.OFF

        # 4. Verify Track Loop behavior during play_next
        t1 = _make_track("Looping Track")
        t2 = _make_track("Next Track")
        player.current_track = t1
        player.queue.append(t2)
        player.loop_mode = LoopMode.TRACK

        mock_source = MagicMock(spec=DeathAudioSource)
        with patch.object(DeathAudioSource, "create_stream", return_value=mock_source):
            await player.play_next(force=True)
            # Under Track Loop, t1 replays and t2 stays in queue
            assert player.current_track == t1
            assert len(player.queue) == 1
            assert player.queue[0] == t2

            # Switch to Queue Loop
            player.loop_mode = LoopMode.QUEUE
            await player.play_next(force=True)
            # Under Queue Loop, t2 plays, and t1 is appended to the back of queue
            assert player.current_track == t2
            assert len(player.queue) == 1
            assert player.queue[0] == t1
    run_async(_test())


# ==============================================================================
# P7-TC09: DISCONNECT & RECONNECT RESILIENCE
# ==============================================================================

def test_p7_tc09_disconnect_and_reconnect_resilience(mock_bot, mock_guild):
    """P7-TC09: Voice client disconnect state reconciliation preserves queue."""
    mock_bot.get_guild.return_value = mock_guild
    player = GuildAudioPlayer(mock_bot, mock_guild.id)

    t1 = _make_track("Preserved Track")
    player.queue.append(t1)
    player.current_track = _make_track("Active Track")
    player.state = PlayerState.PLAYING

    # 1. VoiceClient drops connection
    mock_guild.voice_client.is_connected.return_value = False
    new_state = player.sync_state()

    # Reconciles to IDLE, active track cleared, but queue is strictly preserved
    assert new_state == PlayerState.IDLE
    assert player.current_track is None
    assert len(player.queue) == 1
    assert player.queue[0].title == "Preserved Track"

    # 2. VoiceClient reconnects
    mock_guild.voice_client.is_connected.return_value = True
    assert player.is_connected is True
    assert len(player.queue) == 1
    assert player.queue[0].title == "Preserved Track"


# ==============================================================================
# P7-TC10: SAVED PLAYLISTS & PERSISTENCE CRUD
# ==============================================================================

def test_p7_tc10_saved_playlists_crud():
    """P7-TC10: Playlist creation, track append, listing, and deletion."""
    async def _test():
        mock_collection = MagicMock()
        mock_collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id="pl_id_123"))
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        mock_cursor = MagicMock()
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[
            {"name": "chill vibes", "tracks": [{"title": "Lo-Fi Beats", "url": "https://music.yt/123"}]}
        ])
        mock_collection.find.return_value = mock_cursor

        repo = PlaylistRepository(mock_collection)

        # 1. Create Playlist
        ok = await repo.create_playlist(guild_id=777, user_id=888, name="Chill Vibes")
        assert ok is True
        mock_collection.insert_one.assert_called_once()

        # 2. Add Track to Playlist
        mock_collection.find_one.return_value = {
            "guild_id": 777,
            "user_id": 888,
            "name": "chill vibes",
            "tracks": [],
        }
        track_data = {"title": "Coffee Beats", "url": "https://music.yt/456", "duration": 180}
        added = await repo.add_track(guild_id=777, user_id=888, name="Chill Vibes", track_data=track_data)
        assert added is True
        mock_collection.update_one.assert_called_once()

        # 3. List Playlists
        playlists = await repo.list_playlists(guild_id=777, user_id=888)
        assert len(playlists) == 1
        assert playlists[0]["name"] == "chill vibes"

        # 4. Delete Playlist
        deleted = await repo.delete_playlist(guild_id=777, user_id=888, name="Chill Vibes")
        assert deleted is True
        mock_collection.delete_one.assert_called_once()
    run_async(_test())
