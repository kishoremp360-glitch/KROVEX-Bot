import socket
_orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

import os
import sys
import json
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath("."))
load_dotenv("F:/Death Bot/.env")

from bot.config import BotConfig
cfg = BotConfig.from_env()

headers = {
    "Authorization": f"Bot {cfg.token}",
    "User-Agent": "DiscordBot (KROVEX, 1.0)",
}
app_id = "1570428426974662718"
dev_guild_id = "1560990395666538529"

# 1. Fetch Global Commands
req_global = urllib.request.Request(f"https://discord.com/api/v10/applications/{app_id}/commands", headers=headers)
with urllib.request.urlopen(req_global) as resp:
    global_cmds = json.loads(resp.read().decode())

print(f"Total Global Root Commands from Discord REST API: {len(global_cmds)}")

# Inventory of all global command paths
global_paths = set()
for cmd in global_cmds:
    cmd_name = cmd["name"]
    options = cmd.get("options", [])
    if not options:
        global_paths.add(f"/{cmd_name}")
    else:
        has_subcommands = False
        for opt in options:
            if opt.get("type") == 1:  # SUB_COMMAND
                has_subcommands = True
                global_paths.add(f"/{cmd_name}/{opt['name']}")
            elif opt.get("type") == 2:  # SUB_COMMAND_GROUP
                has_subcommands = True
                for nested_opt in opt.get("options", []):
                    if nested_opt.get("type") == 1:
                        global_paths.add(f"/{cmd_name}/{opt['name']}/{nested_opt['name']}")
        if not has_subcommands:
            global_paths.add(f"/{cmd_name}")

print(f"Total Global Command Paths registered on Discord: {len(global_paths)}")

from tests.test_slash_ux_renaming import RENAMED_MAPPINGS

total_renamed = 0
clean_found = 0
clean_missing = []
old_absent = 0
old_found = []

for group, mappings in RENAMED_MAPPINGS.items():
    for clean_name, old_name in mappings:
        total_renamed += 1
        clean_path = f"/{group}/{clean_name}"
        old_path = f"/{group}/{old_name}"
        
        if clean_path in global_paths:
            clean_found += 1
        else:
            clean_missing.append(clean_path)
            
        if old_path not in global_paths:
            old_absent += 1
        else:
            old_found.append(old_path)

print(f"\n--- 88 Slash Command Renames Verification ---")
print(f"Total Renamed Commands Checked: {total_renamed}")
print(f"Clean new paths verified present globally: {clean_found}/{total_renamed}")
print(f"Old redundant paths verified ABSENT globally: {old_absent}/{total_renamed}")
if clean_missing:
    print(f"ERROR: Missing clean paths: {clean_missing}")
if old_found:
    print(f"ERROR: Found old paths: {old_found}")

# 2. Check Guild Commands in Dev Guild
req_guild = urllib.request.Request(f"https://discord.com/api/v10/applications/{app_id}/guilds/{dev_guild_id}/commands", headers=headers)
with urllib.request.urlopen(req_guild) as resp:
    guild_cmds = json.loads(resp.read().decode())

print(f"\nTotal Guild Root Commands in Dev Guild {dev_guild_id}: {len(guild_cmds)}")
