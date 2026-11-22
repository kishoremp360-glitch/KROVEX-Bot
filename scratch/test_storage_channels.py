import socket
_orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

import asyncio
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(r"F:\Death Bot")
load_dotenv(ROOT / ".env")
import discord

TARGET_GUILD_ID = 1552400206811631687
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

async def test_create():
    client = discord.Client(intents=discord.Intents.default())
    
    @client.event
    async def on_ready():
        print(f"[✓] Logged in as {client.user}", flush=True)
        guild = client.get_guild(TARGET_GUILD_ID)
        cat = discord.utils.get(guild.categories, name="🔐 VAULT STORAGE")
        print(f"[✓] Found category: {cat}", flush=True)
        
        channels_to_create = [
            "・manual-backups",
            "・pre-update-backups",
            "・database-snapshots",
            "・project-archives",
        ]
        
        for name in channels_to_create:
            existing = discord.utils.get(cat.channels, name=name)
            if existing:
                print(f"[✓] Already exists: {name} ({existing.id})", flush=True)
                continue
            
            t0 = time.time()
            print(f"[+] Creating {name}...", flush=True)
            try:
                ch = await guild.create_text_channel(name=name, category=cat)
                elapsed = time.time() - t0
                print(f"[✓] Created {name} ({ch.id}) in {elapsed:.2f}s", flush=True)
            except Exception as e:
                print(f"[✗] Failed {name}: {e}", flush=True)
        
        await client.close()

    await client.start(TOKEN)

asyncio.run(test_create())
