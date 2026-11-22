"""
KROVEX VAULT — Safe Server Inspection Script
Inspects Discord server 1552400206811631687 and reports current state.
Does NOT modify anything.
"""
import asyncio
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

# Add project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import discord

TARGET_GUILD_ID = 1552400206811631687
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

async def inspect():
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    intents.message_content = True

    client = discord.Client(intents=intents)
    report = {}

    @client.event
    async def on_ready():
        try:
            print(f"[✓] Logged in as {client.user} (ID: {client.user.id})")
            
            guild = client.get_guild(TARGET_GUILD_ID)
            if not guild:
                print(f"[✗] Bot is NOT in server {TARGET_GUILD_ID}")
                print(f"    Guilds bot is in: {[f'{g.name} ({g.id})' for g in client.guilds]}")
                await client.close()
                return

            print(f"\n{'='*60}")
            print(f"SERVER INSPECTION REPORT")
            print(f"{'='*60}")
            
            # Server info
            report['server'] = {
                'name': guild.name,
                'id': guild.id,
                'owner_id': guild.owner_id,
                'member_count': guild.member_count,
                'created_at': str(guild.created_at),
                'description': guild.description,
                'icon': str(guild.icon) if guild.icon else None,
                'banner': str(guild.banner) if guild.banner else None,
                'premium_tier': guild.premium_tier,
                'premium_subscription_count': guild.premium_subscription_count,
            }
            print(f"\n📋 Server: {guild.name}")
            print(f"   ID: {guild.id}")
            print(f"   Owner ID: {guild.owner_id}")
            print(f"   Members: {guild.member_count}")
            print(f"   Created: {guild.created_at}")
            print(f"   Description: {guild.description}")
            print(f"   Boost Tier: {guild.premium_tier}")
            print(f"   Boosts: {guild.premium_subscription_count}")

            # Bot's member object and permissions
            me = guild.me
            print(f"\n🤖 Bot Member:")
            print(f"   Nick: {me.nick}")
            print(f"   Top Role: {me.top_role.name} (pos: {me.top_role.position})")
            print(f"   Guild Permissions: {me.guild_permissions.value}")
            
            perms = me.guild_permissions
            perm_list = []
            for perm, value in perms:
                if value:
                    perm_list.append(perm)
            print(f"   Granted Permissions: {', '.join(perm_list)}")
            
            important_perms = ['manage_guild', 'manage_channels', 'manage_roles', 
                             'send_messages', 'read_messages', 'attach_files',
                             'manage_messages', 'view_channel', 'administrator']
            missing = [p for p in important_perms if p not in perm_list]
            if missing:
                print(f"   ⚠️  Missing Important Perms: {', '.join(missing)}")
            else:
                print(f"   ✅ All important permissions present")

            report['bot_permissions'] = perm_list
            report['bot_missing_perms'] = missing

            # Roles
            print(f"\n🎭 Roles ({len(guild.roles)}):")
            report['roles'] = []
            for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
                role_info = {
                    'name': role.name,
                    'id': role.id,
                    'position': role.position,
                    'color': str(role.color),
                    'is_bot_managed': role.is_bot_managed(),
                    'is_default': role.is_default(),
                    'mentionable': role.mentionable,
                    'permissions_value': role.permissions.value,
                }
                report['roles'].append(role_info)
                marker = " 🤖" if role.is_bot_managed() else ""
                print(f"   [{role.position:02d}] {role.name} (ID: {role.id}) color={role.color}{marker}")

            # Categories and Channels
            print(f"\n📂 Categories & Channels:")
            report['categories'] = []
            report['channels'] = []
            
            # Uncategorized channels first
            uncategorized = [c for c in guild.channels if c.category is None and not isinstance(c, discord.CategoryChannel)]
            if uncategorized:
                print(f"   📁 [No Category]")
                for ch in sorted(uncategorized, key=lambda c: c.position):
                    ch_type = type(ch).__name__
                    print(f"      {'#' if isinstance(ch, discord.TextChannel) else '🔊'} {ch.name} (ID: {ch.id}, type={ch_type}, pos={ch.position})")
                    report['channels'].append({
                        'name': ch.name,
                        'id': ch.id,
                        'type': ch_type,
                        'category': None,
                        'position': ch.position,
                    })

            for category in sorted(guild.categories, key=lambda c: c.position):
                cat_info = {
                    'name': category.name,
                    'id': category.id,
                    'position': category.position,
                    'channels': [],
                }
                print(f"   📁 {category.name} (ID: {category.id}, pos={category.position})")
                
                for ch in sorted(category.channels, key=lambda c: c.position):
                    ch_type = type(ch).__name__
                    prefix = '#' if isinstance(ch, discord.TextChannel) else '🔊'
                    print(f"      {prefix} {ch.name} (ID: {ch.id}, type={ch_type}, pos={ch.position})")
                    ch_info = {
                        'name': ch.name,
                        'id': ch.id,
                        'type': ch_type,
                        'category': category.name,
                        'category_id': category.id,
                        'position': ch.position,
                    }
                    cat_info['channels'].append(ch_info)
                    report['channels'].append(ch_info)
                
                report['categories'].append(cat_info)

            # Channel permission overwrites for all channels
            print(f"\n🔒 Channel Permission Overwrites (non-default):")
            for ch in guild.channels:
                overwrites = ch.overwrites
                if overwrites:
                    print(f"   #{ch.name}:")
                    for target, overwrite in overwrites.items():
                        allow, deny = overwrite.pair()
                        target_name = target.name if hasattr(target, 'name') else str(target)
                        target_type = "Role" if isinstance(target, discord.Role) else "Member"
                        if allow.value > 0 or deny.value > 0:
                            print(f"      {target_type}: {target_name} — allow={allow.value}, deny={deny.value}")

            # System channel
            print(f"\n⚙️ Server Settings:")
            print(f"   System Channel: {guild.system_channel.name if guild.system_channel else 'None'}")
            print(f"   Rules Channel: {guild.rules_channel.name if guild.rules_channel else 'None'}")
            print(f"   AFK Channel: {guild.afk_channel.name if guild.afk_channel else 'None'}")
            print(f"   AFK Timeout: {guild.afk_timeout}s")
            print(f"   Verification Level: {guild.verification_level}")
            print(f"   Explicit Content Filter: {guild.explicit_content_filter}")
            print(f"   Default Notifications: {guild.default_notifications}")

            # Save report
            report_path = ROOT / "scratch" / "vault_server_inspection.json"
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, default=str)
            print(f"\n📄 Full report saved to: {report_path}")

        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
        finally:
            await client.close()

    await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(inspect())
