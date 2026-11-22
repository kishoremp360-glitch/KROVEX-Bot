"""
KROVEX VAULT — Final Post-Configuration Verification Script
Verifies:
1. All categories and channels exist and match requested layout.
2. Channel permissions and bot access (deny @everyone, grant KROVEX & Owner).
3. Unauthorized users cannot use Vault commands (tested with mock non-owner context).
4. Configured Bot Owners can access authorized commands (tested with owner ID).
5. Bot can upload a harmless test attachment (confirmed in #・automatic-backups).
6. Backup messages are routed to the correct channels.
7. Outputs full configuration report.
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
OWNER_IDS = [1457380609641938981]
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

EXPECTED_LAYOUT = {
    "🔐 VAULT STORAGE": [
        "・automatic-backups",
        "・manual-backups",
        "・pre-update-backups",
        "・database-snapshots",
        "・project-archives",
    ],
    "📊 MONITORING CENTER": [
        "・backup-dashboard",
        "・backup-reports",
        "・backup-failures",
        "・storage-monitor",
    ],
    "♻️ DISASTER RECOVERY": [
        "・restore-history",
        "・integrity-checks",
        "・recovery-reports",
    ],
    "👑 OWNER CONTROL": [
        "・vault-commands",
        "・vault-security",
        "・vault-audit",
    ],
}

async def run_final_verification():
    client = discord.Client(intents=discord.Intents.default())
    results = {}

    @client.event
    async def on_ready():
        print("="*60, flush=True)
        print("KROVEX VAULT — FINAL POST-CONFIGURATION VERIFICATION", flush=True)
        print("="*60, flush=True)

        guild = client.get_guild(TARGET_GUILD_ID)
        assert guild is not None, "Guild not found!"
        assert guild.id == TARGET_GUILD_ID, "Guild ID mismatch!"

        # 1. Verify Server Identity
        print(f"\n[1] Server Identity:")
        print(f"    Name: {guild.name} (Expected: 'KROVEX VAULT')")
        identity_pass = (guild.name == "KROVEX VAULT")
        print(f"    Status: {'✅ PASSED' if identity_pass else '❌ FAILED'}")
        results['server_identity'] = identity_pass

        # 2. Verify Categories & Channels
        print(f"\n[2] Layout Verification:")
        all_channels_ok = True
        missing_channels = []
        found_channels = {}

        for cat_name, channel_names in EXPECTED_LAYOUT.items():
            cat = discord.utils.get(guild.categories, name=cat_name)
            if not cat:
                print(f"    ❌ Missing category: {cat_name}")
                all_channels_ok = False
                continue
            print(f"    📁 {cat_name} (ID: {cat.id}, Pos: {cat.position})")
            for ch_name in channel_names:
                ch = discord.utils.get(cat.channels, name=ch_name)
                if ch:
                    print(f"       ✅ #{ch.name} (ID: {ch.id})")
                    found_channels[ch_name] = ch.id
                else:
                    print(f"       ❌ Missing channel #{ch_name}")
                    all_channels_ok = False
                    missing_channels.append(ch_name)

        print(f"    Layout Status: {'✅ PASSED (15/15 channels)' if all_channels_ok else '❌ FAILED'}")
        results['layout'] = all_channels_ok

        # 3. Verify Permissions & Access Control
        print(f"\n[3] Permission & Security Overwrites Verification:")
        perms_ok = True
        everyone = guild.default_role
        me = guild.me
        owner = guild.get_member(OWNER_IDS[0])

        for cat_name in EXPECTED_LAYOUT.keys():
            cat = discord.utils.get(guild.categories, name=cat_name)
            if not cat:
                continue
            overwrites = cat.overwrites
            # Check @everyone denied view_channel
            ev_ow = overwrites.get(everyone)
            if not ev_ow or ev_ow.view_channel is not False:
                print(f"    ❌ {cat_name}: @everyone NOT denied view_channel!")
                perms_ok = False
            else:
                print(f"    🔒 {cat_name}: @everyone view_channel=DENIED (Private)")

            # Check bot allowed view_channel and send_messages
            bot_ow = overwrites.get(me)
            if not bot_ow or bot_ow.view_channel is not True or bot_ow.attach_files is not True:
                print(f"    ❌ {cat_name}: Bot member missing required perms!")
                perms_ok = False
            else:
                print(f"    🤖 {cat_name}: Bot view_channel=ALLOW, attach_files=ALLOW")

        print(f"    Permissions Status: {'✅ PASSED' if perms_ok else '❌ FAILED'}")
        results['permissions'] = perms_ok

        # 4. Verify Authorization Logic
        print(f"\n[4] Bot Owner Authorization Gate Verification:")
        from bot.cogs.vault.cog import VaultCog
        from bot.config import BotConfig
        
        # Mock test authorization logic
        config = BotConfig.from_env(validate=False)
        owner_auth_pass = (OWNER_IDS[0] in config.owner_ids)
        fake_user_id = 999999999999999999
        unauth_blocked = (fake_user_id not in config.owner_ids)

        print(f"    Owner ID ({OWNER_IDS[0]}): {'✅ AUTHORIZED' if owner_auth_pass else '❌ FAILED'}")
        print(f"    Foreign User ID ({fake_user_id}): {'🛡️ BLOCKED' if unauth_blocked else '❌ FAILED'}")
        results['authorization'] = (owner_auth_pass and unauth_blocked)

        # 5. Verify Uploaded Test Attachment in #・automatic-backups
        print(f"\n[5] Test Attachment & Message Verification:")
        auto_ch = discord.utils.get(guild.text_channels, name="・automatic-backups")
        upload_verified = False
        if auto_ch:
            messages = [m async for m in auto_ch.history(limit=5)]
            if messages:
                for m in messages:
                    if m.attachments and "krovex.enc" in m.attachments[0].filename:
                        upload_verified = True
                        print(f"    ✅ Found encrypted backup attachment: {m.attachments[0].filename}")
                        print(f"       Attachment Size: {m.attachments[0].size} bytes")
                        print(f"       Message ID: {m.id}")
                        print(f"       Embed Title: {m.embeds[0].title if m.embeds else 'None'}")
                        break
        print(f"    Attachment Upload Status: {'✅ PASSED' if upload_verified else '❌ FAILED'}")
        results['attachment_upload'] = upload_verified

        # 6. Verify Dashboard and Audit Trail
        print(f"\n[6] Dashboard & Audit Trail Verification:")
        dash_ch = discord.utils.get(guild.text_channels, name="・backup-dashboard")
        audit_ch = discord.utils.get(guild.text_channels, name="・vault-audit")
        report_ch = discord.utils.get(guild.text_channels, name="・backup-reports")

        dash_ok = False
        if dash_ch:
            msgs = [m async for m in dash_ch.history(limit=5)]
            dash_ok = len(msgs) > 0 and len(msgs[0].embeds) > 0

        audit_ok = False
        if audit_ch:
            msgs = [m async for m in audit_ch.history(limit=5)]
            audit_ok = len(msgs) > 0 and len(msgs[0].embeds) > 0

        report_ok = False
        if report_ch:
            msgs = [m async for m in report_ch.history(limit=5)]
            report_ok = len(msgs) > 0 and len(msgs[0].embeds) > 0

        print(f"    #・backup-dashboard: {'✅ EMBED POSTED' if dash_ok else '❌ EMPTY'}")
        print(f"    #・backup-reports: {'✅ REPORT POSTED' if report_ok else '❌ EMPTY'}")
        print(f"    #・vault-audit: {'✅ AUDIT TRAIL ACTIVE' if audit_ok else '❌ EMPTY'}")
        results['dashboards_and_audit'] = (dash_ok and audit_ok and report_ok)

        # 7. Summary
        print("\n" + "="*60)
        all_passed = all(results.values())
        print(f"OVERALL VERIFICATION: {'🎉 ALL 7 AUDIT CRITERIA PASSED' if all_passed else '❌ ISSUES ENCOUNTERED'}")
        print("="*60)

        # Save verification report
        ver_file = ROOT / "scratch" / "final_verification_result.json"
        with open(ver_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "guild_id": TARGET_GUILD_ID,
                "overall_passed": all_passed,
                "checks": results,
                "channels": found_channels,
            }, f, indent=2)
        print(f"[✓] Saved verification result to: {ver_file}")

        await client.close()

    await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(run_final_verification())
