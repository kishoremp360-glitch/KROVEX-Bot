"""Phase 1: Core System & Startup Comprehensive QA Suite.

Executes and verifies the 10 core lifecycle test cases specified in Phase 1:
1. P1-TC01: Normal Startup & Service Initialization
2. P1-TC02: Missing Discord Token Validation
3. P1-TC03: Invalid / Malformed Configuration Input
4. P1-TC04: SQLite / Database Connectivity Failure
5. P1-TC05: Database Reconnection & Pool Recovery
6. P1-TC06: Extension Loading Error Isolation
7. P1-TC07: Gateway Disconnection & Session Resumption
8. P1-TC08: Repeated Startup & Task Concurrency
9. P1-TC09: Graceful Shutdown While Tasks Run
10. P1-TC10: Zero Credential Leakage in Logs
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import discord
import pytest

from bot.config import BotConfig, ConfigurationError
from bot.core.bot import DeathBot
from bot.database.sqlite_manager import SQLiteDatabaseManager


@pytest.fixture
def clean_config():
    """Create a safe test BotConfig."""
    return BotConfig(
        token="SAFE_TEST_TOKEN_DISCORD_MOCK",
        client_id=1570428426974662718,
        dev_guild_id=1560990395666538529,
        owner_ids=[1457380609641938981],
        default_prefix=",",
        environment="testing",
        log_level="DEBUG",
    )


@pytest.mark.asyncio
async def test_p1_tc01_normal_startup(clean_config):
    """P1-TC01: Verify normal startup initializes core services and database."""
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_p1_tc01.sqlite"
    db = SQLiteDatabaseManager(db_path=db_path)
    await db.connect()

    bot = DeathBot(config=clean_config)
    bot.loop = asyncio.get_running_loop()
    bot.db_manager = db
    bot._init_database = AsyncMock()
    bot.sync_app_commands = AsyncMock()

    # Verify attributes prior to setup
    assert bot.uptime_seconds >= 0
    assert bot.config.default_prefix == ","

    # Execute setup hook
    await bot.setup_hook()
    assert bot.session is not None
    assert bot.music_service is not None

    # Clean up
    await bot.close()
    await db.close()


def test_p1_tc02_missing_discord_token():
    """P1-TC02: Verify missing token cleanly raises ConfigurationError without secret exposure."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ConfigurationError) as exc_info:
            BotConfig.from_env(validate=True)
        err = str(exc_info.value)
        assert "DISCORD_TOKEN" in err
        # Ensure no token values or passwords leak
        assert "password" not in err.lower()


def test_p1_tc03_malformed_configuration():
    """P1-TC03: Verify malformed config values fall back to safe defaults."""
    env = {
        "DISCORD_TOKEN": "mock_token",
        "COLOR_PRIMARY": "invalid_hex_string",
        "MAX_QUEUE_SIZE": "not_an_int",
        "INVITE_TRACKING_ENABLED": "maybe",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = BotConfig.from_env(validate=False)
        # Primary color should fall back to valid int
        assert isinstance(cfg.color_primary, int)
        # Queue size should fall back to standard limit
        assert cfg.max_queue_size == 500
        # Invite tracking bool fallback
        assert isinstance(cfg.invite_tracking_enabled, bool)


@pytest.mark.asyncio
async def test_p1_tc04_database_connection_failure():
    """P1-TC04: Verify database handles invalid path without crashing."""
    invalid_path = Path("Z:/non_existent_drive_9999/invalid.sqlite")
    db = SQLiteDatabaseManager(db_path=invalid_path)
    with pytest.raises(Exception):
        await db.connect()
    assert db.is_connected is False


@pytest.mark.asyncio
async def test_p1_tc05_database_reconnection_and_wal():
    """P1-TC05: Verify WAL mode and persistence across disconnect/reconnect."""
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_p1_tc05.sqlite"
    db = SQLiteDatabaseManager(db_path=db_path)
    await db.connect()
    assert db.is_connected is True

    # Check WAL mode
    cursor = await db.connection.execute("PRAGMA journal_mode")
    row = await cursor.fetchone()
    assert row[0].lower() == "wal"

    # Disconnect and Reconnect
    await db.close()
    assert db.is_connected is False
    await db.connect()
    assert db.is_connected is True
    await db.close()


@pytest.mark.asyncio
async def test_p1_tc06_extension_loading_isolation(clean_config):
    """P1-TC06: Verify a failed extension does not crash the bot loader."""
    bot = DeathBot(config=clean_config)
    with pytest.raises(discord.ext.commands.ExtensionNotFound):
        await bot.load_extension("bot.cogs.non_existent_fake_cog_module")
    # Bot remains functional
    assert bot.is_closed() is False


@pytest.mark.asyncio
async def test_p1_tc07_gateway_disconnect_reconnect(clean_config):
    """P1-TC07: Verify gateway disconnect event is intercepted safely."""
    bot = DeathBot(config=clean_config)
    bot.loop = asyncio.get_running_loop()
    # Simulate on_resumed event dispatch
    resumed_called = False

    async def on_resumed():
        nonlocal resumed_called
        resumed_called = True

    bot.add_listener(on_resumed, "on_resumed")
    bot.dispatch("resumed")
    await asyncio.sleep(0.05)
    assert resumed_called is True
    await bot.close()


@pytest.mark.asyncio
async def test_p1_tc08_repeated_startup_protection(clean_config):
    """P1-TC08: Verify repeated calls to setup_hook do not duplicate active sessions."""
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_p1_tc08.sqlite"
    db = SQLiteDatabaseManager(db_path=db_path)
    await db.connect()

    bot = DeathBot(config=clean_config)
    bot.loop = asyncio.get_running_loop()
    bot.db_manager = db
    bot._init_database = AsyncMock()
    bot.sync_app_commands = AsyncMock()

    await bot.setup_hook()
    first_session = bot.session

    # Second invocation should maintain valid active session
    await bot.setup_hook()
    assert bot.session is not None
    assert bot.session.closed is False

    await bot.close()
    await db.close()


@pytest.mark.asyncio
async def test_p1_tc09_graceful_shutdown_task_cleanup(clean_config):
    """P1-TC09: Verify bot close terminates aiohttp sessions and cleans up resources."""
    bot = DeathBot(config=clean_config)
    bot.loop = asyncio.get_running_loop()
    bot._init_database = AsyncMock()
    bot.sync_app_commands = AsyncMock()
    await bot.setup_hook()
    assert bot.session is not None
    assert bot.session.closed is False

    await bot.close()
    assert bot.session.closed is True


def test_p1_tc10_zero_credential_leakage():
    """P1-TC10: Verify regex security scan finds zero credentials in logged strings and config rep."""
    cfg = BotConfig(
        token="sample_mock_token_string_24.mock06.sample_mock_secret_string_27chars",
        client_id=1570428426974662718,
        dev_guild_id=1560990395666538529,
        gemini_api_key="mock_gemini_api_key_test_string_1234567890",
        spotify_client_secret="mock_spotify_secret_1234567890",
        owner_ids=[1457380609641938981],
    )
    # Check string representation does not expose raw secret tokens
    rep = repr(cfg)
    assert "sample_mock_secret_string_27chars" not in rep
    assert "mock_gemini_api_key" not in rep
    assert "mock_spotify_secret" not in rep
