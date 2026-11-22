import socket
_orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

import asyncio
import os
import json
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(r"F:\Death Bot")
load_dotenv(ROOT / ".env")
import discord

async def check():
    client = discord.Client(intents=discord.Intents.default())
    @client.event
    async def on_ready():
        cfg_path = ROOT / "config" / "vault_channels.json"
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)

        # 1. Automatic Backups
        ch_auto = client.get_channel(cfg["channels"]["・automatic-backups"])
        print(f"\n[+] Channel: #{ch_auto.name} ({ch_auto.id})", flush=True)
        async for m in ch_auto.history(limit=3):
            print(f"    Author: {m.author} (ID: {m.author.id})", flush=True)
            print(f"    Attachments: {[a.filename for a in m.attachments]}", flush=True)
            if m.embeds:
                print(f"    Embed Title: {m.embeds[0].title}", flush=True)
                for f in m.embeds[0].fields:
                    print(f"      • {f.name}: {f.value}", flush=True)

        # 2. Backup Dashboard
        ch_dash = client.get_channel(cfg["channels"]["・backup-dashboard"])
        print(f"\n[+] Channel: #{ch_dash.name} ({ch_dash.id})", flush=True)
        async for m in ch_dash.history(limit=3):
            print(f"    Author: {m.author} (ID: {m.author.id})", flush=True)
            if m.embeds:
                print(f"    Embed Title: {m.embeds[0].title}", flush=True)

        # 3. Vault Audit
        ch_audit = client.get_channel(cfg["channels"]["・vault-audit"])
        print(f"\n[+] Channel: #{ch_audit.name} ({ch_audit.id})", flush=True)
        async for m in ch_audit.history(limit=3):
            print(f"    Author: {m.author} (ID: {m.author.id})", flush=True)
            if m.embeds:
                print(f"    Embed Title: {m.embeds[0].title}", flush=True)
                for f in m.embeds[0].fields:
                    print(f"      • {f.name}: {f.value}", flush=True)

        await client.close()

    await client.start(os.getenv("DISCORD_TOKEN"))

asyncio.run(check())
