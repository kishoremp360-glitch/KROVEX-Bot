import socket
_orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

import asyncio
import os
import sys
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
        print(f"[✓] Guild: {guild.name}", flush=True)
        cat = discord.utils.get(guild.categories, name="🔐 VAULT STORAGE")
        print(f"[✓] Found category: {cat}", flush=True)
        try:
            print("[+] Creating channel '・automatic-backups'...", flush=True)
            ch = await guild.create_text_channel(
                name="・automatic-backups",
                category=cat,
                reason="Test Channel",
            )
            print(f"[✓] Created channel: {ch.name} ({ch.id})", flush=True)
        except Exception as e:
            print(f"[✗] Error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        await client.close()

    await client.start(TOKEN)

asyncio.run(test_create())
