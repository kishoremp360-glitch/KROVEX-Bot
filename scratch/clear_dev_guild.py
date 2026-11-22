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
    "Content-Type": "application/json",
    "User-Agent": "DiscordBot (KROVEX, 1.0)",
}
app_id = "1570428426974662718"
dev_guild_id = "1560990395666538529"

print(f"Clearing guild-scoped commands for dev guild {dev_guild_id}...")
put_req = urllib.request.Request(
    f"https://discord.com/api/v10/applications/{app_id}/guilds/{dev_guild_id}/commands",
    data=b"[]",
    headers=headers,
    method="PUT",
)
with urllib.request.urlopen(put_req) as resp:
    res = json.loads(resp.read().decode())
    print(f"PUT response returned {len(res)} commands.")

# Verification 1: Guild commands
get_req = urllib.request.Request(
    f"https://discord.com/api/v10/applications/{app_id}/guilds/{dev_guild_id}/commands",
    headers=headers,
)
with urllib.request.urlopen(get_req) as resp:
    guild_cmds = json.loads(resp.read().decode())

print(f"VERIFICATION: Guild commands in dev guild {dev_guild_id}: {len(guild_cmds)}")
assert len(guild_cmds) == 0, f"Expected 0 guild commands, got {len(guild_cmds)}"

# Verification 2: Global commands
req_global = urllib.request.Request(
    f"https://discord.com/api/v10/applications/{app_id}/commands",
    headers=headers,
)
with urllib.request.urlopen(req_global) as resp:
    global_cmds = json.loads(resp.read().decode())

print(f"VERIFICATION: Global commands count: {len(global_cmds)}")
assert len(global_cmds) == 43, f"Expected 43 global commands, got {len(global_cmds)}"

print("PHASE 4 COMPLETE: Development-guild command list is 0, Global command list is 43!")
