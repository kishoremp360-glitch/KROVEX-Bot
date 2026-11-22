import os
import sys
from dotenv import load_dotenv

load_dotenv("F:/Death Bot/.env")

dev_guild_id = os.getenv("DEV_GUILD_ID", "").strip()
client_id = os.getenv("DISCORD_CLIENT_ID", "").strip()
token = os.getenv("DISCORD_TOKEN", "").strip()

print(f"DEV_GUILD_ID: {dev_guild_id}")
print(f"DISCORD_CLIENT_ID configured: {bool(client_id)} (Length: {len(client_id)} digits)")
print(f"DISCORD_TOKEN configured: {bool(token)} (Starts with: {token[:6]}... length: {len(token)})")

if dev_guild_id == "1560990395666538529":
    print("PREFLIGHT CHECK: DEV_GUILD_ID matches target guild 1560990395666538529.")
else:
    print(f"PREFLIGHT CHECK MISMATCH: Expected 1560990395666538529, got {dev_guild_id}")
