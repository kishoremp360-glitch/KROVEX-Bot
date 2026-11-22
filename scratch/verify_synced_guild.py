import os
import sys
import socket
import json
import urllib.request
from dotenv import load_dotenv

# Force IPv4 on Windows to prevent semaphore timeout
_orig_getaddrinfo = socket.getaddrinfo
def ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = ipv4_getaddrinfo

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot.config import BotConfig
cfg = BotConfig.from_env()
token = cfg.token

guild_id = "1560990395666538529"
headers = {
    "Authorization": f"Bot {token}",
    "User-Agent": "DiscordBot (https://github.com/theerealrai/KROVEX, 1.0)",
}

# 1. Get Current Bot User ID
req = urllib.request.Request("https://discord.com/api/v10/users/@me", headers=headers)
with urllib.request.urlopen(req) as resp:
    bot_user = json.loads(resp.read().decode())
app_id = bot_user["id"]
print(f"Bot User: {bot_user['username']}#{bot_user.get('discriminator', '0')} (ID: {app_id})")

# 2. Query Guild Commands
guild_url = f"https://discord.com/api/v10/applications/{app_id}/guilds/{guild_id}/commands"
req = urllib.request.Request(guild_url, headers=headers)
with urllib.request.urlopen(req) as resp:
    guild_cmds = json.loads(resp.read().decode())

print(f"\n--- Registered Guild Commands in {guild_id} ---")
print(f"Total root commands in guild: {len(guild_cmds)}")

# Inventory of all guild command paths
guild_command_paths = {}
for cmd in guild_cmds:
    cmd_name = cmd["name"]
    options = cmd.get("options", [])
    subcommands = []
    for opt in options:
        # Type 1 = SUB_COMMAND, Type 2 = SUB_COMMAND_GROUP
        if opt.get("type") == 1:
            subcommands.append(opt["name"])
            guild_command_paths[f"/{cmd_name} {opt['name']}"] = opt.get("description", "")
        elif opt.get("type") == 2:
            nested_opts = opt.get("options", [])
            for nested in nested_opts:
                if nested.get("type") == 1:
                    subcommands.append(f"{opt['name']} {nested['name']}")
                    guild_command_paths[f"/{cmd_name} {opt['name']} {nested['name']}"] = nested.get("description", "")
    if not subcommands:
        guild_command_paths[f"/{cmd_name}"] = cmd.get("description", "")

root_names = sorted([cmd["name"] for cmd in guild_cmds])
print(f"Root commands ({len(root_names)}): {', '.join(root_names)}")

# 3. Check Representative Renamed Commands
expected_present = [
    "/vc kick", "/vc drag", "/vc info",
    "/security status", "/security whitelist",
    "/logs status", "/logs voice",
    "/welcome setup",
    "/automod status",
    "/rr create",
    "/music status",
    "/rate simp"
]

print("\n--- Verifying Representative Renamed Commands ---")
all_present = True
for path in expected_present:
    if path in guild_command_paths:
        print(f"  [PASS] Found: {path}")
    else:
        print(f"  [FAIL] Missing: {path}")
        all_present = False

# 4. Check Absence of Old Redundant Command Names
expected_absent = [
    "/vc vckick", "/vc vcdrag", "/vc vcinfo",
    "/security securitystatus", "/security securitywhitelist",
    "/logs logsstatus", "/logs logsvoice",
    "/welcome welcomesetup",
    "/automod automodstatus",
    "/rr rrcreate",
    "/music musicstatus",
    "/rate ratesimp"
]

print("\n--- Verifying Absence of Old Redundant Commands ---")
all_absent = True
for path in expected_absent:
    if path in guild_command_paths:
        print(f"  [FAIL] Found old redundant path: {path}")
        all_absent = False
    else:
        print(f"  [PASS] Correctly absent: {path}")

# 5. Check Global Commands (to ensure global was NOT touched/synced with guild sync)
global_url = f"https://discord.com/api/v10/applications/{app_id}/commands"
req = urllib.request.Request(global_url, headers=headers)
with urllib.request.urlopen(req) as resp:
    global_cmds = json.loads(resp.read().decode())
print(f"\n--- Global Commands State ---")
print(f"Total global commands: {len(global_cmds)}")
global_names = sorted([c["name"] for c in global_cmds])
print(f"Global command names: {', '.join(global_names)}")

# Summary
print(f"\nSummary:")
print(f"  Guild sync verified: {all_present and all_absent}")
print(f"  Total guild paths registered: {len(guild_command_paths)}")
