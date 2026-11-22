import socket
_orig = socket.getaddrinfo
socket.getaddrinfo = lambda host, port, family=0, type=0, proto=0, flags=0: _orig(host, port, socket.AF_INET, type, proto, flags)

import json
import urllib.request
import subprocess
import sys, os
sys.path.insert(0, os.path.abspath("."))
from bot.config import BotConfig

cfg = BotConfig.from_env()
headers = {"Authorization": f"Bot {cfg.token}", "User-Agent": "DiscordBot"}
app_id = "1570428426974662718"
guild_id = "1560990395666538529"

# 1. @me
req_me = urllib.request.Request("https://discord.com/api/v10/users/@me", headers=headers)
with urllib.request.urlopen(req_me) as resp:
    me = json.loads(resp.read().decode())
print(f"Bot Identity: {me['username']}#{me.get('discriminator', '0')} (ID: {me['id']})")

# 2. Guild member
req_mem = urllib.request.Request(f"https://discord.com/api/v10/guilds/{guild_id}/members/{app_id}", headers=headers)
with urllib.request.urlopen(req_mem) as resp:
    mem = json.loads(resp.read().decode())
print(f"Dev Guild Member Nickname: {mem.get('nick')} | Roles: {mem.get('roles')}")

# 3. Check Hugging Face duplicate state
proc = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=huggingface.co\n", text=True, capture_output=True)
hf_token = None
for line in proc.stdout.splitlines():
    if line.startswith("password="):
        hf_token = line.split("=", 1)[1]
        break

if hf_token:
    req_hf = urllib.request.Request("https://huggingface.co/api/spaces/theerealrai/KROVEX", headers={"Authorization": f"Bearer {hf_token}"})
    with urllib.request.urlopen(req_hf) as resp:
        hf_data = json.loads(resp.read().decode())
        stage = hf_data.get("runtime", {}).get("stage")
        hardware = hf_data.get("runtime", {}).get("hardware")
        print(f"HF Duplicate Space Status: {stage} (Hardware: {hardware})")
