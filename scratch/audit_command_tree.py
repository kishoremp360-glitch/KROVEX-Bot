import asyncio
import os
import sys

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath("."))

from bot.core.bot import DeathBot
from bot.config import BotConfig
from bot.database.sqlite_manager import SQLiteDatabaseManager
from unittest.mock import AsyncMock
from pathlib import Path
import tempfile

async def audit():
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "audit_test.sqlite"
    db = SQLiteDatabaseManager(db_path=db_path)
    await db.connect()

    bot = DeathBot(config=BotConfig.from_env(validate=False))
    bot.db_manager = db
    bot._init_database = AsyncMock()
    bot.sync_app_commands = AsyncMock()

    # Load services
    await bot.load_extension("bot.services.security_service")
    await bot.load_extension("bot.services.automod_service")
    await bot.load_extension("bot.services.dm_queue_service")
    await bot.load_extension("bot.services.logging_service")
    await bot.load_extension("bot.services.mention_service")
    await bot.load_extension("bot.services.bot_role_service")

    # Load all cogs
    await bot.load_cogs()
            
    # Inspect Slash Commands
    root_slash = bot.tree.get_commands()
    print(f"\n--- SLASH COMMAND AUDIT ---")
    print(f"Total Root Slash Commands: {len(root_slash)} (Discord limit: 100, Headroom: {100 - len(root_slash)})")
    
    slash_groups = []
    slash_standalone = []
    total_slash_entries = 0
    
    for cmd in root_slash:
        # Check if group
        subcmds = getattr(cmd, "commands", None)
        if subcmds is not None:
            group_count = len(subcmds)
            slash_groups.append((cmd.name, group_count, [sc.name for sc in subcmds]))
            total_slash_entries += 1 + group_count
        else:
            slash_standalone.append(cmd.name)
            total_slash_entries += 1
            
    print(f"Slash Groups ({len(slash_groups)}):")
    for gname, count, subnames in sorted(slash_groups):
        print(f"  - /{gname} ({count} subcommands): {', '.join(subnames[:8])}{'...' if len(subnames) > 8 else ''}")
        
    print(f"\nStandalone Slash Commands ({len(slash_standalone)}):")
    print(f"  {', '.join(sorted(slash_standalone))}")
    print(f"Total Slash Entries (root + nested): {total_slash_entries}")
    
    # Inspect Prefix Commands
    print(f"\n--- PREFIX COMMAND AUDIT ---")
    prefix_commands = list(bot.commands)
    all_prefix_names = set()
    all_prefix_aliases = set()
    prefix_collisions = []
    
    total_prefix_entries = 0
    prefix_groups = []
    
    for cmd in prefix_commands:
        all_prefix_names.add(cmd.name)
        total_prefix_entries += 1
        
        # Check subcommands
        subcmds = getattr(cmd, "commands", None)
        if subcmds:
            prefix_groups.append((cmd.name, len(subcmds)))
            total_prefix_entries += len(subcmds)
            
        for a in cmd.aliases:
            if a in all_prefix_names or a in all_prefix_aliases:
                prefix_collisions.append((cmd.name, a))
            all_prefix_aliases.add(a)
            
    print(f"Total Root Prefix Commands: {len(prefix_commands)}")
    print(f"Total Prefix Groups: {len(prefix_groups)}")
    print(f"Total Prefix Entries (including subcommands): {total_prefix_entries}")
    print(f"Total Aliases: {len(all_prefix_aliases)}")
    print(f"Alias Collisions Detected: {len(prefix_collisions)}")
    if prefix_collisions:
        for cname, a in prefix_collisions:
            print(f"  COLLISION: command '{cname}' alias '{a}' already claimed")
            
    # Check specific commands
    print(f"\n--- SPECIFIC COMMAND CHECKS ---")
    print("Ownerpanel slash:", bot.tree.get_command("ownerpanel") is not None)
    print("Ownerdashboard slash:", bot.tree.get_command("ownerdashboard") is not None)
    print("Help slash:", bot.tree.get_command("help") is not None)
    print("Ban slash:", bot.tree.get_command("ban") is not None)
    print("Kick slash:", bot.tree.get_command("kick") is not None)
    print("Purge slash:", bot.tree.get_command("purge") is not None)
    print("Vc root slash:", bot.tree.get_command("vc") is not None)
    
    print("Ownerpanel prefix:", bot.get_command("ownerpanel") is not None)
    print("Help prefix:", bot.get_command("help") is not None)
    print("Ban prefix:", bot.get_command("ban") is not None)
    print("Purge prefix:", bot.get_command("purge") is not None)
    print("Clearqueue prefix:", bot.get_command("clearqueue") is not None)
    print("Vc prefix:", bot.get_command("vc") is not None)

if __name__ == "__main__":
    asyncio.run(audit())
