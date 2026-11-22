"""Unit tests for database models, serialization, and connection manager."""

import pytest

from bot.database.connection import DatabaseConnectionError, DatabaseManager
from bot.database.models import (
    CommandUsage,
    GuildSettings,
    ModerationLog,
    MusicSettings,
    UserProfile,
    VoiceSession,
    VoiceSettings,
    WelcomeSettings,
    utc_now,
)


def test_database_manager_disconnected_state():
    """Verify DatabaseManager raises errors when operations called while disconnected."""
    mgr = DatabaseManager(uri="", database_name="test_db")
    assert not mgr.is_connected

    with pytest.raises(DatabaseConnectionError):
        _ = mgr.client

    with pytest.raises(DatabaseConnectionError):
        _ = mgr.db


@pytest.mark.asyncio
async def test_database_manager_ping_when_disconnected():
    """Verify ping returns False when disconnected."""
    mgr = DatabaseManager(uri="", database_name="test_db")
    result = await mgr.ping()
    assert result is False


def test_guild_settings_serialization():
    """Verify GuildSettings serialization roundtrip."""
    original = GuildSettings(guild_id=123456789, prefix="!!", dj_role_ids=[1, 2, 3])
    data = original.to_dict()
    assert data["guild_id"] == 123456789
    assert data["prefix"] == "!!"
    assert data["dj_role_ids"] == [1, 2, 3]

    restored = GuildSettings.from_dict(data)
    assert restored.guild_id == original.guild_id
    assert restored.prefix == original.prefix
    assert restored.dj_role_ids == original.dj_role_ids


def test_user_profile_serialization():
    """Verify UserProfile serialization roundtrip."""
    profile = UserProfile(user_id=987654321, xp=500, level=3, balance=2500)
    data = profile.to_dict()
    assert data["user_id"] == 987654321
    assert data["xp"] == 500
    assert data["level"] == 3
    assert data["balance"] == 2500

    restored = UserProfile.from_dict(data)
    assert restored.user_id == 987654321
    assert restored.balance == 2500


def test_music_settings_serialization():
    """Verify MusicSettings serialization roundtrip."""
    settings = MusicSettings(guild_id=111, default_volume=75, loop_mode="track", twenty_four_seven=True)
    data = settings.to_dict()
    restored = MusicSettings.from_dict(data)
    assert restored.guild_id == 111
    assert restored.default_volume == 75
    assert restored.loop_mode == "track"
    assert restored.twenty_four_seven is True


def test_voice_settings_serialization():
    """Verify VoiceSettings serialization roundtrip."""
    vsettings = VoiceSettings(guild_id=222, enabled=True, status_channel_id=333, update_interval=45)
    data = vsettings.to_dict()
    restored = VoiceSettings.from_dict(data)
    assert restored.guild_id == 222
    assert restored.enabled is True
    assert restored.status_channel_id == 333
    assert restored.update_interval == 45


def test_welcome_settings_serialization():
    """Verify WelcomeSettings serialization roundtrip."""
    wsettings = WelcomeSettings(guild_id=444, enabled=True, channel_id=555, auto_role_ids=[666, 777])
    data = wsettings.to_dict()
    restored = WelcomeSettings.from_dict(data)
    assert restored.guild_id == 444
    assert restored.enabled is True
    assert restored.channel_id == 555
    assert restored.auto_role_ids == [666, 777]


@pytest.mark.asyncio
async def test_guild_repo_duplicate_race_handling():
    """Verify GuildRepository safely recovers from DuplicateKeyError during concurrent get_or_create."""
    from unittest.mock import AsyncMock, MagicMock
    from pymongo.errors import DuplicateKeyError
    from bot.database.repositories.guild_repo import GuildRepository

    mock_coll = MagicMock()
    mock_coll.name = "guild_settings"
    # First find_one returns None, simulating new guild
    # insert_one raises DuplicateKeyError, simulating a concurrent task inserted first
    # Second find_one returns the winner's document
    existing_doc = {"guild_id": 999, "prefix": "!"}
    mock_coll.find_one = AsyncMock(side_effect=[None, existing_doc])
    mock_coll.insert_one = AsyncMock(side_effect=DuplicateKeyError("Duplicate key"))

    repo = GuildRepository(mock_coll)
    settings = await repo.get_or_create(999, default_prefix="!")

    assert settings.guild_id == 999
    assert settings.prefix == "!"


@pytest.mark.asyncio
async def test_voice_repo_closes_dangling_sessions():
    """Verify VoiceRepository.start_session closes prior active sessions for the same user."""
    from unittest.mock import AsyncMock, MagicMock
    from bot.database.repositories.voice_repo import VoiceRepository

    mock_settings_coll = MagicMock()
    mock_sessions_coll = MagicMock()

    # Mock open session
    open_doc = {
        "_id": "sess_1",
        "guild_id": 1,
        "user_id": 2,
        "channel_id": 3,
        "joined_at": utc_now(),
        "left_at": None,
        "duration_seconds": 0,
    }
    mock_sessions_coll.find_one = AsyncMock(return_value=open_doc)
    mock_sessions_coll.update_one = AsyncMock()
    mock_sessions_coll.insert_one = AsyncMock()

    repo = VoiceRepository(mock_settings_coll, mock_sessions_coll)
    new_session = await repo.start_session(guild_id=1, user_id=2, channel_id=4)

    # Must have updated the open session
    mock_sessions_coll.update_one.assert_awaited_once()
    # Must have inserted the new session
    mock_sessions_coll.insert_one.assert_awaited_once()
    assert new_session.channel_id == 4

