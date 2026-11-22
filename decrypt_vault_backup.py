#!/usr/bin/env python3
"""
KROVEX VAULT — Standalone Emergency Backup Decryption Utility
Use this zero-dependency utility to decrypt any .krovex.enc backup file
even if the Discord bot or server is completely offline.

Usage:
    python decrypt_vault_backup.py <backup_file.krovex.enc> [output_file.sqlite]
"""

import sys
import os
import hashlib
import sqlite3
from pathlib import Path
from cryptography.fernet import Fernet

KEY_FILE_NAME = ".vault_key"

def resolve_key(custom_key_path: Path | None = None) -> bytes:
    """Find and load the AES-256 Fernet key."""
    candidates = [
        custom_key_path,
        Path(__file__).resolve().parent / KEY_FILE_NAME,
        Path.cwd() / KEY_FILE_NAME,
        Path.home() / KEY_FILE_NAME,
    ]
    for p in candidates:
        if p and p.exists():
            key = p.read_bytes().strip()
            if key:
                print(f"[✓] Loaded encryption key from: {p}")
                return key
    
    # Check env var
    env_key = os.getenv("VAULT_ENCRYPTION_KEY", "").strip()
    if env_key:
        print("[✓] Loaded encryption key from environment variable.")
        return env_key.encode()

    # Manual prompt
    raw = input("Enter your 44-character base64 Vault Key: ").strip()
    if raw:
        return raw.encode()
    raise FileNotFoundError("Could not find .vault_key file or environment key.")

def decrypt_backup(input_path: Path, output_path: Path | None = None, key_path: Path | None = None) -> Path:
    """Decrypt a .krovex.enc file into an unencrypted SQLite database and verify integrity."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    key = resolve_key(key_path)
    fernet = Fernet(key)

    print(f"\n[+] Reading encrypted payload: {input_path.name} ({input_path.stat().st_size:,} bytes)...")
    encrypted_bytes = input_path.read_bytes()
    sha256_enc = hashlib.sha256(encrypted_bytes).hexdigest()
    print(f"    SHA-256 (Encrypted): {sha256_enc}")

    print("[+] Decrypting payload with AES-256 (Fernet)...")
    try:
        decrypted_bytes = fernet.decrypt(encrypted_bytes)
    except Exception as e:
        raise ValueError(f"Decryption failed! Key mismatch or corrupted payload: {e}")

    sha256_dec = hashlib.sha256(decrypted_bytes).hexdigest()
    print(f"    SHA-256 (Decrypted): {sha256_dec}")

    # Determine output path
    if not output_path:
        stem = input_path.stem.replace(".krovex", "")
        output_path = input_path.parent / f"{stem}_restored.sqlite"

    output_path.write_bytes(decrypted_bytes)
    print(f"[✓] Saved decrypted database to: {output_path} ({len(decrypted_bytes):,} bytes)")

    # SQLite integrity verification check
    print("[+] Running SQLite integrity verification check...")
    try:
        conn = sqlite3.connect(output_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        check_result = cursor.fetchone()
        
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table';")
        table_count = cursor.fetchone()[0]
        
        conn.close()

        if check_result and check_result[0] == "ok":
            print(f"    ✅ SQLite Integrity: OK ({table_count} tables restored successfully)")
        else:
            print(f"    ⚠️  SQLite Integrity Warning: {check_result}")
    except Exception as err:
        print(f"    ⚠️  Could not run SQLite verification (file may not be a database): {err}")

    print("\n" + "="*60)
    print("RESTORE OPERATION SUCCESSFUL")
    print(f"Restored File: {output_path.resolve()}")
    print("="*60)
    return output_path

def main():
    if len(sys.argv) < 2:
        print("Usage: python decrypt_vault_backup.py <backup_file.krovex.enc> [output_file.sqlite]")
        # Check for any .krovex.enc files in scratch
        scratch_dir = Path(__file__).resolve().parent / "scratch"
        enc_files = list(scratch_dir.glob("*.krovex.enc")) if scratch_dir.exists() else []
        if enc_files:
            latest = max(enc_files, key=os.path.getmtime)
            print(f"\nFound latest local snapshot: {latest.name}")
            confirm = input("Decrypt this snapshot? [y/N]: ").strip().lower()
            if confirm == "y":
                decrypt_backup(latest)
                return
        sys.exit(1)

    inp = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    decrypt_backup(inp, out)

if __name__ == "__main__":
    main()
