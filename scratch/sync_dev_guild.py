import socket
_orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

import asyncio
import os
import sys
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock
from dotenv import load_dotenv

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath("."))

load_dotenv("F:/Death Bot/.env")

import discord
from bot.core.bot import DeathBot
from bot.config import BotConfig
from bot.database.sqlite_manager import SQLiteDatabaseManager

DEV_GUILD_ID = 1560990395666538529

async def sync_guild():
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        print("ERROR: DISCORD_TOKEN is missing!")
        return 1

    # Safe isolated temp DB for startup
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "sync_temp.sqlite"
    db = SQLiteDatabaseManager(db_path=db_path)
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
    print(f"Total commands in tree to sync: {len(root_commands)}")

    # Step 1: Login via REST (NO GATEWAY CONNECTION!)
    print("Logging into Discord REST API (non-Gateway)...")
    await bot.login(token)
    print(f"Authenticated as Bot User: {bot.user.name} (ID: {bot.user.id})")
    print(f"Target Guild Object: discord.Object(id={DEV_GUILD_ID})")

    # Step 2: Copy to guild ONLY
    dev_guild = discord.Object(id=DEV_GUILD_ID)
    bot.tree.copy_global_to(guild=dev_guild)

    # Step 3: Execute guild-scoped sync
    print(f"Executing guild-scoped sync to guild {DEV_GUILD_ID}...")
    synced = await bot.tree.sync(guild=dev_guild)
    print(f"SUCCESS: Synced {len(synced)} root commands to development guild {DEV_GUILD_ID}!")

    # Print synced root commands summary
    synced_names = [c.name for c in synced]
    print(f"Synced root commands: {', '.join(sorted(synced_names))}")

    # Close HTTP session cleanly
    await bot.close()
    return 0

if __name__ == "__main__":
    code = asyncio.run(sync_guild())
    sys.exit(code)
