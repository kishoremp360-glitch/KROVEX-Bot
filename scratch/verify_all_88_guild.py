import os
import sys
import socket
import json
import urllib.request
from pathlib import Path

_orig_getaddrinfo = socket.getaddrinfo
def ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = ipv4_getaddrinfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot.config import BotConfig
cfg = BotConfig.from_env()
token = cfg.token

guild_id = "1560990395666538529"
headers = {
    "Authorization": f"Bot {token}",
    "User-Agent": "DiscordBot (https://github.com/theerealrai/KROVEX, 1.0)",
}

req = urllib.request.Request("https://discord.com/api/v10/users/@me", headers=headers)
with urllib.request.urlopen(req) as resp:
    bot_user = json.loads(resp.read().decode())
app_id = bot_user["id"]

guild_url = f"https://discord.com/api/v10/applications/{app_id}/guilds/{guild_id}/commands"
req = urllib.request.Request(guild_url, headers=headers)
with urllib.request.urlopen(req) as resp:
    guild_cmds = json.loads(resp.read().decode())

guild_paths = set()
for cmd in guild_cmds:
    cmd_name = cmd["name"]
    options = cmd.get("options", [])
    has_sub = False
    for opt in options:
        if opt.get("type") == 1:
            has_sub = True
            guild_paths.add(f"{cmd_name} {opt['name']}")
        elif opt.get("type") == 2:
            has_sub = True
            for nested in opt.get("options", []):
                if nested.get("type") == 1:
                    guild_paths.add(f"{cmd_name} {opt['name']} {nested['name']}")
    if not has_sub:
        guild_paths.add(cmd_name)

from tests.test_slash_ux_renaming import RENAMED_MAPPINGS

missing_new = []
found_old = []
total_checked = 0

for group, pairs in RENAMED_MAPPINGS.items():
    for new_sub, old_sub in pairs:
        total_checked += 1
        new_path = f"{group} {new_sub}"
        old_path = f"{group} {old_sub}"
        if new_path not in guild_paths:
            missing_new.append(new_path)
        if old_path in guild_paths:
            found_old.append(old_path)

print(f"Total renamed commands checked: {total_checked}")
print(f"Missing new paths: {len(missing_new)} -> {missing_new}")
print(f"Found old redundant paths: {len(found_old)} -> {found_old}")
if not missing_new and not found_old:
    print("ALL 88 RENAMED COMMANDS PERFECTLY VERIFIED IN DEVELOPMENT GUILD!")
