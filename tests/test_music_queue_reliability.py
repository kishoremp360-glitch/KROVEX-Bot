"""Regression and reliability tests for KROVEX Music Queue & Playback State.

Phase M1 verification suite covering:
1. First track automatically starting.
2. Disconnected voice client handling.
3. Voice client reconnecting handling.
4. Failed audio source creation handling.
5. Queue position preservation after failed playback.
6. Second track starting automatically after first track finishes.
7. /nowplaying behavior when player is idle.
8. /nowplaying behavior during active playback.
9. Concurrency protection against simultaneous play_next calls.
10. Prefix and Slash player instance consistency.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.config import BotConfig
from bot.services.music.player import GuildAudioPlayer
from bot.services.music.source import (
    AudioFilter,
    AudioSourceInfo,
    DeathAudioSource,
    LoopMode,
    PlayerState,
    Track,
)
from bot.services.music_service import MusicService


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
    try:
        bot.loop = asyncio.get_running_loop()
    except RuntimeError:
        bot.loop = MagicMock()
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


def make_connected_vc():
    vc = MagicMock(spec=discord.VoiceClient)
    vc.is_connected.return_value = True
    vc.is_playing.return_value = False
    vc.is_paused.return_value = False
    vc.channel = MagicMock(id=555)
    return vc


# =============================================================================
# 1. First track automatically starting
# =============================================================================

@pytest.mark.asyncio
async def test_first_track_automatically_starts(mock_bot):
    """When idle and connected, the first enqueued track immediately begins playback."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    vc = make_connected_vc()
    t1 = make_test_track("Song 1")

    with patch.object(GuildAudioPlayer, "voice_client", new=vc):
        with patch("bot.services.music.source.DeathAudioSource.create_stream") as mock_create_stream:
            mock_stream = MagicMock()
            mock_create_stream.return_value = mock_stream

            pos, started = await player.enqueue(t1)

            assert started is True
            assert pos == 0
            assert player.current_track == t1
            assert player.state == PlayerState.PLAYING
            assert len(player.queue) == 0
            vc.play.assert_called_once()


# =============================================================================
# 2. Disconnected voice client
# =============================================================================

@pytest.mark.asyncio
async def test_disconnected_voice_client_preserves_track_in_queue(mock_bot):
    """When voice client is disconnected, track remains safely in queue and state stays IDLE."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    vc = make_connected_vc()
    vc.is_connected.return_value = False  # Disconnected
    t1 = make_test_track("Song Disconnected")

    with patch.object(GuildAudioPlayer, "voice_client", new=vc):
        pos, started = await player.enqueue(t1)

        assert started is False
        assert pos == 1
        assert len(player.queue) == 1
        assert player.queue[0] == t1
        assert player.current_track is None
        assert player.state == PlayerState.IDLE
        vc.play.assert_not_called()


# =============================================================================
# 3. Voice client reconnecting
# =============================================================================

@pytest.mark.asyncio
async def test_voice_client_reconnecting_waits_and_starts(mock_bot):
    """If voice client is currently reconnecting, play_next waits for connection before playing."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    vc = make_connected_vc()
    vc._connecting = True

    # First call to is_connected returns False, second returns True (simulating reconnect finish)
    vc.is_connected.side_effect = [False, True, True, True]
    t1 = make_test_track("Song Reconnect")

    with patch.object(GuildAudioPlayer, "voice_client", new=vc):
        with patch("bot.services.music.source.DeathAudioSource.create_stream") as mock_create_stream:
            mock_stream = MagicMock()
            mock_create_stream.return_value = mock_stream

            pos, started = await player.enqueue(t1)

            assert started is True
            assert player.current_track == t1
            assert player.state == PlayerState.PLAYING
            vc.play.assert_called_once()


@pytest.mark.asyncio
async def test_voice_client_reconnecting_timeout_handles_gracefully(mock_bot):
    """If voice client remains disconnected after wait, track stays queued and state resets to IDLE."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    vc = make_connected_vc()
    vc._connecting = True
    vc.is_connected.return_value = False  # Never succeeds reconnecting
    t1 = make_test_track("Song Reconnect Timeout")

    with patch.object(GuildAudioPlayer, "voice_client", new=vc):
        pos, started = await player.enqueue(t1)

        assert started is False
        assert pos == 1
        assert len(player.queue) == 1
        assert player.current_track is None
        assert player.state == PlayerState.IDLE
        vc.play.assert_not_called()


# =============================================================================
# 4. Failed audio source creation
# =============================================================================

@pytest.mark.asyncio
async def test_failed_audio_source_creation_logs_and_records_history(mock_bot):
    """When FFmpeg stream construction fails, track is saved in history and not silently vanished."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    vc = make_connected_vc()
    t1 = make_test_track("Corrupt Song")

    with patch.object(GuildAudioPlayer, "voice_client", new=vc):
        with patch("bot.services.music.source.DeathAudioSource.create_stream", side_effect=RuntimeError("FFmpeg not found")):
            pos, started = await player.enqueue(t1)

            # Give scheduled task a moment to execute
            await asyncio.sleep(0.05)

            assert started is False
            # Failed track is preserved in history
            assert t1 in player.history
            assert player.current_track is None
            assert player.state == PlayerState.IDLE


# =============================================================================
# 5. Queue position after failed playback
# =============================================================================

