"""
KROVEX VAULT — Server Cleaner & Typography Stylizer
Target Guild: 1552400206811631687

1. Deletes all legacy non-vault categories and channels.
2. Re-styles Vault categories and channels with sleek Discord typography.
3. Updates config/vault_channels.json with the styled channel names and IDs.
"""

import socket
_orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

import asyncio
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(r"F:\Death Bot")
load_dotenv(ROOT / ".env")
import discord

TARGET_GUILD_ID = 1552400206811631687
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

# Target Sleek Typography
# Categories:
CATEGORY_STYLES = {
    "VAULT STORAGE": "🔐 ┆ 𝐕𝐀𝐔𝐋𝐓 𝐒𝐓𝐎𝐑𝐀𝐆𝐄",
    "MONITORING CENTER": "📊 ┆ 𝐌𝐎𝐍𝐈𝐓𝐎𝐑𝐈𝐍𝐆 𝐂𝐄𝐍𝐓𝐄𝐑",
    "DISASTER RECOVERY": "♻️ ┆ 𝐃𝐈𝐒𝐀𝐒𝐓𝐄𝐑 𝐑𝐄𝐂𝐎𝐕𝐄𝐑𝐘",
    "OWNER CONTROL": "👑 ┆ 𝐎𝐖𝐍𝐄𝐑 𝐂𝐎𝐍𝐓𝐑𝐎𝐋",
}

# Channels with small caps and clean aesthetic:
CHANNEL_STYLES = {
    # Vault Storage
    "・automatic-backups": "💾┊automatic-backups",
    "・manual-backups": "📦┊manual-backups",
    "・pre-update-backups": "⚡┊pre-update-backups",
    "・database-snapshots": "🗄️┊database-snapshots",
    "・project-archives": "📁┊project-archives",
    # Monitoring Center
    "・backup-dashboard": "📊┊backup-dashboard",
    "・backup-reports": "📜┊backup-reports",
    "・backup-failures": "🚨┊backup-failures",
    "・storage-monitor": "📈┊storage-monitor",
    # Disaster Recovery
    "・restore-history": "⏳┊restore-history",
    "・integrity-checks": "🛡️┊integrity-checks",
    "・recovery-reports": "📑┊recovery-reports",
    # Owner Control
    "・vault-commands": "👑┊vault-commands",
    "・vault-security": "🔒┊vault-security",
    "・vault-audit": "📋┊vault-audit",
}

async def run_clean():
    client = discord.Client(intents=discord.Intents.default())

    @client.event
    async def on_ready():
        print(f"[✓] Logged in as {client.user}", flush=True)
        guild = client.get_guild(TARGET_GUILD_ID)
        assert guild.id == TARGET_GUILD_ID, "Safety check failed!"
        print(f"[✓] Connected to {guild.name} ({guild.id})", flush=True)

        # 1. Identify Vault Categories vs Legacy Categories
        vault_cat_keywords = ["VAULT STORAGE", "MONITORING CENTER", "DISASTER RECOVERY", "OWNER CONTROL"]
        
        legacy_categories = []
        vault_categories = []

        for cat in guild.categories:
            if any(k in cat.name for k in vault_cat_keywords):
                vault_categories.append(cat)
            else:
                legacy_categories.append(cat)

        print(f"\n[+] Found {len(legacy_categories)} legacy categories to remove.", flush=True)
        print(f"[+] Found {len(vault_categories)} vault categories to preserve.", flush=True)

        # Delete uncategorized channels that don't belong to vault
        for ch in guild.channels:
            if ch.category is None and not isinstance(ch, discord.CategoryChannel):
                if not any(k in ch.name for k in CHANNEL_STYLES.keys()):
                    try:
                        print(f"[-] Deleting uncategorized channel: #{ch.name} ({ch.id})...", flush=True)
                        await ch.delete(reason="Purging non-vault channels")
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        print(f"[!] Could not delete #{ch.name}: {e}", flush=True)

        # Delete all channels inside legacy categories, then delete category
        for cat in legacy_categories:
            print(f"\n[-] Purging legacy category '{cat.name}' ({cat.id})...", flush=True)
            for ch in cat.channels:
                try:
                    print(f"    [-] Deleting channel: #{ch.name} ({ch.id})...", flush=True)
                    await ch.delete(reason="Purging non-vault channels")
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"    [!] Could not delete channel #{ch.name}: {e}", flush=True)
            try:
                await cat.delete(reason="Purging legacy category")
                print(f"[✓] Deleted category: {cat.name}", flush=True)
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"[!] Could not delete category {cat.name}: {e}", flush=True)

        # 2. Re-style Vault Categories and Channels with new sleek font
        print(f"\n[+] Updating typography for Vault categories & channels...", flush=True)
        
        new_channel_map = {
            "guild_id": guild.id,
            "guild_name": guild.name,
            "categories": {},
            "channels": {},
        }

        for cat in guild.categories:
            for k, new_cat_name in CATEGORY_STYLES.items():
                if k in cat.name:
                    if cat.name != new_cat_name:
                        print(f"    [~] Renaming category: '{cat.name}' -> '{new_cat_name}'", flush=True)
                        try:
                            await cat.edit(name=new_cat_name)
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            print(f"    [!] Could not rename category: {e}", flush=True)
                    new_channel_map["categories"][k] = cat.id

                    # Rename channels inside this category
                    for ch in cat.channels:
                        for old_k, styled_name in CHANNEL_STYLES.items():
                            if old_k == ch.name or styled_name == ch.name:
                                if ch.name != styled_name:
                                    print(f"        [~] Renaming #{ch.name} -> #{styled_name}", flush=True)
                                    try:
                                        await ch.edit(name=styled_name)
                                        await asyncio.sleep(0.6)
                                    except Exception as e:
                                        print(f"        [!] Could not rename channel: {e}", flush=True)
                                new_channel_map["channels"][old_k] = ch.id
                                new_channel_map["channels"][styled_name] = ch.id

        # Save updated mapping
        cfg_path = ROOT / "config" / "vault_channels.json"
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(new_channel_map, f, indent=2)
        print(f"\n[✓] Updated vault_channels.json with new channel mapping", flush=True)

        await client.close()

    await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(run_clean())
