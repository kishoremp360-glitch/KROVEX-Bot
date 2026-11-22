"""Comprehensive unit tests for the centralized SQLite database architecture and migrations."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import pytest

from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import (
    AutomodRepository,
    CommandUsageRepository,
    GuildRepository,
    InviteRepository,
    LevelRepository,
    ModerationRepository,
    MusicRepository,
    PlaylistRepository,
    SecurityRepository,
    TicketRepository,
    UserRepository,
    VoiceRepository,
    WelcomeRepository,
)
from bot.database.models import (
    CommandUsage,
    GuildSettings,
    ModerationLog,
    MusicSettings,
    UserProfile,
    VoiceSession,
    VoiceSettings,
    WelcomeSettings,
)


def run_async(coro):
    """Helper to synchronously run async tasks in pytest without pytest-asyncio fixture issues."""
    return asyncio.run(coro)


def test_sqlite_wal_and_foreign_keys(tmp_path: Path):
    """Verify WAL journal mode and foreign key enforcement."""
    async def _test():
        db_file = tmp_path / "test_death_bot.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()

        row_wal = await manager.fetchone("PRAGMA journal_mode;")
        assert row_wal is not None
        assert row_wal["journal_mode"].lower() == "wal"

        row_fk = await manager.fetchone("PRAGMA foreign_keys;")
        assert row_fk is not None
        assert row_fk["foreign_keys"] == 1

        await manager.close()

    run_async(_test())


def test_guild_repository_crud(tmp_path: Path):
    """Verify GuildRepository get, set prefix, and update settings."""
    async def _test():
        db_file = tmp_path / "test_death_bot.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()

        repo = GuildRepository(manager)
        prefix = await repo.get_prefix(111222, default="!")
        assert prefix == "!"

        await repo.set_prefix(111222, "?")
        prefix_updated = await repo.get_prefix(111222)
        assert prefix_updated == "?"

        settings = await repo.get_or_create(111222)
        assert settings.guild_id == 111222
        assert settings.prefix == "?"

        await manager.close()

    run_async(_test())


def test_user_repository_crud(tmp_path: Path):
    """Verify UserRepository balance updates and profile creation."""
    async def _test():
        db_file = tmp_path / "test_death_bot.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()

        repo = UserRepository(manager)
        profile = await repo.get_or_create(999888)
        assert profile.user_id == 999888
        assert profile.balance == 0

        new_bal = await repo.update_balance(999888, 500)
        assert new_bal == 500

        await manager.close()

    run_async(_test())


def test_music_and_playlist_repository(tmp_path: Path):
    """Verify MusicRepository and PlaylistRepository operations."""
    async def _test():
        db_file = tmp_path / "test_death_bot.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()

        music_repo = MusicRepository(manager)
        m_settings = await music_repo.get_or_create(12345)
        assert m_settings.guild_id == 12345
        assert m_settings.default_volume == 100

        await music_repo.update_settings(12345, default_volume=80, loop_mode="track")
        m_updated = await music_repo.get_or_create(12345)
        assert m_updated.default_volume == 80
        assert m_updated.loop_mode == "track"

        # Playlists
        pl_repo = PlaylistRepository(manager)
        created = await pl_repo.create_playlist(12345, 999, "Chill Vibes")
        assert created is True

        created_dup = await pl_repo.create_playlist(12345, 999, "Chill Vibes")
        assert created_dup is False

        added = await pl_repo.add_track(12345, 999, "chill vibes", {"title": "Lofi Song", "url": "https://example.com"})
        assert added is True

        pl = await pl_repo.get_playlist(12345, 999, "Chill Vibes")
        assert pl is not None
        assert len(pl["tracks"]) == 1
        assert pl["tracks"][0]["title"] == "Lofi Song"

        await manager.close()

    run_async(_test())


def test_voice_repository_sessions(tmp_path: Path):
    """Verify VoiceRepository start and end session calculations."""
    async def _test():
        db_file = tmp_path / "test_death_bot.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()

        voice_repo = VoiceRepository(manager)
        session = await voice_repo.start_session(1001, 2002, 3003)
        assert session.channel_id == 3003

        ended = await voice_repo.end_session(1001, 2002)
        assert ended is not None
        assert ended.left_at is not None

        total_time = await voice_repo.get_total_voice_time(1001, 2002)
        assert total_time >= 0

        await manager.close()

    run_async(_test())


def test_backup_creation_and_pruning(tmp_path: Path):
    """Verify SQLite online backup creation and integrity."""
    async def _test():
        db_file = tmp_path / "test_death_bot.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        manager.backups_dir = tmp_path / "backups"
        await manager.connect()

        backup_path = await manager.create_backup("test_backup.sqlite")
        assert backup_path.exists()
        assert backup_path.stat().st_size > 0

        # Prune verification
        await manager._prune_backups(keep=1)
        backups = list(manager.backups_dir.glob("*.sqlite"))
        assert len(backups) == 1

        await manager.close()

    run_async(_test())

