import socket
_orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.abspath("."))
from bot.core.bot import DeathBot
from bot.config import BotConfig
from bot.database.sqlite_manager import SQLiteDatabaseManager

async def audit():
    tmp_dir = tempfile.mkdtemp()
    db = SQLiteDatabaseManager(db_path=Path(tmp_dir) / "audit.sqlite")
    await db.connect()
    
    cfg = BotConfig.from_env(validate=False)
    bot = DeathBot(config=cfg)
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

    tree_cmds = bot.tree.get_commands()
    print(f"Root slash commands count: {len(tree_cmds)} (Limit is 100 -> OK: {len(tree_cmds) <= 100})")

    # 1. Check duplicate root commands
    root_names = [c.name for c in tree_cmds]
    dup_roots = [name for name in set(root_names) if root_names.count(name) > 1]
    print(f"Duplicate root commands: {dup_roots}")

    # 2. Extract all subcommand paths and check duplicates
    all_paths = set()
    dup_paths = []
    
    def walk(cmd, prefix=""):
        full = f"{prefix}/{cmd.name}" if prefix else f"/{cmd.name}"
        subcmds = getattr(cmd, "commands", None)
        if subcmds:
            for sub in subcmds:
                walk(sub, full)
        else:
            if full in all_paths:
                dup_paths.append(full)
            all_paths.add(full)

    for c in tree_cmds:
        walk(c)

    print(f"Total slash command paths in local tree: {len(all_paths)}")
    print(f"Duplicate slash command paths: {dup_paths}")

    # 3. Check representative renamed commands
    renamed_checks = [
        ("/vc/kick", "/vc/vckick"),
        ("/vc/drag", "/vc/vcdrag"),
        ("/vc/info", "/vc/vcinfo"),
        ("/security/status", "/security/securitystatus"),
        ("/security/whitelist", "/security/securitywhitelist"),
        ("/logs/status", "/logs/logsstatus"),
        ("/logs/voice", "/logs/logsvoice"),
        ("/welcome/setup", "/welcome/welcomesetup"),
        ("/automod/status", "/automod/automodstatus"),
        ("/rr/create", "/rr/rrcreate"),
        ("/music/status", "/music/musicstatus"),
        ("/rate/simp", "/rate/ratesimp"),
    ]

    print("\n--- Verifying Sample Renamed Paths ---")
    all_renamed_ok = True
    for clean_path, old_path in renamed_checks:
        has_clean = clean_path in all_paths
        has_old = old_path in all_paths
        if has_clean and not has_old:
            print(f"  [PASS] {clean_path} present, {old_path} absent")
        else:
            print(f"  [FAIL] {clean_path} (present={has_clean}), {old_path} (present={has_old})")
            all_renamed_ok = False

    print(f"Sample rename verification: {'PASS' if all_renamed_ok else 'FAIL'}")

    # 4. Check prefix commands
    prefix_cmds = [c.name for c in bot.commands]
    aliases = []
    for c in bot.commands:
        aliases.extend(c.aliases)
    print(f"\nPrefix commands count: {len(prefix_cmds)}")
    print(f"Total prefix aliases count: {len(aliases)}")
    vcpanel_ok = "vcpanel" in prefix_cmds or any("vcpanel" in c.aliases for c in bot.commands)
    vcstaff_ok = "vcstaff" in prefix_cmds or any("vcstaff" in c.aliases for c in bot.commands)
    print(f".vcpanel present in prefix commands: {vcpanel_ok}")
    print(f".vcstaff present in prefix commands: {vcstaff_ok}")

    if bot.http:
        await bot.http.close()

if __name__ == "__main__":
    asyncio.run(audit())
