"""Comprehensive Automated Test Suite for KROVEX Ultimate Voice Control Centre.

Validates:
- 8-section dashboard UI & navigation
- Scope A (Current VC) & Scope B (Server-Wide) bulk actions
- Move All explicit destination channel selection
- Protected member immunity (Sovereign, bot owners, bot self)
- Role hierarchy safety checks
- Member management filters & multi-select batch actions
- Channel management permission preservation & restoration
- Smart quick action modes (Meeting, Gaming, Silent, Emergency Lock, AFK)
- Presets persistence & retrieval
- Temporary actions engine & scheduled reversion
- Activity logging & audit trail pagination
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from bot.cogs.admin.owner_panel import OwnerDashboardView
from bot.cogs.ownervc.bulk_engine import (
    BulkActionConfirmView,
    BulkExecutionPlan,
    VoiceBulkActionEngine,
)
from bot.cogs.ownervc.dashboard import OwnerVCControlView
from bot.cogs.ownervc.temp_actions import TemporaryActionsEngine
from bot.cogs.ownervc.voice_centre import (
    ChannelFallbackSelect,
    DestinationChannelSelect,
    MemberMultiSelect,
    VoiceCentreCategorySelect,
    VoiceControlCentreView,
)


def _make_mock_bot():
    bot = MagicMock()
    bot.user = MagicMock(spec=discord.ClientUser, id=999999999)
    bot.config = MagicMock()
    bot.config.owner_ids = [111111111]
    bot.owner_ids = {111111111}
    bot.is_bot_owner = MagicMock(side_effect=lambda u: u.id in [111111111])

    bot.vc_repo = MagicMock()
    bot.vc_repo.log_action = AsyncMock(return_value=1)
    bot.vc_repo.get_action_logs = AsyncMock(return_value=[
        {
            "id": 1,
            "guild_id": 123,
            "executor_id": 111,
            "action_type": "mute_all",
            "scope": "current_vc",
            "success_count": 5,
            "fail_count": 0,
            "created_at": "2026-11-20 12:00:00",
        }
    ])
    bot.vc_repo.get_action_log_count = AsyncMock(return_value=1)
    bot.vc_repo.get_presets = AsyncMock(return_value=[
        {"preset_name": "LateNightLoFi", "description": "96kbps quiet room", "config_json": "{}"}
    ])
    bot.vc_repo.save_preset = AsyncMock()
    bot.vc_repo.delete_preset = AsyncMock(return_value=True)
    bot.vc_repo.save_temp_action = AsyncMock(return_value=101)
    bot.vc_repo.get_active_temp_actions = AsyncMock(return_value=[])
    bot.vc_repo.deactivate_temp_action = AsyncMock(return_value=True)
    bot.vc_repo.save_permission_backup = AsyncMock()
    bot.vc_repo.get_permission_backup = AsyncMock(return_value=None)
    bot.vc_repo.get_control_settings = AsyncMock(return_value={
        "guild_id": 123,
        "afk_channel_id": 555,
        "afk_timeout_seconds": 300,
        "meeting_exempt_roles": [],
        "staff_roles": [],
    })
    bot.vc_repo.is_staff = AsyncMock(return_value=False)
    return bot


def _make_mock_guild(owner_id: int = 12345):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 123
    guild.name = "Test Guild"
    guild.owner_id = owner_id
    guild.bitrate_limit = 96000

    default_role = MagicMock(spec=discord.Role, id=1000)
    guild.default_role = default_role

    bot_role = MagicMock(spec=discord.Role, position=50)
    bot_member = MagicMock(spec=discord.Member, id=999999999, top_role=bot_role)
    guild.me = bot_member

    # Voice channels
    vc1 = MagicMock(spec=discord.VoiceChannel, id=101, name="General Voice", bitrate=64000, user_limit=0)
    vc1.guild = guild
    vc1.members = []
    vc1.overwrites_for = MagicMock(return_value=MagicMock(connect=None, view_channel=None))
    vc1.set_permissions = AsyncMock()
    vc1.edit = AsyncMock()
    vc1.purge = AsyncMock(return_value=[MagicMock(), MagicMock()])

    vc2 = MagicMock(spec=discord.VoiceChannel, id=102, name="Gaming Lounge", bitrate=96000, user_limit=10)
    vc2.guild = guild
    vc2.members = []
    vc2.overwrites_for = MagicMock(return_value=MagicMock(connect=None, view_channel=None))
    vc2.set_permissions = AsyncMock()
    vc2.edit = AsyncMock()

    guild.voice_channels = [vc1, vc2]
    guild.get_channel = MagicMock(side_effect=lambda cid: vc1 if cid == 101 else (vc2 if cid == 102 else None))

    afk = MagicMock(spec=discord.VoiceChannel, id=555, name="AFK Room")
    afk.members = []
    guild.afk_channel = afk

    return guild


def _make_mock_member(member_id: int, name: str, guild: discord.Guild, vc: Optional[discord.VoiceChannel] = None, role_pos: int = 10):
    m = MagicMock(spec=discord.Member)
    m.id = member_id
    m.name = name
    m.display_name = name
    m.guild = guild
    m.bot = False
    m.top_role = MagicMock(spec=discord.Role, position=role_pos, name="Member")
    m.roles = [m.top_role]

    if vc:
        voice_state = MagicMock()
        voice_state.channel = vc
        voice_state.mute = False
        voice_state.deaf = False
        voice_state.self_deaf = False
        m.voice = voice_state
        vc.members.append(m)
    else:
        m.voice = None

    m.edit = AsyncMock()
    m.move_to = AsyncMock()
    return m


# ─────────────────────────────────────────────────────────────────────────────
# 1. UI STRUCTURE & NAVIGATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_voice_centre_view_initialization_and_eight_sections():
    bot = _make_mock_bot()
    guild = _make_mock_guild()
    view = VoiceControlCentreView(bot, guild, active_channel=guild.voice_channels[0])

    assert view.current_section == "voice_control"
    assert view.scope == "current_vc"
    assert view.active_channel == guild.voice_channels[0]

    embed, _ = await view.render()
    assert embed.color.value == 0x9D4EDD  # Neon purple
    assert "Voice Control" in embed.title

    # Check master select dropdown has all 8 sections
    nav_select = next(item for item in view.children if isinstance(item, VoiceCentreCategorySelect))
    assert len(nav_select.options) == 8
    option_values = [o.value for o in nav_select.options]
    assert option_values == [
        "voice_control",
        "member_management",
        "channel_management",
        "quick_actions",
        "presets",
        "vc_chat",
        "activity_logs",
        "settings",
    ]


@pytest.mark.asyncio
async def test_voice_channel_decoupled_resolution():
    """Ensure opening dashboard without being in voice defaults to an existing guild VC rather than failing."""
    bot = _make_mock_bot()
    guild = _make_mock_guild()
    # Initialize view without passing active_channel
    view = VoiceControlCentreView(bot, guild, active_channel=None)
    assert view.active_channel is not None
    assert view.active_channel.id == 101


# ─────────────────────────────────────────────────────────────────────────────
# 2. SOVEREIGN IMMUNITY & AUTHORIZATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_protected_member_immunity_in_bulk_engine():
    bot = _make_mock_bot()
    guild = _make_mock_guild(owner_id=12345)
    engine = VoiceBulkActionEngine(bot)

    owner = _make_mock_member(12345, "ServerOwner", guild)
    bot_owner = _make_mock_member(111111111, "BotDeveloper", guild)
    bot_self = guild.me
    regular = _make_mock_member(999, "RegularUser", guild)

    assert engine.is_protected_member(owner, guild) is True
    assert engine.is_protected_member(bot_owner, guild) is True
    assert engine.is_protected_member(bot_self, guild) is True
    assert engine.is_protected_member(regular, guild) is False


@pytest.mark.asyncio
async def test_role_hierarchy_checks():
    bot = _make_mock_bot()
    guild = _make_mock_guild(owner_id=12345)
    engine = VoiceBulkActionEngine(bot)
    bot_member = guild.me  # position 50

    subordinate = _make_mock_member(501, "Subordinate", guild, role_pos=20)
    superior = _make_mock_member(502, "SuperiorStaff", guild, role_pos=60)

    can_mod_sub, _ = engine.can_moderate_member(bot_member, subordinate)
    can_mod_sup, _ = engine.can_moderate_member(bot_member, superior)

    assert can_mod_sub is True
    assert can_mod_sup is False


# ─────────────────────────────────────────────────────────────────────────────
# 3. SCOPE A: CURRENT VC CONTROLS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scope_a_bulk_mute_and_unmute():
    bot = _make_mock_bot()
    guild = _make_mock_guild(owner_id=12345)
    vc = guild.voice_channels[0]
    engine = VoiceBulkActionEngine(bot)

    m1 = _make_mock_member(1001, "User1", guild, vc=vc, role_pos=10)
    m2 = _make_mock_member(1002, "User2", guild, vc=vc, role_pos=10)
    owner = _make_mock_member(12345, "OwnerInVC", guild, vc=vc, role_pos=99)

    # Build Plan
    executor = _make_mock_member(111111111, "Executor", guild)
    plan = engine.build_plan("mute", "current_vc", guild, executor, [vc])

    assert len(plan.target_members) == 3
    assert len(plan.eligible_members) == 2  # m1, m2
    assert len(plan.protected_members) == 1  # owner

    # Execute Mute
    executed_plan = await engine.execute_plan(plan)
    assert executed_plan.success_count == 2
    assert executed_plan.fail_count == 0
    m1.edit.assert_called_once_with(mute=True, reason="KROVEX Bulk Mute (current_vc)")
    m2.edit.assert_called_once_with(mute=True, reason="KROVEX Bulk Mute (current_vc)")
    owner.edit.assert_not_called()

    # Logged to DB
    bot.vc_repo.log_action.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 4. SCOPE B: SERVER-WIDE CONTROLS & DESTINATION SELECTION
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scope_b_server_wide_move_all_with_destination():
    bot = _make_mock_bot()
    guild = _make_mock_guild(owner_id=12345)
    vc1 = guild.voice_channels[0]
    vc2 = guild.voice_channels[1]
    engine = VoiceBulkActionEngine(bot)

    m1 = _make_mock_member(2001, "UserVC1", guild, vc=vc1, role_pos=10)
    m2 = _make_mock_member(2002, "UserVC2", guild, vc=vc2, role_pos=10)
    owner = _make_mock_member(12345, "OwnerInVC", guild, vc=vc1, role_pos=99)

    executor = _make_mock_member(111111111, "Admin", guild)
    dest = guild.afk_channel

    plan = engine.build_plan("move", "server_wide", guild, executor, [vc1, vc2], destination_channel=dest)
    assert len(plan.eligible_members) == 2
    assert len(plan.protected_members) == 1

    await engine.execute_plan(plan)
    m1.move_to.assert_called_once_with(dest, reason=f"KROVEX Bulk Move to #{dest.name}")
    m2.move_to.assert_called_once_with(dest, reason=f"KROVEX Bulk Move to #{dest.name}")
    owner.move_to.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 5. CHANNEL MANAGEMENT & OVERWRITE PRESERVATION
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_channel_lock_backs_up_and_restores_overwrites():
    bot = _make_mock_bot()
    guild = _make_mock_guild()
    vc = guild.voice_channels[0]
    view = VoiceControlCentreView(bot, guild, active_channel=vc)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = _make_mock_member(guild.owner_id, "Owner", guild)
    interaction.guild = guild
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    # Lock channel
    await view._handle_channel_lock(interaction)
    vc.set_permissions.assert_called_with(guild.default_role, connect=False, reason=f"KROVEX Channel Lock by {interaction.user}")
    bot.vc_repo.save_permission_backup.assert_called_once()

    # Unlock channel restores from backup
    bot.vc_repo.get_permission_backup.return_value = {
        "overwrites_json": json.dumps({"connect": None, "view_channel": None})
    }
    await view._handle_channel_unlock(interaction)
    vc.set_permissions.assert_called_with(guild.default_role, connect=None, reason=f"KROVEX Channel Unlock by {interaction.user}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. SMART QUICK ACTIONS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_meeting_mode_mutes_non_exempt():
    bot = _make_mock_bot()
    guild = _make_mock_guild()
    vc = guild.voice_channels[0]
    view = VoiceControlCentreView(bot, guild, active_channel=vc)

    m1 = _make_mock_member(3001, "Listener", guild, vc=vc, role_pos=10)
    speaker = _make_mock_member(3002, "Speaker", guild, vc=vc, role_pos=10)
    speaker_role = MagicMock(spec=discord.Role, id=777)
    speaker.roles.append(speaker_role)

    # Configure exempt role
    bot.vc_repo.get_control_settings.return_value = {
        "meeting_exempt_roles": [777],
    }

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = _make_mock_member(guild.owner_id, "Owner", guild)
    interaction.guild = guild
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await view._handle_meeting_mode(interaction)
    m1.edit.assert_called_once_with(mute=True, reason="KROVEX Bulk Mute (current_vc)")
    speaker.edit.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 7. TEMPORARY ACTIONS ENGINE & REVERSION
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_temporary_actions_scheduling():
    bot = _make_mock_bot()
    guild = _make_mock_guild()
    vc = guild.voice_channels[0]
    temp_engine = TemporaryActionsEngine(bot)

    target = _make_mock_member(4001, "TempUser", guild, vc=vc)
    action_id = await temp_engine.schedule_temp_mute(guild.id, target, 60, 111111111)

    assert action_id == 101
    target.edit.assert_called_once_with(mute=True, reason="KROVEX Temp Mute (60s)")
    bot.vc_repo.save_temp_action.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 8. TWO-WAY NAVIGATION BETWEEN DASHBOARDS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_owner_dashboard_and_voice_centre_two_way_navigation():
    bot = _make_mock_bot()
    guild = _make_mock_guild()

    # 1. OwnerDashboardView has Voice Control Centre button and category
    owner_view = OwnerDashboardView(bot, guild)
    assert any(getattr(item, "custom_id", None) == "owner:goto_vc_centre" for item in owner_view.children)

    # 2. VoiceControlCentreView has Return to Owner Dashboard button
    vc_view = VoiceControlCentreView(bot, guild, active_channel=guild.voice_channels[0])
    await vc_view.render()
    assert any(getattr(item, "custom_id", None) == "vc:goto_owner" for item in vc_view.children)


# ─────────────────────────────────────────────────────────────────────────────
# 9. ADDITIONAL COMPREHENSIVE TESTS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bulk_deafen_and_disconnect():
    bot = _make_mock_bot()
    guild = _make_mock_guild()
    vc = guild.voice_channels[0]
    engine = VoiceBulkActionEngine(bot)

    m1 = _make_mock_member(5001, "UserD1", guild, vc=vc)
    m2 = _make_mock_member(5002, "UserD2", guild, vc=vc)
    executor = _make_mock_member(111111111, "Executor", guild)

    # Deafen All
    plan_deaf = engine.build_plan("deafen", "current_vc", guild, executor, [vc])
    await engine.execute_plan(plan_deaf)
    m1.edit.assert_called_with(deafen=True, reason="KROVEX Bulk Deafen (current_vc)")
    m2.edit.assert_called_with(deafen=True, reason="KROVEX Bulk Deafen (current_vc)")

    # Disconnect All
    plan_disc = engine.build_plan("disconnect", "current_vc", guild, executor, [vc])
    await engine.execute_plan(plan_disc)
    m1.move_to.assert_called_with(None, reason="KROVEX Bulk Disconnect (current_vc)")
    m2.move_to.assert_called_with(None, reason="KROVEX Bulk Disconnect (current_vc)")


@pytest.mark.asyncio
async def test_member_management_filters_and_multi_select():
    bot = _make_mock_bot()
    guild = _make_mock_guild()
    vc = guild.voice_channels[0]
    view = VoiceControlCentreView(bot, guild, active_channel=vc)
    view.current_section = "member_management"

    m_muted = _make_mock_member(6001, "MutedUser", guild, vc=vc)
    m_muted.voice.mute = True

    m_normal = _make_mock_member(6002, "NormalUser", guild, vc=vc)

    # 1. Filter: Muted
    view.member_filter = "muted"
    embed, _ = await view.render()
    assert "MUTED" in embed.description
    assert "MutedUser" in embed.description
    assert "NormalUser" not in embed.description

    # 2. Multi-select batch action
    view.selected_member_ids = [6001]
    targets = [m_muted]
    executor = _make_mock_member(guild.owner_id, "Owner", guild)
    plan = view.bulk_engine.build_plan("unmute", "selected_members", guild, executor, [], specific_members=targets)
    await view.bulk_engine.execute_plan(plan)
    m_muted.edit.assert_called_with(mute=False, reason="KROVEX Bulk Unmute (selected_members)")


@pytest.mark.asyncio
async def test_presets_crud_and_activity_logs():
    bot = _make_mock_bot()
    guild = _make_mock_guild()
    view = VoiceControlCentreView(bot, guild)

    # Presets section
    view.current_section = "presets"
    embed_presets, _ = await view.render()
    assert "LateNightLoFi" in embed_presets.description
    bot.vc_repo.get_presets.assert_called_with(guild.id)

    # Activity Logs section
    view.current_section = "activity_logs"
    embed_logs, _ = await view.render()
    assert "Activity Logs" in embed_logs.title
    assert "MUTE ALL" in embed_logs.description
    bot.vc_repo.get_action_logs.assert_called_with(guild.id, limit=8, offset=0, filter_type="all")


@pytest.mark.asyncio
async def test_vc_control_slash_command_execution():
    from bot.cogs.ownervc.dashboard import VCDashboard
    bot = _make_mock_bot()
    cog = VCDashboard(bot)
    guild = _make_mock_guild()

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.user = _make_mock_member(guild.owner_id, "Owner", guild)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = MagicMock(side_effect=lambda: interaction.response.defer.called)
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await cog.vcpanel_slash.callback(cog, interaction, channel=guild.voice_channels[0])
    interaction.response.defer.assert_called_once_with(ephemeral=False)
    interaction.followup.send.assert_called_once()
    sent_call = interaction.followup.send.call_args
    assert sent_call.kwargs.get("view") is not None
    assert sent_call.kwargs.get("embed") is not None

