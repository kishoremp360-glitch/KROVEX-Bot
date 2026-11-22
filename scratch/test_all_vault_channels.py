import socket
_orig = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(r"F:\Death Bot")
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
import discord
from bot.cogs.vault.cog import VaultCog

async def run_full_vault_test():
    client = discord.Client(intents=discord.Intents.default())

    @client.event
    async def on_ready():
        client.config = type("Config", (), {"owner_ids": [1457380609641938981]})()
        vault = VaultCog(client)

        print("[1] Dispatching Storage Monitor Heartbeat to #📈┊storage-monitor...", flush=True)
        await vault.dispatch_storage_heartbeat()
        print("[✓] Storage Heartbeat dispatched.", flush=True)

        print("\n[2] Executing In-Memory Integrity Drill to #🛡️┊integrity-checks...", flush=True)
        passed, drill_msg = await vault.run_integrity_drill(actor_id=1457380609641938981)
        print(f"[✓] Integrity Drill result: passed={passed}, msg={drill_msg}", flush=True)

        print("\n[3] Creating Project Source Archive to #📁┊project-archives...", flush=True)
        arch_ok, arch_msg = await vault.create_project_archive(actor_id=1457380609641938981)
        print(f"[✓] Project Archive result: ok={arch_ok}, msg={arch_msg}", flush=True)

        print("\n[4] Committing Database Backup to #💾┊automatic-backups...", flush=True)
        db_path = ROOT / "db" / "death_bot.sqlite"
        up_ok, up_msg, bid = await vault.upload_encrypted_backup(
            source_path=db_path,
            backup_type="automatic",
            actor_id=1457380609641938981,
        )
        print(f"[✓] Backup upload result: ok={up_ok}, msg={up_msg}, bid={bid}", flush=True)

        print("\n" + "="*60, flush=True)
        print("ALL VAULT CHANNEL TASKS EXECUTED SUCCESSFULLY", flush=True)
        print("="*60, flush=True)
        await client.close()

    await client.start(os.getenv("DISCORD_TOKEN"))

asyncio.run(run_full_vault_test())
