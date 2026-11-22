import socket
_orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

import asyncio
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath("."))
load_dotenv("F:/Death Bot/.env")

import discord
from bot.core.bot import DeathBot
from bot.config import BotConfig
from bot.database.sqlite_manager import SQLiteDatabaseManager

async def test_phase5():
    tmp_dir = tempfile.mkdtemp()
    db = SQLiteDatabaseManager(db_path=Path(tmp_dir) / "test.sqlite")
    await db.connect()

    cfg = BotConfig.from_env(validate=False)
    bot = DeathBot(config=cfg)
    bot.db_manager = db
    bot._init_database = AsyncMock()

    # Load services & cogs
    await bot.load_extension("bot.services.security_service")
    await bot.load_extension("bot.services.automod_service")
    await bot.load_extension("bot.services.dm_queue_service")
    await bot.load_extension("bot.services.logging_service")
    await bot.load_extension("bot.services.mention_service")
    await bot.load_extension("bot.services.bot_role_service")
    await bot.load_cogs()

    print("\n--- 1. Testing /util invite Execution ---")
    util_cog = bot.get_cog("Utility")
    assert util_cog is not None, "Utility cog not found"

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.original_response = AsyncMock()

    # Find invite slash command
    util_group = next(c for c in bot.tree.get_commands() if c.name == "util")
    invite_cmd = next(c for c in util_group.commands if c.name == "invite")
    
    # Run callback
    await invite_cmd.callback(util_cog, interaction)
    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args[1]
    embed = kwargs.get("embed") or (kwargs.get("embeds")[0] if kwargs.get("embeds") else None)
    assert embed is not None, "Embed should not be None"
    assert "KROVEX" in embed.title or "KROVEX" in embed.description
    print("  [PASS] /util invite ran without error! Title:", embed.title)
    
    # Check invite URL in embed description
    print("  [PASS] Embed Description snippet:", embed.description[:120])
    assert "1570428426974662718" in embed.description
    assert "scope=bot%20applications.commands" in embed.description or "scope=bot+applications.commands" in embed.description or "bot" in embed.description

    print("\n--- 2. Testing Owner Authorization Guard ---")
    owner_cog = bot.get_cog("Owner Dashboard") or bot.get_cog("OwnerDashboardCog")
    assert owner_cog is not None, "OwnerDashboardCog not found"

    guild = MagicMock(spec=discord.Guild, id=1560990395666538529, owner_id=111111)
    
    # Unauthorized member test
    unauth_interaction = MagicMock(spec=discord.Interaction)
    unauth_interaction.guild = guild
    unauth_interaction.user = MagicMock(spec=discord.Member, id=999999)
    unauth_interaction.response = MagicMock()
    unauth_interaction.response.is_done.return_value = False
    unauth_interaction.response.send_message = AsyncMock()
    unauth_interaction.followup = MagicMock()
    unauth_interaction.followup.send = AsyncMock()
    unauth_interaction.original_response = AsyncMock()
    
    ownerpanel_cmd = next(c for c in bot.tree.get_commands() if c.name == "ownerpanel")
    await ownerpanel_cmd.callback(owner_cog, unauth_interaction)
    unauth_interaction.response.send_message.assert_called_once()
    kwargs_unauth = unauth_interaction.response.send_message.call_args[1]
    msg = kwargs_unauth.get("content") or ""
    if not msg and unauth_interaction.response.send_message.call_args[0]:
        msg = unauth_interaction.response.send_message.call_args[0][0]
    assert "Access Denied" in msg or "Sovereign" in msg or "Owner" in msg
    print("  [PASS] /ownerpanel correctly blocked unauthorized user: ", msg[:60], "...")

    # Authorized server owner test
    auth_interaction = MagicMock(spec=discord.Interaction)
    auth_interaction.guild = guild
    auth_interaction.user = MagicMock(spec=discord.Member, id=111111)
    auth_interaction.response = MagicMock()
    auth_interaction.response.is_done.return_value = False
    auth_interaction.response.send_message = AsyncMock()
    auth_interaction.followup = MagicMock()
    auth_interaction.followup.send = AsyncMock()
    auth_interaction.original_response = AsyncMock()
    await ownerpanel_cmd.callback(owner_cog, auth_interaction)
    auth_interaction.response.send_message.assert_called_once()
    kwargs_auth = auth_interaction.response.send_message.call_args[1]
    auth_embed = kwargs_auth.get("embed") or (kwargs_auth.get("embeds")[0] if kwargs_auth.get("embeds") else None)
    assert auth_embed is not None
    print("  [PASS] /ownerpanel allowed server owner!")

    print("\n--- 3. Testing .vcpanel Prefix Command ---")
    vc_dash = bot.get_cog("VCDashboard")
    assert vc_dash is not None, "VCDashboard cog not found"
    
    # Prefix command .vcpanel unauthorized test
    ctx_unauth = MagicMock(spec=discord.ext.commands.Context)
    ctx_unauth.guild = guild
    ctx_unauth.author = MagicMock(spec=discord.Member, id=999999)
    ctx_unauth.send = AsyncMock()
    vc_channel = MagicMock(spec=discord.VoiceChannel, guild=guild, name="General", members=[], user_limit=0, bitrate=64000)
    vc_channel.overwrites_for.return_value = MagicMock(connect=True, view_channel=True)
    await vc_dash.vcpanel_prefix(ctx_unauth, channel=vc_channel)
    ctx_unauth.send.assert_called_once()
    assert "Access Denied" in ctx_unauth.send.call_args[0][0]
    print("  [PASS] .vcpanel blocked unauthorized non-owner!")

    # Prefix command .vcpanel authorized owner test
    ctx_auth = MagicMock(spec=discord.ext.commands.Context)
    ctx_auth.guild = guild
    ctx_auth.author = MagicMock(spec=discord.Member, id=111111)
    ctx_auth.send = AsyncMock()
    await vc_dash.vcpanel_prefix(ctx_auth, channel=vc_channel)
    ctx_auth.send.assert_called_once()
    vc_embed = ctx_auth.send.call_args[1]["embed"]
    assert "Owner VCPANEL" in vc_embed.title
    print("  [PASS] .vcpanel allowed server owner with Title:", vc_embed.title)

    if bot.http:
        await bot.http.close()

    print("\nALL PHASE 5 CHECKS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(test_phase5())
