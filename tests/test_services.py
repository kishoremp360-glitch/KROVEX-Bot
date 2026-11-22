"""Unit tests for domain services (Music, Voice, and Welcome)."""

from unittest.mock import MagicMock
import pytest

from bot.services.music_service import (
    AudioSourceInfo,
    LoopMode,
    MusicService,
    PlayerState,
    Track,
)
from bot.services.welcome_service import WelcomeService
from bot.services.voice_service import VoiceService


def test_audio_source_info_duration_formatting():
    """Verify formatted_duration handles live streams, seconds, and hours."""
    # Under an hour
    s1 = AudioSourceInfo(
        title="Song 1",
        url="https://audio.url",
        webpage_url="https://youtube.com/watch?v=1",
        duration_seconds=215,
        uploader="Artist",
    )
    assert s1.formatted_duration == "03:35"

    # Over an hour
    s2 = AudioSourceInfo(
        title="Mix",
        url="https://audio.url",
        webpage_url="https://youtube.com/watch?v=2",
        duration_seconds=3665,
        uploader="DJ",
    )
    assert s2.formatted_duration == "01:01:05"

    # Live
    s3 = AudioSourceInfo(
        title="Live Stream",
        url="https://audio.url",
        webpage_url="https://youtube.com/watch?v=3",
        duration_seconds=0,
        uploader="Streamer",
        is_live=True,
    )
    assert s3.formatted_duration == "LIVE"


def test_music_service_queue_operations():
    """Verify MusicService queue mutations."""
    service = MusicService()
    guild_id = 9999

    info = AudioSourceInfo("Test Song", "http://url", "http://web", 180, "Artist")
    track = Track(source_info=info, requester_id=123, requester_name="Requester")

    # Add to queue
    assert service.add_to_queue(guild_id, track, max_size=2) is True
    assert len(service.get_queue(guild_id)) == 1

    # Second track
    assert service.add_to_queue(guild_id, track, max_size=2) is True
    assert len(service.get_queue(guild_id)) == 2

    # Exceed max size
    assert service.add_to_queue(guild_id, track, max_size=2) is False

    # Remove track (1-based index)
    removed = service.remove_from_queue(guild_id, 1)
    assert removed is not None
    assert len(service.get_queue(guild_id)) == 1

    # Clear queue
    cleared = service.clear_queue(guild_id)
    assert cleared == 1
    assert len(service.get_queue(guild_id)) == 0


def test_music_service_volume_and_loop():
    """Verify volume clamping and loop state management."""
    service = MusicService()
    guild_id = 8888

    # Volume clamping
    assert service.set_volume(guild_id, 150) == 100
    assert service.set_volume(guild_id, -20) == 1
    assert service.set_volume(guild_id, 65) == 65

    # Loop modes
    assert service.get_loop_mode(guild_id) == LoopMode.OFF
    service.set_loop_mode(guild_id, LoopMode.TRACK)
    assert service.get_loop_mode(guild_id) == LoopMode.TRACK

    # Player states
    assert service.get_state(guild_id) == PlayerState.IDLE
    service.set_state(guild_id, PlayerState.PLAYING)
    assert service.get_state(guild_id) == PlayerState.PLAYING


def test_welcome_service_template_formatting():
    """Verify WelcomeService template string replacement."""
    mock_bot = MagicMock()
    mock_repo = MagicMock()
    service = WelcomeService(mock_bot, mock_repo)

    mock_member = MagicMock()
    mock_member.mention = "<@12345>"
    mock_member.name = "JohnDoe"
    mock_member.display_name = "John"
    mock_member.guild.name = "Cyber Realm"
    mock_member.guild.member_count = 142

    template = "Welcome {user} ({user_name}) to {server}! Member #{member_count}."
    formatted = service.format_template(template, mock_member)

    assert formatted == "Welcome <@12345> (JohnDoe) to Cyber Realm! Member #142."


