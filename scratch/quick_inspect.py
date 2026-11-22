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

async def inspect():
    client = discord.Client(intents=discord.Intents.default())
    @client.event
    async def on_ready():
        try:
            print("[✓] on_ready reached", flush=True)
            g = client.get_guild(TARGET_GUILD_ID)
            print(f"[✓] Guild: {g.name}", flush=True)
            for c in g.categories:
                print(f"📁 {c.name} (pos={c.position}):", flush=True)
                for ch in c.channels:
                    print(f"   #{ch.name}", flush=True)
        except Exception as e:
            print(f"[ERROR] {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            await client.close()

    await client.start(TOKEN)

asyncio.run(inspect())
