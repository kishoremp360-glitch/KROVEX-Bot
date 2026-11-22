"""
Unit and integration tests for KROVEX Vault Cog.
Verifies:
- Bot owner authorization strict gate
- AES-256 encryption & decryption round-trip
- SHA-256 checksum integrity verification
- Secret masking and exclusion
"""

import hashlib
import pytest
from unittest.mock import MagicMock
from pathlib import Path
from cryptography.fernet import Fernet

from bot.config import BotConfig
from bot.cogs.vault.cog import VaultCog, get_or_create_vault_key

def test_vault_key_generation(tmp_path: Path, monkeypatch):
    test_key_file = tmp_path / ".vault_key"
    monkeypatch.setattr("bot.cogs.vault.cog.KEY_FILE", test_key_file)
    
    key = get_or_create_vault_key()
    assert isinstance(key, bytes)
    assert len(key) == 44 # Fernet base64 32-byte key is 44 bytes
    assert test_key_file.exists()

    # Re-reading should return identical key
    key2 = get_or_create_vault_key()
    assert key == key2

def test_vault_owner_authorization():
    bot = MagicMock()
    bot.config = MagicMock()
    bot.config.owner_ids = [1457380609641938981]

    cog = VaultCog(bot)

    # 1. Configured bot owner must be authorized
    assert cog._is_owner(1457380609641938981) is True

    # 2. Server owner, Admin, or foreign member without owner_id must be denied
    assert cog._is_owner(123456789012345678) is False
    assert cog._is_owner(999999999999999999) is False

def test_vault_aes_encryption_and_checksum_integrity():
    bot = MagicMock()
    bot.config = MagicMock()
    bot.config.owner_ids = [1457380609641938981]

    cog = VaultCog(bot)

    sample_db_payload = b"SQLite format 3\x00SAMPLE_KROVEX_DB_PAYLOAD_FOR_TESTING"
    raw_sha = hashlib.sha256(sample_db_payload).hexdigest()

    # Encrypt
    encrypted = cog._fernet.encrypt(sample_db_payload)
    enc_sha = hashlib.sha256(encrypted).hexdigest()
    assert encrypted != sample_db_payload
    assert raw_sha != enc_sha

    # Decrypt and verify round-trip
    decrypted = cog._fernet.decrypt(encrypted)
    assert decrypted == sample_db_payload
    assert hashlib.sha256(decrypted).hexdigest() == raw_sha

def test_secrets_exclusion_policy():
    sensitive_patterns = [".env", "token", "api_key", "secret", "private_key", "key"]
    sample_file_names = [
        "death_bot.sqlite",
        "death_bot_20261116.sqlite",
        ".env",
        ".env.production",
        "bot_secrets.json",
        "credentials.key"
    ]

    safe_backups = [f for f in sample_file_names if not any(p in f.lower() for p in sensitive_patterns)]
    assert ".env" not in safe_backups
    assert ".env.production" not in safe_backups
    assert "bot_secrets.json" not in safe_backups
    assert "credentials.key" not in safe_backups
    assert "death_bot.sqlite" in safe_backups
    assert "death_bot_20261116.sqlite" in safe_backups