def test_music_service_track_and_cleanup():
    """Verify MusicService active track tracking and guild cleanup."""
    service = MusicService()
    guild_id = 7777

    info = AudioSourceInfo("Track A", "http://url", "http://web", 200, "Artist")
    track = Track(source_info=info, requester_id=1, requester_name="Req")

    service.add_to_queue(guild_id, track)
    service.set_current_track(guild_id, track)
    service.set_state(guild_id, PlayerState.PLAYING)

    assert service.get_current_track(guild_id) == track
    assert service.get_state(guild_id) == PlayerState.PLAYING

    # Cleanup guild
    service.cleanup_guild(guild_id)
    assert service.get_current_track(guild_id) is None
    assert len(service.get_queue(guild_id)) == 0
    assert service.get_state(guild_id) == PlayerState.IDLE


def test_music_service_diagnostics():
    """Verify MusicService diagnostic availability checks."""
    # yt-dlp is installed in environment
    assert MusicService.is_ytdlp_available() is True
    # PyNaCl availability returns a bool
    assert isinstance(MusicService.is_voice_supported(), bool)
    # FFmpeg check returns a bool
    assert isinstance(MusicService.is_ffmpeg_available(), bool)


@pytest.mark.asyncio
async def test_voice_service_afk_channel_filtering():
    """Verify VoiceService ignores or closes sessions when in AFK channel."""
    from unittest.mock import AsyncMock

    mock_bot = MagicMock()
    mock_repo = MagicMock()
    mock_repo.start_session = AsyncMock()
    mock_repo.end_session = AsyncMock()

    service = VoiceService(mock_bot, mock_repo)

    mock_guild = MagicMock()
    mock_afk_channel = MagicMock()
    mock_afk_channel.id = 999
    mock_guild.afk_channel = mock_afk_channel

    mock_regular_channel = MagicMock()
    mock_regular_channel.id = 111

    mock_member = MagicMock()
    mock_member.bot = False
    mock_member.guild = mock_guild

    # 1. Join regular channel
    before_state = MagicMock()
    before_state.channel = None
    after_state = MagicMock()
    after_state.channel = mock_regular_channel

    await service.handle_voice_state_update(mock_member, before_state, after_state)
    mock_repo.start_session.assert_awaited_once()

    # 2. Move to AFK channel (should end session)
    before_state.channel = mock_regular_channel
    after_state.channel = mock_afk_channel
    await service.handle_voice_state_update(mock_member, before_state, after_state)
    mock_repo.end_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_welcome_service_role_hierarchy_protection():
    """Verify WelcomeService does not attempt to assign roles higher than bot's top role."""
    from unittest.mock import AsyncMock
    from bot.database.models import WelcomeSettings

    mock_bot = MagicMock()
    mock_repo = MagicMock()
    settings = WelcomeSettings(guild_id=1, enabled=True, auto_role_ids=[100, 200])
    mock_repo.get_or_create = AsyncMock(return_value=settings)

    service = WelcomeService(mock_bot, mock_repo)

    mock_guild = MagicMock()
    mock_me = MagicMock()
    mock_me.guild_permissions.manage_roles = True

    # Bot's top role has position 50
    mock_top_role = MagicMock()
    mock_top_role.__gt__ = lambda self, other: other.position < 50
    mock_top_role.__lt__ = lambda self, other: other.position > 50
    mock_me.top_role = mock_top_role

    # Role 1: position 10 (valid, lower than bot)
    role_valid = MagicMock()
    role_valid.position = 10
    role_valid.__lt__ = lambda self, other: self.position < 50

    # Role 2: position 90 (invalid, higher than bot)
    role_invalid = MagicMock()
    role_invalid.position = 90
    role_invalid.__lt__ = lambda self, other: self.position < 50

    mock_guild.me = mock_me
    mock_guild.get_role.side_effect = lambda rid: role_valid if rid == 100 else role_invalid

    mock_member = MagicMock()
    mock_member.guild = mock_guild
    mock_member.add_roles = AsyncMock()

    await service.handle_member_join(mock_member)

    # Should only add role_valid
    mock_member.add_roles.assert_awaited_once_with(role_valid, reason="Death Bot Auto-role on join")

