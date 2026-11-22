"""Unit tests for configuration validation and secret masking."""

import os
import pytest

from bot.config import BotConfig, ConfigurationError


def test_config_missing_token_raises_error(monkeypatch):
    """Verify that missing DISCORD_TOKEN raises ConfigurationError."""
    monkeypatch.setenv("DISCORD_TOKEN", "")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017")

    with pytest.raises(ConfigurationError) as exc_info:
        BotConfig.from_env(validate=True)
    assert "DISCORD_TOKEN" in str(exc_info.value)


def test_config_placeholder_token_raises_error(monkeypatch):
    """Verify that placeholder DISCORD_TOKEN raises ConfigurationError."""
    monkeypatch.setenv("DISCORD_TOKEN", "your_bot_token_here")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017")

    with pytest.raises(ConfigurationError) as exc_info:
        BotConfig.from_env(validate=True)
    assert "DISCORD_TOKEN" in str(exc_info.value)


def test_config_missing_token_raises_error(monkeypatch):
    """Verify that missing DISCORD_TOKEN raises ConfigurationError."""
    monkeypatch.setenv("DISCORD_TOKEN", "")

    with pytest.raises(ConfigurationError) as exc_info:
        BotConfig.from_env(validate=True)
    assert "DISCORD_TOKEN" in str(exc_info.value)


def test_config_valid_env_parsing(monkeypatch):
    """Verify that valid environment variables are parsed correctly."""
    monkeypatch.setenv("DISCORD_TOKEN", "valid_token_xyz")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "123456789012345678")
    monkeypatch.setenv("DEV_GUILD_ID", "987654321098765432")
    monkeypatch.setenv("OWNER_IDS", "111,222, 333")
    monkeypatch.setenv("MONGODB_URI", "mongodb://dbuser:secretpass@cluster0.net:27017")
    monkeypatch.setenv("MONGODB_DATABASE", "test_db")
    monkeypatch.setenv("DEFAULT_PREFIX", "?")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("MAX_QUEUE_SIZE", "250")
    monkeypatch.setenv("DEFAULT_VOLUME", "80")
    monkeypatch.setenv("SYNC_COMMANDS_ON_STARTUP", "false")

    cfg = BotConfig.from_env(validate=True)
    assert cfg.token == "valid_token_xyz"
    assert cfg.client_id == 123456789012345678
    assert cfg.dev_guild_id == 987654321098765432
    assert cfg.owner_ids == [111, 222, 333]
    assert cfg.mongodb_database == "test_db"
    assert cfg.default_prefix == "?"
    assert cfg.environment == "staging"
    assert cfg.log_level == "DEBUG"
    assert cfg.max_queue_size == 250
    assert cfg.default_volume == 80
    assert cfg.sync_commands_on_startup is False


def test_config_secret_masking(monkeypatch):
    """Verify that tokens and database passwords are redacted in repr."""
    monkeypatch.setenv("DISCORD_TOKEN", "super_secret_discord_bot_token")
    monkeypatch.setenv("MONGODB_URI", "mongodb://dbuser:supersecretpass@cluster.mongodb.net")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "super_secret_spotify_secret_123")

    cfg = BotConfig.from_env(validate=True)
    repr_str = repr(cfg)

    # Token must NOT be in repr
    assert "super_secret_discord_bot_token" not in repr_str
    assert "***REDACTED***" in repr_str
    # Password must NOT be in repr
    assert "supersecretpass" not in repr_str
    # Verified regex mask in safe_repr
    safe = cfg.safe_repr()
    assert "supersecretpass" not in safe["mongodb_uri"]
    assert "://***REDACTED***@" in safe["mongodb_uri"]
    assert safe["spotify_client_secret"] == "***REDACTED***"
    assert "super_secret_spotify_secret_123" not in repr_str

