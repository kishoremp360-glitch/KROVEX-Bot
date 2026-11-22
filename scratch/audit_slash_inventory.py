import asyncio
import os
import sys
import json
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock

# Add project root to sys.path
sys.path.insert(0, os.path.abspath("."))

from bot.core.bot import DeathBot
from bot.config import BotConfig
from bot.database.sqlite_manager import SQLiteDatabaseManager
import discord

async def run_audit():
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "audit_slash.sqlite"
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

    root_commands = bot.tree.get_commands()
    print(f"Total root slash items: {len(root_commands)}")

    # Map all prefix commands and aliases
    prefix_map = {}
    for cmd in bot.commands:
        prefix_map[cmd.name.lower()] = {
            "name": cmd.name,
            "aliases": cmd.aliases,
            "help": cmd.help or "",
            "is_group": hasattr(cmd, "commands") and bool(cmd.commands)
        }
        for alias in cmd.aliases:
            prefix_map[alias.lower()] = {
                "name": cmd.name,
                "alias_used": alias,
                "aliases": cmd.aliases,
                "help": cmd.help or "",
                "is_group": False
            }

    inventory = []
    redundant_names = []
    
    for cmd in sorted(root_commands, key=lambda c: c.name):
        # Case 1: Slash Group
        if hasattr(cmd, "commands"):
            group_name = cmd.name
            group_desc = cmd.description or ""
            subcommands = cmd.commands
            
            for sub in sorted(subcommands, key=lambda s: s.name):
                # Check for nested sub-subgroup
                if hasattr(sub, "commands"):
                    sub_group_name = sub.name
                    for nested in sorted(sub.commands, key=lambda n: n.name):
                        full_path = f"/{group_name} {sub_group_name} {nested.name}"
                        desc = nested.description or ""
                        perms = str(nested.default_permissions) if nested.default_permissions else "None"
                        
                        # Redundancy check
                        is_redundant = (
                            nested.name.startswith(group_name) or 
                            nested.name.startswith(sub_group_name) or
                            (group_name in nested.name and len(nested.name) > len(group_name))
                        )
                        
                        # Find prefix equivalent
                        matching_prefix = prefix_map.get(nested.name.lower()) or prefix_map.get(f"{sub_group_name}{nested.name}".lower())
                        
                        item = {
                            "type": "nested_subcommand",
                            "root": f"/{group_name}",
                            "sub_group": sub_group_name,
                            "subcommand": nested.name,
                            "full_path": full_path,
                            "description": desc,
                            "permissions": perms,
                            "is_redundant": is_redundant,
                            "prefix_equiv": matching_prefix["name"] if matching_prefix else "N/A",
                            "prefix_aliases": matching_prefix["aliases"] if matching_prefix else []
                        }
                        inventory.append(item)
                        if is_redundant:
                            redundant_names.append(item)
                else:
                    full_path = f"/{group_name} {sub.name}"
                    desc = sub.description or ""
                    perms = str(sub.default_permissions) if sub.default_permissions else "None"
                    
                    # Redundancy check
                    # e.g., /security securitywhitelist, /rr rrcreate, /vc vckick, /welcome welcomestatus
                    is_redundant = (
                        sub.name.startswith(group_name) or 
                        (group_name in sub.name and len(sub.name) > len(group_name)) or
                        (group_name == "vc" and sub.name.startswith("vc")) or
                        (group_name == "rr" and sub.name.startswith("rr")) or
                        (group_name == "automod" and sub.name.startswith("automod")) or
                        (group_name == "security" and sub.name.startswith("security")) or
                        (group_name == "welcome" and sub.name.startswith("welcome")) or
                        (group_name == "ticket" and sub.name.startswith("ticket")) or
                        (group_name == "playlist" and sub.name.startswith("playlist")) or
                        (group_name == "logs" and sub.name.startswith("log"))
                    )
                    
                    # Find prefix equivalent
                    # direct name match or prefix match
                    matching_prefix = prefix_map.get(sub.name.lower())
                    if not matching_prefix and sub.name.startswith(group_name):
                        shorter = sub.name[len(group_name):]
                        matching_prefix = prefix_map.get(shorter.lower())
                    
                    item = {
                        "type": "subcommand",
                        "root": f"/{group_name}",
                        "sub_group": None,
                        "subcommand": sub.name,
                        "full_path": full_path,
                        "description": desc,
                        "permissions": perms,
                        "is_redundant": is_redundant,
                        "prefix_equiv": matching_prefix["name"] if matching_prefix else "N/A",
                        "prefix_aliases": matching_prefix["aliases"] if matching_prefix else []
                    }
                    inventory.append(item)
                    if is_redundant:
                        redundant_names.append(item)
        else:
            # Standalone root command
            full_path = f"/{cmd.name}"
            desc = cmd.description or ""
            perms = str(cmd.default_permissions) if cmd.default_permissions else "None"
            matching_prefix = prefix_map.get(cmd.name.lower())
            
            item = {
                "type": "standalone",
                "root": f"/{cmd.name}",
                "sub_group": None,
                "subcommand": None,
                "full_path": full_path,
                "description": desc,
                "permissions": perms,
                "is_redundant": False,
                "prefix_equiv": matching_prefix["name"] if matching_prefix else "N/A",
                "prefix_aliases": matching_prefix["aliases"] if matching_prefix else []
            }
            inventory.append(item)

    print(f"Total Slash Command Paths: {len(inventory)}")
    print(f"Total Redundantly Named Commands Identified: {len(redundant_names)}")

    with open("scratch/slash_inventory.json", "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2)

    with open("scratch/slash_redundant.json", "w", encoding="utf-8") as f:
        json.dump(redundant_names, f, indent=2)

    # Print summary of redundant commands grouped by parent
    grouped_redundant = {}
    for r in redundant_names:
        parent = r["root"]
        grouped_redundant.setdefault(parent, []).append(r)
        
    print("\n--- REDUNDANCY SUMMARY BY GROUP ---")
    for parent, items in sorted(grouped_redundant.items()):
        print(f"\nGroup {parent} ({len(items)} redundant names):")
        for it in items:
            print(f"  - {it['full_path']:<35} (desc: {it['description'][:40]}...)")

if __name__ == "__main__":
    asyncio.run(run_audit())