@pytest.mark.asyncio
async def test_queue_position_after_failed_playback(mock_bot):
    """When first track stream fails and second track is queued, second track advances smoothly."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    vc = make_connected_vc()
    t1 = make_test_track("Failing Song")
    t2 = make_test_track("Working Song")

    with patch.object(GuildAudioPlayer, "voice_client", new=vc):
        with patch("bot.services.music.source.DeathAudioSource.create_stream") as mock_stream_factory:
            # First track fails, second track succeeds
            good_stream = MagicMock()
            mock_stream_factory.side_effect = [RuntimeError("Extraction failed"), good_stream]

            # Enqueue t1 (which will fail)
            player.queue.append(t2)
            await player.enqueue(t1)

            await asyncio.sleep(0.05)

            # t1 recorded in history
            assert t1 in player.history
            # t2 picked up and playing
            assert player.current_track == t2
            assert player.state == PlayerState.PLAYING


# =============================================================================
# 6. Second track starting after first track finishes
# =============================================================================

@pytest.mark.asyncio
async def test_second_track_starts_after_first_finishes(mock_bot):
    """Simulating voice_client _after callback automatically advances to track #2."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    vc = make_connected_vc()
    t1 = make_test_track("Song 1")
    t2 = make_test_track("Song 2")

    captured_after = None

    def fake_play(source, after=None):
        nonlocal captured_after
        captured_after = after
        vc.is_playing.return_value = True

    vc.play.side_effect = fake_play

    with patch.object(GuildAudioPlayer, "voice_client", new=vc):
        with patch("bot.services.music.source.DeathAudioSource.create_stream", return_value=MagicMock()):
            # Enqueue t1 -> starts playing
            pos1, started1 = await player.enqueue(t1)
            assert started1 is True
            assert player.current_track == t1
            assert player.state == PlayerState.PLAYING

            # Enqueue t2 -> goes to queue position 1
            pos2, started2 = await player.enqueue(t2)
            assert started2 is False
            assert pos2 == 1
            assert len(player.queue) == 1

            # Simulate t1 ending via _after callback
            assert captured_after is not None
            vc.is_playing.return_value = False
            # Call play_next with force to simulate after callback advancing
            await player.play_next(force=True)

            # Now t2 should be current_track and t1 in history
            assert player.current_track == t2
            assert player.state == PlayerState.PLAYING
            assert t1 in player.history
            assert len(player.queue) == 0


# =============================================================================
# 7. /nowplaying when idle
# =============================================================================

def test_nowplaying_when_idle(mock_bot):
    """When idle, build_player_embed returns standby embed without raising."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    player.current_track = None
    player.sync_state()

    embed = player.build_player_embed()
    assert "Standby" in embed.footer.text or "Idle" in embed.title
    assert player.state == PlayerState.IDLE


# =============================================================================
# 8. /nowplaying during active playback
# =============================================================================

def test_nowplaying_during_active_playback(mock_bot):
    """When playing, build_player_embed returns rich details and metadata."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    t = make_test_track("Active Song", duration=240)
    player.current_track = t
    player.state = PlayerState.PLAYING

    vc = make_connected_vc()
    vc.is_playing.return_value = True

    with patch.object(GuildAudioPlayer, "voice_client", new=vc):
        embed = player.build_player_embed()
        assert "Active Song" in embed.title
        assert "Artist" in [f.value for f in embed.fields if f.name == "Uploader"][0]
        assert any(f.name == "Progress" for f in embed.fields)


# =============================================================================
# 9. Concurrent play_next calls
# =============================================================================

@pytest.mark.asyncio
async def test_concurrent_play_next_calls_prevent_duplicate_playback(mock_bot):
    """Multiple concurrent calls to play_next do not pop duplicate tracks or launch parallel streams."""
    player = GuildAudioPlayer(bot=mock_bot, guild_id=1)
    vc = make_connected_vc()

    def fake_play(source, after=None):
        vc.is_playing.return_value = True

    vc.play.side_effect = fake_play

    t1 = make_test_track("Track Alpha")
    t2 = make_test_track("Track Beta")

    player.queue.extend([t1, t2])

    with patch.object(GuildAudioPlayer, "voice_client", new=vc):
        with patch("bot.services.music.source.DeathAudioSource.create_stream", return_value=MagicMock()):
            # Concurrently launch 5 play_next calls
            await asyncio.gather(
                player.play_next(),
                player.play_next(),
                player.play_next(),
                player.play_next(),
                player.play_next(),
            )

            # Exactly one track should be current_track and one in queue
            assert player.current_track == t1
            assert len(player.queue) == 1
            assert player.queue[0] == t2
            assert vc.play.call_count == 1


# =============================================================================
# 10. Prefix and Slash player consistency
# =============================================================================

def test_prefix_and_slash_player_consistency(mock_bot):
    """MusicService returns the exact same GuildAudioPlayer instance across command contexts."""
    service = MusicService(bot=mock_bot)
    guild_id = 998877

    # Simulate prefix command getting player
    player_prefix = service.get_player(guild_id)
    # Simulate slash command getting player
    player_slash = service.get_player(guild_id)

    assert player_prefix is player_slash
    assert id(player_prefix) == id(player_slash)

    # Enqueuing on one updates the other
    t = make_test_track("Shared Track")
    player_prefix.queue.append(t)
    assert len(player_slash.queue) == 1
    assert player_slash.queue[0].title == "Shared Track"
