import socket
_orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

import asyncio
import os
import sys
import tempfile
import json
import urllib.request
from pathlib import Path
from unittest.mock import AsyncMock
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath("."))
load_dotenv("F:/Death Bot/.env")

import discord
from bot.core.bot import DeathBot
from bot.config import BotConfig
from bot.database.sqlite_manager import SQLiteDatabaseManager

async def sync_global():
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        print("ERROR: DISCORD_TOKEN is missing!")
        return 1

    tmp_dir = tempfile.mkdtemp()
    db = SQLiteDatabaseManager(db_path=Path(tmp_dir) / "global_sync_temp.sqlite")
    await db.connect()

    config = BotConfig.from_env(validate=False)
    bot = DeathBot(config=config)
    bot.db_manager = db
    bot._init_database = AsyncMock()

    # Load services
    await bot.load_extension("bot.services.security_service")
    await bot.load_extension("bot.services.automod_service")
    await bot.load_extension("bot.services.dm_queue_service")
    await bot.load_extension("bot.services.logging_service")
    await bot.load_extension("bot.services.mention_service")
    await bot.load_extension("bot.services.bot_role_service")

    # Load all cogs
    await bot.load_cogs()

    root_commands = bot.tree.get_commands()
    print(f"Total commands in tree to sync globally: {len(root_commands)}")
    if len(root_commands) != 43:
        print(f"WARNING: Expected 43 root commands, found {len(root_commands)}!")

    # Login via REST
    print("Logging into Discord REST API (non-Gateway)...")
    await bot.login(token)
    print(f"Authenticated as: {bot.user.name} (ID: {bot.user.id})")

    # Execute Global tree.sync()
    print("Executing global tree.sync()...")
    synced = await bot.tree.sync()
    print(f"SUCCESS: Synced {len(synced)} root commands globally to Discord!")

    if bot.http:
        await bot.http.close()
    return 0

if __name__ == "__main__":
    code = asyncio.run(sync_global())
    sys.exit(code)
