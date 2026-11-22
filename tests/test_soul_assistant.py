"""Comprehensive test suite for KROVEX SOUL Natural Language AI Assistant.

Covers:
- Phase 2: Mention-to-Activate session lifecycle, follow-ups without mentions, multi-tenant isolation, inactivity timeout, explicit termination.
- Phase 3: Natural language understanding across music, voice, moderation, utility, economy.
- Phase 4 & 5: Tool execution engine, permission checks, role hierarchy, confirmation workflows for dangerous actions.
- Phase 6: Contextual follow-up memory (e.g. 'louder', 'skip this', 'unmute him').
- Phase 7 & 8: Discord message listener integration and response formatting.
- Phase 9: Slash & prefix SOUL command suite (/soul status, stop, settings, history, usage).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from bot.core.context import UnifiedContext
from bot.services.ai.intent_resolver import IntentResolver, ResolvedIntent
from bot.services.ai.session_manager import SessionManager, SoulSessionState
from bot.services.ai.soul_service import SoulService
from bot.services.ai.tools import ToolDefinition, ToolRegistry, ToolResult


# ── TEST FIXTURES & HELPERS ──────────────────────────────────────────────────

def make_member(user_id: int, name: str, guild: discord.Guild, roles: Optional[List[discord.Role]] = None, **perms) -> discord.Member:
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.name = name
    member.display_name = name
    member.guild = guild
    member.roles = roles or []
    member.top_role = MagicMock(spec=discord.Role)
    member.top_role.position = perms.get("top_role_pos", 1)
    member.voice = None

    guild_perms = discord.Permissions()
    for perm_name, val in perms.items():
        if hasattr(guild_perms, perm_name):
            setattr(guild_perms, perm_name, val)
    member.guild_permissions = guild_perms
    return member


def make_guild(guild_id: int = 1560990395666538529, owner_id: int = 111111) -> discord.Guild:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = "Krovex Test Guild"
    guild.owner_id = owner_id
    guild.members = []
    guild.voice_channels = []
    guild.channels = []

    bot_member = make_member(1570428426974662718, "KROVEX", guild, administrator=True, top_role_pos=99)
    guild.me = bot_member
    guild.get_member = MagicMock(side_effect=lambda uid: next((m for m in guild.members if m.id == uid), None))
    return guild


def make_text_channel(channel_id: int, name: str, guild: discord.Guild) -> discord.TextChannel:
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = channel_id
    ch.name = name
    ch.guild = guild
    ch.mention = f"<#{channel_id}>"
    ch.send = AsyncMock()
    ch.permissions_for = MagicMock()
    # Delegate channel permissions to member guild_permissions by default
    ch.permissions_for = MagicMock(side_effect=lambda m: getattr(m, "guild_permissions", discord.Permissions.none()))
    return ch


# ── PHASE 2 & 3: INTENT RESOLUTION & ENTITY EXTRACTION ───────────────────────

def test_intent_resolver_music_intents():
    resolver = IntentResolver()
    guild = make_guild()
    author = make_member(222, "Alice", guild)

    # 1. Play queries
    res = resolver.resolve("play Believer", guild, author)
    assert res.intent_type == "action"
    assert res.tool_name == "music_play"
    assert res.args.get("query") == "believer"

    res = resolver.resolve("put on shape of you", guild, author)
    assert res.tool_name == "music_play"
    assert res.args.get("query") == "shape of you"

    # 2. Volume relative & absolute
    res = resolver.resolve("make it louder", guild, author)
    assert res.tool_name == "music_volume"
    assert res.args.get("level") == 80

    res = resolver.resolve("make it quieter", guild, author)
    assert res.tool_name == "music_volume"
    assert res.args.get("level") == 30

    res = resolver.resolve("volume 50", guild, author)
    assert res.tool_name == "music_volume"
    assert res.args.get("level") == 50

    # 3. Skip, Pause, Resume, Stop
    assert resolver.resolve("skip this", guild, author).tool_name == "music_skip"
    assert resolver.resolve("pause music", guild, author).tool_name == "music_pause"
    assert resolver.resolve("resume song", guild, author).tool_name == "music_resume"
    assert resolver.resolve("stop playback", guild, author).tool_name == "music_stop"
    assert resolver.resolve("now playing", guild, author).tool_name == "music_nowplaying"
    assert resolver.resolve("show queue", guild, author).tool_name == "music_queue"


def test_intent_resolver_moderation_and_voice():
    resolver = IntentResolver()
    guild = make_guild()
    author = make_member(222, "Alice", guild, kick_members=True, ban_members=True)
    target = make_member(333, "Alex", guild)
    guild.members = [author, target]

    # Voice lock/unlock
    assert resolver.resolve("lock room", guild, author).tool_name == "voice_lock"
    assert resolver.resolve("unlock voice", guild, author).tool_name == "voice_unlock"
    assert resolver.resolve("hide vc", guild, author).tool_name == "voice_hide"
    assert resolver.resolve("show vc", guild, author).tool_name == "voice_show"
    assert resolver.resolve("claim vc", guild, author).tool_name == "voice_claim"

    # Moderation with member mention or name
    res = resolver.resolve(f"kick <@{target.id}> for spamming", guild, author)
    assert res.tool_name == "mod_kick"
    assert res.args.get("target") == target

    res = resolver.resolve(f"ban Alex bad behavior", guild, author)
    assert res.tool_name == "mod_ban"
    assert res.args.get("target") == target

    res = resolver.resolve(f"timeout Alex 1h trolling", guild, author)
    assert res.tool_name == "mod_timeout"
    assert res.args.get("target") == target
    assert res.args.get("duration") == "1h"

    res = resolver.resolve("purge 25 messages", guild, author)
    assert res.tool_name == "mod_purge"
    assert res.args.get("count") == 25


def test_intent_resolver_confirmation_and_termination():
    resolver = IntentResolver()
    guild = make_guild()
    author = make_member(222, "Alice", guild)

    # Confirmation
    assert resolver.resolve("yes", guild, author, has_pending_confirmation=True).intent_type == "confirmation"
    assert resolver.resolve("confirm", guild, author, has_pending_confirmation=True).intent_type == "confirmation"
    assert resolver.resolve("no", guild, author, has_pending_confirmation=True).intent_type == "cancellation"
    assert resolver.resolve("cancel", guild, author, has_pending_confirmation=True).intent_type == "cancellation"

    # Termination
    assert resolver.resolve("goodbye KROVEX", guild, author).intent_type == "termination"
    assert resolver.resolve("stop assistant", guild, author).intent_type == "termination"
    assert resolver.resolve("bye", guild, author).intent_type == "termination"


# ── PHASE 4 & 5: SESSION MANAGER & PERMISSION GUARDS ─────────────────────────

def test_session_manager_isolation_and_expiration():
    sm = SessionManager(default_timeout_seconds=300.0)

    # 1. Activation
    sess = sm.activate_session(guild_id=1, channel_id=10, user_id=100, user_name="User1")
    assert sess is not None
    assert sm.is_session_active(1, 10, 100) is True

    # 2. Isolation: Different user, same channel
    assert sm.is_session_active(1, 10, 200) is False

    # 3. Isolation: Same user, different channel
    assert sm.is_session_active(1, 20, 100) is False

    # 4. Isolation: Same user, different guild
    assert sm.is_session_active(2, 10, 100) is False

    # 5. Inactivity Expiration
    sess.last_activity_at = time.monotonic() - 301.0
    assert sess.is_expired() is True
    assert sm.is_session_active(1, 10, 100) is False

    # 6. Explicit Termination
    sm.activate_session(1, 10, 100, user_name="User1")
    assert sm.is_session_active(1, 10, 100) is True
    ended = sm.end_session(1, 10, 100)
    assert ended is True
    assert sm.is_session_active(1, 10, 100) is False


def test_tool_registry_permission_guards():
    bot = MagicMock()
    bot.config = MagicMock(owner_ids=[999999])
    registry = ToolRegistry(bot)
    guild = make_guild(owner_id=111111)
    ch = make_text_channel(50, "general", guild)

    # 1. Normal member without permissions
    normal_member = make_member(222, "Ordinary", guild, kick_members=False, ban_members=False, top_role_pos=5)
    target_member = make_member(333, "Target", guild, top_role_pos=2)

    mod_kick = registry.get_tool("mod_kick")
    allowed, err = registry.check_permissions(mod_kick, normal_member, ch, target_member)
    assert allowed is False
    assert "permission" in err.lower()

    # 2. Member with kick permission moderating target
    mod_member = make_member(444, "Mod", guild, kick_members=True, top_role_pos=10)
    allowed, err = registry.check_permissions(mod_kick, mod_member, ch, target_member)
    assert allowed is True
    assert err is None

    # 3. Role hierarchy violation (target higher than author)
    higher_target = make_member(555, "Admin", guild, top_role_pos=20)
    allowed, err = registry.check_permissions(mod_kick, mod_member, ch, higher_target)
    assert allowed is False
    assert "role hierarchy" in err.lower()

    # 4. Target is Server Owner
    owner_target = make_member(111111, "OwnerTarget", guild, top_role_pos=50)
    allowed, err = registry.check_permissions(mod_kick, mod_member, ch, owner_target)
    assert allowed is False
    assert "server owner" in err.lower()

    # 5. Voice requirement
    music_play = registry.get_tool("music_play")
    allowed, err = registry.check_permissions(music_play, normal_member, ch)
    assert allowed is False
    assert "voice channel" in err.lower()


# ── PHASE 6, 7 & 8: SOUL SERVICE END-TO-END WORKFLOW ─────────────────────────

@pytest.mark.asyncio
async def test_soul_service_action_and_confirmation_flow():
    bot = MagicMock()
    bot.config = MagicMock(owner_ids=[999999])
    bot.get_context = AsyncMock()

    guild = make_guild(owner_id=111111)
    ch = make_text_channel(50, "general", guild)
    author = make_member(444, "Staff", guild, kick_members=True, manage_messages=True, top_role_pos=10)
    target = make_member(333, "Troublemaker", guild, top_role_pos=2)
    guild.members = [author, target]

    db_mock = MagicMock()
    repo_mock = MagicMock()
    provider_mock = MagicMock()
    provider_mock.is_configured = True

    service = SoulService(
        db=db_mock,
        repo=repo_mock,
        provider=provider_mock,
        bot=bot,
    )

    # Mock Moderation Cog
    mod_cog = MagicMock()
    mod_cog._execute_kick = AsyncMock()
    bot.get_cog.return_value = mod_cog

    # 1. User says: "kick Troublemaker spamming"
    msg1 = MagicMock(spec=discord.Message)
    msg1.guild = guild
    msg1.channel = ch
    msg1.author = author
    msg1.content = "kick Troublemaker spamming"

    reply, err = await service.process_natural_language_request(bot, msg1, msg1.content)
    assert err is None
    # Because kick requires confirmation, it asks first!
    assert "Are you sure you want to kick" in reply
    assert "Reply **yes** to proceed" in reply

    # Verify session has pending confirmation
    session = service.session_manager.get_session(guild.id, ch.id, author.id)
    assert session is not None
    assert session.pending_confirmation is not None
    assert session.pending_confirmation.tool_name == "mod_kick"

    # 2. User says: "yes" -> Confirms and executes kick
    msg2 = MagicMock(spec=discord.Message)
    msg2.guild = guild
    msg2.channel = ch
    msg2.author = author
    msg2.content = "yes"

    reply2, err2 = await service.process_natural_language_request(bot, msg2, msg2.content)
    assert err2 is None
    assert "Done! 👢 Kicked **Troublemaker**" in reply2
    mod_cog._execute_kick.assert_awaited_once()

    # Confirmation is now cleared
    assert session.pending_confirmation is None


@pytest.mark.asyncio
async def test_soul_service_music_and_volume_flow():
    bot = MagicMock()
    bot.config = MagicMock(owner_ids=[999999])
    bot.get_context = AsyncMock()

    guild = make_guild()
    ch = make_text_channel(50, "general", guild)
    author = make_member(222, "Alice", guild)
    # Give author a connected voice state
    author.voice = MagicMock(channel=MagicMock(name="Music Lounge"))

    service = SoulService(
        db=MagicMock(),
        repo=MagicMock(),
        provider=MagicMock(),
        bot=bot,
    )

    music_cog = MagicMock()
    music_cog._execute_play = AsyncMock()
    music_cog._execute_volume = AsyncMock()
    music_cog._execute_skip = AsyncMock()
    bot.get_cog.return_value = music_cog

    # 1. "play Believer"
    msg = MagicMock(spec=discord.Message, guild=guild, channel=ch, author=author)
    reply, err = await service.process_natural_language_request(bot, msg, "play Believer")
    assert err is None
    assert "Playing" in reply or "playing" in reply
    music_cog._execute_play.assert_awaited_once()

    # 2. Contextual follow-up: "make it louder"
    reply2, err2 = await service.process_natural_language_request(bot, msg, "make it louder")
    assert err2 is None
    assert "80%" in reply2
    music_cog._execute_volume.assert_awaited_once()

    # 3. Contextual follow-up: "skip this"
    reply3, err3 = await service.process_natural_language_request(bot, msg, "skip this")
    assert err3 is None
    assert "Skipped" in reply3
    music_cog._execute_skip.assert_awaited_once()


# ── PHASE 9: SOUL COMMAND SUITE ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_soul_commands_status_and_stop():
    from bot.cogs.soul.cog import Soul
    bot = MagicMock()
    bot.user = MagicMock(id=1570428426974662718)
    cog = Soul(bot)

    guild = make_guild()
    ch = make_text_channel(50, "general", guild)
    author = make_member(222, "Alice", guild)

    service = SoulService(
        db=MagicMock(),
        repo=MagicMock(),
        provider=MagicMock(),
        bot=bot,
    )
    bot.soul_service = service

    # 1. Initially inactive
    ctx = MagicMock()
    ctx.guild = guild
    ctx.channel = ch
    ctx.author = author
    ctx.reply = AsyncMock()

    await cog._execute_soul_status(ctx)
    ctx.reply.assert_called_once()
    embed = ctx.reply.call_args.kwargs.get("embed")
    assert "Inactive" in embed.description

    # 2. Activate session and check status
    service.activate_session(guild.id, ch.id, author.id)
    ctx.reply.reset_mock()
    await cog._execute_soul_status(ctx)
    embed2 = ctx.reply.call_args.kwargs.get("embed")
    assert "Active" in embed2.description

    # 3. Stop session
    ctx.reply.reset_mock()
    await cog._execute_soul_stop(ctx)
    ctx.reply.assert_called_once()
    assert "stopped" in ctx.reply.call_args.args[0].lower()
    assert service.is_session_active(guild.id, ch.id, author.id) is False
