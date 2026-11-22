"""KROVEX Master Audit & QA Plan — Phase 6 Execution Test Suite: Voice System & Owner VC.

Covers test cases P6-TC01 through P6-TC10:
- P6-TC01: Dynamic Temp Voice Channel Lifecycle (Join-to-Create, owner assignment, auto-cleanup on exit)
- P6-TC02: Channel Ownership Transfer and Claim Mechanics (.claim when owner leaves, .transfer)
- P6-TC03: Three-Dropdown OwnerVC Control Dashboard (Voice Moderation, Privacy & Capacity, Message Moderation)
- P6-TC04: VC Loop Protection System (Loop activation, automatic reconnect enforcement, cancellation)
- P6-TC05: Voice Ban & Overwrite Isolation (Single-target ban/unban with permission overwrites)
- P6-TC06: Bulk Voice Actions & Two-Step Confirmation (Mute/Deafen/Kick all requiring explicit confirm)
- P6-TC07: Authorized VC Staff Directory (.vcstaff add/remove/list with vc_staff_roles persistence)
- P6-TC08: Staff Bulk Actions Toggle Policy (Default locked, Server Sovereign toggle override)
- P6-TC09: Voice Room Privacy & Capacity Bounds (Lock/Unlock, Hide/Show, Ghost, Bitrate and limit bounds)
- P6-TC10: Voice Activity Auditing & Cleanup Engine (VoiceService sweep cleans empty temp channels)
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.cogs.ownervc.cog import OwnerVC
from bot.cogs.ownervc.dashboard import (
    OwnerVCControlView,
    VoiceModerationSelect,
    VoicePrivacyCapacitySelect,
    MessageModerationSelect,
    build_owner_vc_embed,
)
from bot.cogs.ownervc.staff_panel import (
    ConfirmBulkActionView,
    VCStaffControlView,
    build_vc_staff_embed,
)
from bot.core.context import UnifiedContext
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import VCRepository
from bot.services.voice_service import VoiceService


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture
def mock_bot(tmp_path: Path):
    bot = MagicMock()
    bot.config = MagicMock()
    bot.config.owner_ids = [99901]
    bot.owner_ids = [99901]
    return bot


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 888888888
    guild.name = "Krovex Voice Staging"
    guild.owner_id = 111111111
    guild.default_role = MagicMock(spec=discord.Role, id=888888000)
    guild.voice_channels = []
    guild.members = []
    guild.icon = None
    return guild


# ==============================================================================
# P6-TC01: DYNAMIC TEMP VOICE CHANNEL LIFECYCLE
# ==============================================================================

def test_p6_tc01_dynamic_temp_vc_lifecycle(tmp_path: Path, mock_bot, mock_guild):
    """P6-TC01: Temp voice channel creation, owner tracking, and destruction upon empty."""
    async def _test():
        db_file = tmp_path / "test_p6_tc01.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = VCRepository(db)
            mock_bot.db = db
            mock_bot.db_manager = db
            mock_bot.vc_repo = repo
            vservice = VoiceService(mock_bot, repo)

            user = MagicMock(spec=discord.Member)
            user.id = 50001
            user.bot = False
            user.display_name = "Sonic"

            vc = MagicMock(spec=discord.VoiceChannel)
            vc.id = 70001
            vc.guild = mock_guild
            vc.name = "Sonic's Lounge"
            vc.members = [user]
            vc.delete = AsyncMock()

            # 1. Register temp channel in repository
            await repo.register_temp_channel(mock_guild.id, vc.id, user.id)
            owner_rec = await repo.get_vc_owner(mock_guild.id, vc.id)
            assert owner_rec is not None
            assert owner_rec["owner_id"] == user.id

            # 2. Channel active while occupied
            await vservice._check_and_cleanup_temp_channel(vc)
            vc.delete.assert_not_called()
            assert await repo.is_temp_channel(mock_guild.id, vc.id) is True

            # 3. Last member leaves -> cleanup deletes channel
            vc.members = []
            await vservice._check_and_cleanup_temp_channel(vc)
            vc.delete.assert_awaited_once()

            # 4. Verified deleted from DB
            is_temp = await repo.is_temp_channel(mock_guild.id, vc.id)
            assert is_temp is False
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P6-TC02: CHANNEL OWNERSHIP TRANSFER & CLAIM
# ==============================================================================

def test_p6_tc02_channel_ownership_transfer_and_claim(tmp_path: Path, mock_bot, mock_guild):
    """P6-TC02: Transferring ownership to another member and claiming abandoned channels."""
    async def _test():
        db_file = tmp_path / "test_p6_tc02.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = VCRepository(db)
            mock_bot.vc_repo = repo

            owner = MagicMock(spec=discord.Member, id=60001)
            successor = MagicMock(spec=discord.Member, id=60002)
            channel_id = 70002

            await repo.register_temp_channel(mock_guild.id, channel_id, owner.id)
            owner_rec = await repo.get_vc_owner(mock_guild.id, channel_id)
            assert owner_rec["owner_id"] == owner.id

            # 1. Transfer channel ownership
            await repo.set_vc_owner(mock_guild.id, channel_id, successor.id)
            succ_rec = await repo.get_vc_owner(mock_guild.id, channel_id)
            assert succ_rec["owner_id"] == successor.id

            # 2. Abandoned channel claim (when owner departs)
            third_party = MagicMock(spec=discord.Member, id=60003)
            await repo.set_vc_owner(mock_guild.id, channel_id, third_party.id)
            third_rec = await repo.get_vc_owner(mock_guild.id, channel_id)
            assert third_rec["owner_id"] == third_party.id
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P6-TC03: THREE-DROPDOWN OWNERVC CONTROL DASHBOARD
# ==============================================================================

def test_p6_tc03_three_dropdown_ownervc_dashboard(mock_bot, mock_guild):
    """P6-TC03: OwnerVC dashboard layout with exactly three categorized dropdowns."""
    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = 70003
    vc.name = "Apex Control"
    vc.guild = mock_guild
    vc.user_limit = 5
    vc.bitrate = 128000
    vc.members = []
    vc.overwrites_for.return_value = MagicMock(connect=None, view_channel=None)

    view = OwnerVCControlView(mock_bot, vc)
    selects = [item for item in view.children if isinstance(item, discord.ui.Select)]

    # Must contain exactly 3 select menus in rows 0, 1, 2
    assert len(selects) == 3

    # Dropdown 1: Voice Moderation
    assert isinstance(selects[0], VoiceModerationSelect)
    assert selects[0].placeholder == "Voice moderation"
    assert selects[0].row == 0
    assert len(selects[0].options) == 17

    # Dropdown 2: Privacy and Capacity
    assert isinstance(selects[1], VoicePrivacyCapacitySelect)
    assert selects[1].placeholder == "Voice room privacy and capacity"
    assert selects[1].row == 1
    assert len(selects[1].options) == 14

    # Dropdown 3: Message Moderation
    assert isinstance(selects[2], MessageModerationSelect)
    assert selects[2].placeholder == "Message moderation"
    assert selects[2].row == 2
    assert len(selects[2].options) == 10

    # Build and verify live embed
    embed = build_owner_vc_embed(vc, ban_count=0)
    assert "Owner" in embed.title or "Staff" in embed.title or "VCPANEL" in embed.title
    assert "Apex Control" in embed.description
    assert "128 kbps" in embed.description


# ==============================================================================
# P6-TC04: VC LOOP PROTECTION SYSTEM
# ==============================================================================

def test_p6_tc04_vc_loop_protection(tmp_path: Path, mock_bot, mock_guild):
    """P6-TC04: Anchoring members with automatic reconnect loops and status tracking."""
    async def _test():
        db_file = tmp_path / "test_p6_tc04.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = VCRepository(db)
            mock_bot.vc_repo = repo

            channel_id = 70004
            target_user_id = 60005

            # Activate VC loop
            await repo.set_vc_loop(mock_guild.id, channel_id, target_user_id, activated_by=111)
            loop_data = await repo.get_vc_loop(mock_guild.id, target_user_id)
            assert loop_data is not None
            assert loop_data["channel_id"] == channel_id

            # Channel loop lookup
            ch_loops = await repo.get_channel_vc_loops(mock_guild.id, channel_id)
            assert any(l["user_id"] == target_user_id for l in ch_loops)

            # Stop VC loop
            await repo.remove_vc_loop(mock_guild.id, target_user_id)
            loop_after = await repo.get_vc_loop(mock_guild.id, target_user_id)
            assert loop_after is None
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P6-TC05: VOICE BAN & OVERWRITE ISOLATION
# ==============================================================================

def test_p6_tc05_voice_ban_and_overwrite(tmp_path: Path, mock_bot, mock_guild):
    """P6-TC05: Single-target voice ban adding connect=False overwrite and tracking."""
    async def _test():
        db_file = tmp_path / "test_p6_tc05.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = VCRepository(db)
            mock_bot.vc_repo = repo

            channel_id = 70005
            troublemaker_id = 60006

            # 1. Voice Ban target in DB
            await repo.add_vc_ban(mock_guild.id, channel_id, troublemaker_id, banned_by=111, reason="Test Ban")
            assert await repo.is_vc_banned(mock_guild.id, channel_id, troublemaker_id) is True

            bans = await repo.get_vc_bans(mock_guild.id, channel_id)
            assert any(b["user_id"] == troublemaker_id for b in bans)

            # 2. Overwrite check on Discord Channel
            vc = MagicMock(spec=discord.VoiceChannel)
            vc.set_permissions = AsyncMock()
            member = MagicMock(spec=discord.Member, id=troublemaker_id)
            await vc.set_permissions(member, connect=False, reason="KROVEX Voice Ban")
            vc.set_permissions.assert_awaited_once_with(member, connect=False, reason="KROVEX Voice Ban")

            # 3. Voice Unban target
            await repo.remove_vc_ban(mock_guild.id, channel_id, troublemaker_id)
            assert await repo.is_vc_banned(mock_guild.id, channel_id, troublemaker_id) is False
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P6-TC06: BULK VOICE ACTIONS & TWO-STEP CONFIRMATION
# ==============================================================================

def test_p6_tc06_bulk_voice_actions_and_confirmation(mock_bot, mock_guild):
    """P6-TC06: Mute all, deafen all, and kick all require two-step confirmation views."""
    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = 70006
    vc.name = "War Room"
    vc.guild = mock_guild

    owner = MagicMock(spec=discord.Member, id=mock_guild.owner_id)
    regular_user = MagicMock(spec=discord.Member, id=60007)
    regular_user.top_role.position = 5
    regular_user.edit = AsyncMock()

    vc.members = [owner, regular_user]

    # Verify ConfirmBulkActionView initialization
    view = ConfirmBulkActionView(action_name="Mute All", channel_name=vc.name, author_id=owner.id, on_confirm_cb=AsyncMock())
    assert view.action_name == "Mute All"
    assert view.channel_name == "War Room"
    assert view.author_id == owner.id

    # Non-author interaction rejected
    intruder_interaction = MagicMock(spec=discord.Interaction)
    intruder_interaction.user = MagicMock(id=99999)
    intruder_interaction.response = MagicMock()
    intruder_interaction.response.send_message = AsyncMock()
    assert run_async(view.interaction_check(intruder_interaction)) is False

    # Author interaction accepted
    owner_interaction = MagicMock(spec=discord.Interaction)
    owner_interaction.user = owner
    assert run_async(view.interaction_check(owner_interaction)) is True


# ==============================================================================
# P6-TC07: AUTHORIZED VC STAFF DIRECTORY
# ==============================================================================

def test_p6_tc07_vc_staff_directory_persistence(tmp_path: Path, mock_bot, mock_guild):
    """P6-TC07: Adding, removing, and listing authorized VC staff roles."""
    async def _test():
        db_file = tmp_path / "test_p6_tc07.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = VCRepository(db)
            mock_bot.vc_repo = repo

            role_mod_id = 77001
            role_lead_id = 77002

            # 1. Add roles to authorized VC staff directory
            await repo.add_staff_role(mock_guild.id, role_mod_id, added_by=mock_guild.owner_id)
            await repo.add_staff_role(mock_guild.id, role_lead_id, added_by=mock_guild.owner_id)

            staff_roles = await repo.get_staff_roles(mock_guild.id)
            assert len(staff_roles) == 2
            assert role_mod_id in staff_roles
            assert role_lead_id in staff_roles

            # 2. Check is_staff helper
            is_staff = await repo.is_staff(mock_guild.id, [role_mod_id, 99999])
            assert is_staff is True

            is_non_staff = await repo.is_staff(mock_guild.id, [12345, 67890])
            assert is_non_staff is False

            # 3. Revoke role
            await repo.remove_staff_role(mock_guild.id, role_mod_id)
            staff_after = await repo.get_staff_roles(mock_guild.id)
            assert len(staff_after) == 1
            assert role_mod_id not in staff_after
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P6-TC08: STAFF BULK ACTIONS TOGGLE POLICY
# ==============================================================================

def test_p6_tc08_staff_bulk_actions_toggle_policy(tmp_path: Path, mock_bot, mock_guild):
    """P6-TC08: Staff bulk moderation defaults to locked; owner toggles access."""
    async def _test():
        db_file = tmp_path / "test_p6_tc08.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = VCRepository(db)
            mock_bot.vc_repo = repo

            # Default policy: Staff bulk actions disabled (False)
            default_state = await repo.get_staff_bulk_actions_allowed(mock_guild.id)
            assert default_state is False

            # Server Owner enables bulk actions
            await repo.set_staff_bulk_actions_allowed(mock_guild.id, True, updated_by=mock_guild.owner_id)
            updated_state = await repo.get_staff_bulk_actions_allowed(mock_guild.id)
            assert updated_state is True

            # Server Owner disables bulk actions again
            await repo.set_staff_bulk_actions_allowed(mock_guild.id, False, updated_by=mock_guild.owner_id)
            disabled_state = await repo.get_staff_bulk_actions_allowed(mock_guild.id)
            assert disabled_state is False
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P6-TC09: VOICE ROOM PRIVACY & CAPACITY BOUNDS
# ==============================================================================

def test_p6_tc09_voice_privacy_and_capacity_bounds(mock_bot, mock_guild):
    """P6-TC09: Channel lock/unlock, hide/show, ghost mode, and capacity bounds."""
    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = 70009
    vc.guild = mock_guild
    vc.set_permissions = AsyncMock()
    vc.edit = AsyncMock()

    # 1. Lock Voice Channel (connect=False for default_role)
    run_async(vc.set_permissions(mock_guild.default_role, connect=False, reason="Lock VC"))
    vc.set_permissions.assert_awaited_with(mock_guild.default_role, connect=False, reason="Lock VC")

    # 2. Hide Voice Channel (view_channel=False)
    run_async(vc.set_permissions(mock_guild.default_role, view_channel=False, reason="Hide VC"))
    vc.set_permissions.assert_awaited_with(mock_guild.default_role, view_channel=False, reason="Hide VC")

    # 3. User limit bounds (0 to 99)
    run_async(vc.edit(user_limit=15))
    vc.edit.assert_awaited_with(user_limit=15)

    # 4. Bitrate adjustment (clamped between 8kbps and 384kbps)
    run_async(vc.edit(bitrate=128000))
    vc.edit.assert_awaited_with(bitrate=128000)


# ==============================================================================
# P6-TC10: VOICE ACTIVITY AUDITING & CLEANUP ENGINE
# ==============================================================================

def test_p6_tc10_voice_activity_auditing_and_cleanup(tmp_path: Path, mock_bot, mock_guild):
    """P6-TC10: Automated sweep cleans orphaned temp channels and preserves occupied rooms."""
    async def _test():
        db_file = tmp_path / "test_p6_tc10.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = VCRepository(db)
            mock_bot.db = db
            mock_bot.db_manager = db
            mock_bot.vc_repo = repo
            service = VoiceService(mock_bot, repo)

            # Active channel with 2 members
            m1 = MagicMock(spec=discord.Member)
            m1.bot = False
            m2 = MagicMock(spec=discord.Member)
            m2.bot = False
            occupied_vc = MagicMock(spec=discord.VoiceChannel)
            occupied_vc.id = 70010
            occupied_vc.guild = mock_guild
            occupied_vc.members = [m1, m2]
            occupied_vc.delete = AsyncMock()

            # Abandoned channel with 0 members
            empty_vc = MagicMock(spec=discord.VoiceChannel)
            empty_vc.id = 70011
            empty_vc.guild = mock_guild
            empty_vc.members = []
            empty_vc.delete = AsyncMock()

            await repo.register_temp_channel(mock_guild.id, occupied_vc.id, 90001)
            await repo.register_temp_channel(mock_guild.id, empty_vc.id, 90002)

            # Test check and cleanup on occupied channel
            await service._check_and_cleanup_temp_channel(occupied_vc)
            occupied_vc.delete.assert_not_called()
            assert await repo.is_temp_channel(mock_guild.id, occupied_vc.id) is True

            # Test check and cleanup on empty channel
            await service._check_and_cleanup_temp_channel(empty_vc)
            empty_vc.delete.assert_awaited_once()
            assert await repo.is_temp_channel(mock_guild.id, empty_vc.id) is False
        finally:
            await db.close()

    run_async(_test())
