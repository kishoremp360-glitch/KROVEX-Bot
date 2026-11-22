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

async def test_upload():
    client = discord.Client(intents=discord.Intents.default())
    @client.event
    async def on_ready():
        client.config = type("Config", (), {"owner_ids": [1457380609641938981]})()
        vault = VaultCog(client)
        
        db_path = ROOT / "db" / "death_bot.sqlite"
        print(f"[+] Triggering upload of {db_path}...", flush=True)
        success, msg, bid = await vault.upload_encrypted_backup(
            source_path=db_path,
            backup_type="automatic",
            actor_id=1457380609641938981,
        )
        print(f"[✓] Result: success={success}, msg={msg}, id={bid}", flush=True)
        await client.close()

    await client.start(os.getenv("DISCORD_TOKEN"))

asyncio.run(test_upload())
