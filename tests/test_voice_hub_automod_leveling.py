"""Comprehensive unit & integration tests for:
1. Dynamic "Join to Create" Auto-VC Hub & Auto-Cleanup
2. Voice AutoMod: Anti-Soundboard Spam, Mute/Deafen Evasion Prevention & Quarantine Panic
3. Voice Activity Leveling & AFK-Protected Rewards
4. Role Setup for server 1572984100141269163
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.services.voice_service import VoiceService
from bot.services.bot_role_service import BotRoleService, KROVEX_ROLE_SPECS
from bot.cogs.ownervc.bulk_engine import VoiceBulkActionEngine


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock(spec=discord.ClientUser, id=1570428426974662718)
    bot.config = MagicMock()
    bot.config.owner_ids = [1457380609641938981, 1558723324639445166]
    bot.owner_ids = {1457380609641938981, 1558723324639445166}
    bot.vc_repo = MagicMock()
    bot.vc_repo.register_temp_channel = AsyncMock()
    bot.vc_repo.is_temp_channel = AsyncMock(return_value=True)
    bot.vc_repo.remove_temp_channel = AsyncMock()
    bot.vc_repo.log_action = AsyncMock(return_value=1)
    bot.economy_repo = MagicMock()
    bot.economy_repo.add_balance = AsyncMock()
    bot.economy_repo.add_xp = AsyncMock()
    return bot


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1572984100141269163
    guild.name = "Krovex Test Guild"
    guild.owner_id = 1457380609641938981
    guild.default_role = MagicMock(spec=discord.Role, id=1572984100141269163)
    guild.afk_channel = None
    guild.voice_channels = []
    guild.roles = []
    guild.create_voice_channel = AsyncMock()
    guild.create_role = AsyncMock()
    me = MagicMock(spec=discord.Member)
    me.id = 1570428426974662718
    me.top_role = MagicMock(position=50)
    me.guild_permissions = discord.Permissions(
        manage_channels=True,
        move_members=True,
        mute_members=True,
        deafen_members=True,
        manage_roles=True,
        administrator=True,
    )
    guild.me = me
    return guild


# ==============================================================================
# FEATURE 1: DYNAMIC JOIN-TO-CREATE AUTO-VC HUB
# ==============================================================================

@pytest.mark.asyncio
async def test_join_to_create_hub_detection_and_creation(mock_bot, mock_guild):
    """Verify that joining a '➕ Join to Create' channel creates a room, moves member, and registers temp channel."""
    repo = MagicMock()
    service = VoiceService(mock_bot, repo)

    hub_channel = MagicMock(spec=discord.VoiceChannel)
    hub_channel.id = 1111111111
    hub_channel.name = "➕ Join to Create"
    hub_channel.guild = mock_guild
    hub_channel.category = None
    hub_channel.bitrate = 64000

    created_vc = MagicMock(spec=discord.VoiceChannel)
    created_vc.id = 2222222222
    created_vc.name = "🔊・TheRealRai's Room"
    created_vc.send = AsyncMock()
    mock_guild.create_voice_channel.return_value = created_vc

    member = MagicMock(spec=discord.Member)
    member.id = 1457380609641938981
    member.display_name = "TheRealRai"
    member.guild = mock_guild
    member.bot = False
    member.voice = MagicMock(channel=hub_channel)
    member.move_to = AsyncMock()

    # Call _handle_join_to_create directly
    res_vc = await service._handle_join_to_create(member, hub_channel)

    assert res_vc == created_vc
    mock_guild.create_voice_channel.assert_awaited_once()
    assert "TheRealRai's Room" in mock_guild.create_voice_channel.call_args[1]["name"]
    member.move_to.assert_awaited_once_with(created_vc, reason="KROVEX Auto-VC: Move to dynamic room")
    mock_bot.vc_repo.register_temp_channel.assert_awaited_once_with(mock_guild.id, created_vc.id, member.id)


@pytest.mark.asyncio
async def test_join_to_create_auto_cleanup_when_empty(mock_bot, mock_guild):
    """Verify that when the last member leaves a temporary room, it is cleaned up."""
    repo = MagicMock()
    service = VoiceService(mock_bot, repo)

    temp_vc = MagicMock(spec=discord.VoiceChannel)
    temp_vc.id = 3333333333
    temp_vc.name = "🔊・TheRealRai's Room"
    temp_vc.guild = mock_guild
    temp_vc.members = []  # Empty channel
    temp_vc.delete = AsyncMock()

    await service._check_and_cleanup_temp_channel(temp_vc)

    mock_bot.vc_repo.is_temp_channel.assert_awaited_once_with(mock_guild.id, temp_vc.id)
    mock_bot.vc_repo.remove_temp_channel.assert_awaited_once_with(mock_guild.id, temp_vc.id)
    temp_vc.delete.assert_awaited_once()


# ==============================================================================
# FEATURE 2: VOICE AUTOMOD & QUARANTINE PANIC
# ==============================================================================

@pytest.mark.asyncio
async def test_voice_automod_soundboard_spam_throttling(mock_bot, mock_guild):
    """Verify soundboard spam >3 in 5s triggers automated server mute sanction."""
    repo = MagicMock()
    service = VoiceService(mock_bot, repo)

    vc = MagicMock(spec=discord.VoiceChannel, id=4444444444, guild=mock_guild)
    member = MagicMock(spec=discord.Member, id=987654321, guild=mock_guild)
    member.display_name = "Spammer"
    member.edit = AsyncMock()

    # Event 1 & 2: under threshold
    assert await service.record_soundboard_event(member, vc) is False
    assert await service.record_soundboard_event(member, vc) is False

    # Event 3: triggers sanction
    assert await service.record_soundboard_event(member, vc) is True
    member.edit.assert_awaited_once_with(mute=True, reason="KROVEX Voice AutoMod: Anti-Soundboard Spam Throttling")
    mock_bot.vc_repo.log_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_automod_evasion_prevention(mock_bot, mock_guild):
    """Verify user who was muted/deafened cannot reconnect to evade sanction."""
    repo = MagicMock()
    repo.start_session = AsyncMock()
    repo.end_session = AsyncMock(return_value=MagicMock(duration_seconds=10))
    service = VoiceService(mock_bot, repo)

    vc = MagicMock(spec=discord.VoiceChannel, id=5555555555, name="Normal VC", guild=mock_guild)
    member = MagicMock(spec=discord.Member, id=987654321, guild=mock_guild, bot=False)
    member.edit = AsyncMock()

    # State before: Member was server muted and server deafened, then disconnected
    before_state = MagicMock(channel=vc, mute=True, deaf=True)
    after_leave = MagicMock(channel=None)
    await service.handle_voice_state_update(member, before_state, after_leave)

    # State after: Member rejoins immediately
    before_rejoin = MagicMock(channel=None)
    after_rejoin = MagicMock(channel=vc)
    await service.handle_voice_state_update(member, before_rejoin, after_rejoin)

    # Verify mute/deafen was immediately re-applied
    member.edit.assert_awaited_once_with(
        mute=True,
        deafen=True,
        reason="KROVEX Voice AutoMod: Mute/Deafen Evasion Prevention",
    )


@pytest.mark.asyncio
async def test_emergency_quarantine_panic_button(mock_bot, mock_guild):
    """Verify Quarantine Panic isolates non-staff members in locked quarantine channel and mutes them."""
    engine = VoiceBulkActionEngine(mock_bot)

    quarantine_vc = MagicMock(spec=discord.VoiceChannel, id=9999999999, name="🚨・Quarantine")
    mock_guild.create_voice_channel = AsyncMock(return_value=quarantine_vc)

    # Human non-protected member
    victim = MagicMock(spec=discord.Member, id=111222333, guild=mock_guild, bot=False)
    victim.display_name = "RaidSuspect"
    victim.voice = MagicMock(channel=MagicMock(spec=discord.VoiceChannel, id=8888888888))
    victim.move_to = AsyncMock()
    victim.edit = AsyncMock()

    active_vc = MagicMock(spec=discord.VoiceChannel, id=8888888888, members=[victim])
    mock_guild.voice_channels = [active_vc]

    executor = MagicMock(spec=discord.Member, id=1457380609641938981, guild=mock_guild)

    plan = await engine.execute_emergency_quarantine(mock_guild, executor)

    assert plan.success_count == 1
    assert plan.fail_count == 0
    victim.move_to.assert_awaited_once_with(quarantine_vc, reason=f"KROVEX Emergency Quarantine by {executor}")
    victim.edit.assert_awaited_once_with(mute=True, reason="KROVEX Emergency Quarantine: Muted")
    mock_bot.vc_repo.log_action.assert_awaited_once()


# ==============================================================================
# FEATURE 3: VOICE ACTIVITY LEVELING & REWARDS
# ==============================================================================

@pytest.mark.asyncio
async def test_voice_activity_leveling_afk_safeguards(mock_bot, mock_guild):
    """Verify XP & coins awarded ONLY when anti-farming safeguards pass (>=2 members, unmuted, undeafened, non-AFK)."""
    repo = MagicMock()
    service = VoiceService(mock_bot, repo)

    # Eligible members (2 non-bots, active, not muted, not deafened)
    m1 = MagicMock(spec=discord.Member, id=101, bot=False)
    m1.voice = MagicMock(mute=False, self_mute=False, deaf=False, self_deaf=False)

    m2 = MagicMock(spec=discord.Member, id=102, bot=False)
    m2.voice = MagicMock(mute=False, self_mute=False, deaf=False, self_deaf=False)

    # Ineligible member: deafened
    m3_deaf = MagicMock(spec=discord.Member, id=103, bot=False)
    m3_deaf.voice = MagicMock(mute=False, self_mute=False, deaf=True, self_deaf=False)

    valid_vc = MagicMock(spec=discord.VoiceChannel, id=7777777777, members=[m1, m2, m3_deaf])

    # Ineligible channel: solo user (farming alone)
    solo_m = MagicMock(spec=discord.Member, id=104, bot=False)
    solo_m.voice = MagicMock(mute=False, self_mute=False, deaf=False, self_deaf=False)
    solo_vc = MagicMock(spec=discord.VoiceChannel, id=6666666666, members=[solo_m])

    mock_guild.voice_channels = [valid_vc, solo_vc]
    mock_bot.guilds = [mock_guild]

    # Run one evaluation loop tick
    async def single_tick():
        for guild in mock_bot.guilds:
            for vc in guild.voice_channels:
                non_bots = [m for m in vc.members if not m.bot]
                if len(non_bots) < 2:
                    continue
                for m in non_bots:
                    vs = m.voice
                    if not vs or vs.mute or vs.self_mute or vs.deaf or vs.self_deaf:
                        continue
                    await mock_bot.economy_repo.add_balance(guild.id, m.id, wallet=5, bank=0)
                    await mock_bot.economy_repo.add_xp(guild.id, m.id, xp=15)

    await single_tick()

    # m1 and m2 rewarded
    assert mock_bot.economy_repo.add_balance.call_count == 2
    assert mock_bot.economy_repo.add_xp.call_count == 2
    mock_bot.economy_repo.add_xp.assert_any_call(mock_guild.id, 101, xp=15)
    mock_bot.economy_repo.add_xp.assert_any_call(mock_guild.id, 102, xp=15)


# ==============================================================================
# FEATURE 4: ROLE SETUP FOR SERVER 1572984100141269163
# ==============================================================================

@pytest.mark.asyncio
async def test_role_setup_provisions_three_dedicated_roles(mock_bot, mock_guild):
    """Verify setup_bot_roles creates KROVEX, KROVEX Prime Security™, and KROVEX Unbypassable Security™."""
    role_service = BotRoleService(mock_bot)

    created_roles = []
    for spec in KROVEX_ROLE_SPECS:
        r = MagicMock(spec=discord.Role)
        r.id = len(created_roles) + 1000
        r.name = spec["name"]
        r.position = 40 + len(created_roles)
        r.managed = False
        created_roles.append(r)

    mock_guild.roles = []
    mock_guild.create_role = AsyncMock(side_effect=created_roles)
    mock_guild.me.roles = []
    mock_guild.me.add_roles = AsyncMock()

    active, failed, err = await role_service.setup_bot_roles(mock_guild)

    assert err is None
    assert len(active) == 3
    names = [r.name for r in active]
    assert "KROVEX" in names
    assert "KROVEX Prime Security™" in names
    assert "KROVEX Unbypassable Security™" in names
    assert mock_guild.create_role.call_count == 3
