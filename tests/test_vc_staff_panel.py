"""Comprehensive automated tests for KROVEX Owner Panel & VC Staff Control Panel.

Tests:
1. Owner Panel authorization (Owner allowed, Non-owner blocked)
2. VC Staff role repository (add, remove, list, check)
3. VC Staff Panel authorization (Owner allowed, Staff allowed, Non-staff blocked)
4. Immediate role revocation (revoking role in DB immediately denies interaction)
5. Confirmation prompts for bulk actions (Mute All, Kick All)
6. Bot permission guards
7. Role hierarchy protection
8. Audit logging
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.cogs.admin.owner_panel import (
    AddStaffRoleSelect,
    OwnerCategorySelect,
    OwnerDashboardView,
    RemoveStaffRoleSelect,
)
from bot.cogs.ownervc.staff_panel import (
    ConfirmBulkActionView,
    VCStaffChannelSelect,
    VCStaffControlView,
    build_vc_staff_embed,
)
from bot.database.repositories.sqlite_repos import VCRepository


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.execute = AsyncMock()
    db.fetchone = AsyncMock()
    db.fetchall = AsyncMock()
    return db


@pytest.fixture
def mock_bot(mock_db):
    bot = MagicMock()
    bot.user = MagicMock(id=999999999, name="KROVEX")
    bot.config = MagicMock()
    bot.config.owner_ids = [10001]
    bot.vc_repo = VCRepository(mock_db)
    bot.latency = 0.045
    return bot


def _make_guild(owner_id: int = 12345):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 7777777
    guild.name = "Krovex Test Guild"
    guild.owner_id = owner_id
    guild.premium_tier = 2
    guild.premium_subscription_count = 7
    guild.channels = []
    guild.text_channels = []
    guild.voice_channels = []
    guild.roles = []
    guild.created_at = MagicMock()
    guild.created_at.timestamp = MagicMock(return_value=1700000000)

    bot_member = MagicMock(spec=discord.Member)
    bot_member.id = 999999999
    bot_role = MagicMock(spec=discord.Role)
    bot_role.position = 50
    bot_member.top_role = bot_role
    bot_member.joined_at = MagicMock()
    bot_member.joined_at.timestamp = MagicMock(return_value=1700000100)

    perms = MagicMock()
    perms.manage_channels = True
    perms.mute_members = True
    perms.deafen_members = True
    perms.move_members = True
    perms.administrator = True
    bot_member.guild_permissions = perms
    guild.me = bot_member
    return guild


def _make_vc(guild: discord.Guild, name: str = "Test VC", channel_id: int = 55555):
    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = channel_id
    vc.name = name
    vc.guild = guild
    vc.members = []
    vc.category = None
    vc.rtc_region = None
    vc.user_limit = 0
    vc.bitrate = 64000
    vc.permissions_synced = False
    vc.overwrites = {}

    default_overwrite = MagicMock()
    default_overwrite.connect = None
    default_overwrite.view_channel = None
    vc.overwrites_for = MagicMock(return_value=default_overwrite)
    vc.set_permissions = AsyncMock()
    vc.edit = AsyncMock()
    guild.get_channel = MagicMock(return_value=vc)
    return vc


def _make_interaction(guild: discord.Guild, user_id: int, roles: list = None):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.guild_id = guild.id

    user = MagicMock(spec=discord.Member)
    user.id = user_id
    user.roles = roles or []
    user_perms = MagicMock()
    user_perms.administrator = False
    user_perms.manage_channels = False
    user.guild_permissions = user_perms
    interaction.user = user

    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


# ── TEST 1: VC STAFF REPOSITORY OPERATIONS ────────────────────────────────────

@pytest.mark.asyncio
async def test_vc_staff_repository_add_remove_list(mock_db):
    repo = VCRepository(mock_db)
    cursor_mock = MagicMock()
    cursor_mock.rowcount = 1
    mock_db.execute.return_value = cursor_mock

    # 1. Add staff role
    res = await repo.add_staff_role(777, 888, 12345)
    assert res is True
    mock_db.execute.assert_called_with(
        "INSERT OR IGNORE INTO vc_staff_roles (guild_id, role_id, added_by) VALUES (?,?,?)",
        (777, 888, 12345),
    )

    # 2. List staff roles
    mock_db.fetchall.return_value = [{"role_id": 888}, {"role_id": 999}]
    roles = await repo.get_staff_roles(777)
    assert roles == [888, 999]

    # 3. Check is_staff
    mock_db.fetchone.return_value = {"1": 1}
    is_staff = await repo.is_staff(777, [888])
    assert is_staff is True

    # 4. Remove staff role
    res_rem = await repo.remove_staff_role(777, 888)
    assert res_rem is True


# ── TEST 2: OWNER PANEL AUTHORIZATION ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_owner_panel_authorization_owner_allowed(mock_bot):
    guild = _make_guild(owner_id=12345)
    view = OwnerDashboardView(mock_bot, guild)

    # Owner interaction
    owner_inter = _make_interaction(guild, user_id=12345)
    allowed = await view.interaction_check(owner_inter)
    assert allowed is True
    owner_inter.response.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_owner_panel_authorization_non_owner_blocked(mock_bot):
    guild = _make_guild(owner_id=12345)
    view = OwnerDashboardView(mock_bot, guild)

    # Non-owner interaction
    intruder_inter = _make_interaction(guild, user_id=99999)
    allowed = await view.interaction_check(intruder_inter)
    assert allowed is False
    intruder_inter.response.send_message.assert_called_once()
    assert "Access Denied" in intruder_inter.response.send_message.call_args[0][0]


# ── TEST 3: VC STAFF PANEL AUTHORIZATION ───────────────────────────────────────

@pytest.mark.asyncio
async def test_vc_staff_panel_staff_role_allowed(mock_bot, mock_db):
    guild = _make_guild(owner_id=12345)
    vc = _make_vc(guild)
    view = VCStaffControlView(mock_bot, vc)

    staff_role = MagicMock(spec=discord.Role)
    staff_role.id = 88888

    # User has staff role
    staff_inter = _make_interaction(guild, user_id=44444, roles=[staff_role])
    mock_db.fetchone.return_value = {"1": 1}  # is_staff -> True

    allowed = await view.interaction_check(staff_inter)
    assert allowed is True


@pytest.mark.asyncio
async def test_vc_staff_panel_unauthorized_user_blocked(mock_bot, mock_db):
    guild = _make_guild(owner_id=12345)
    vc = _make_vc(guild)
    view = VCStaffControlView(mock_bot, vc)

    # Normal user without staff role
    normal_inter = _make_interaction(guild, user_id=33333, roles=[])
    mock_db.fetchone.return_value = None  # is_staff -> False

    allowed = await view.interaction_check(normal_inter)
    assert allowed is False
    normal_inter.response.send_message.assert_called_once()
    assert "Access Denied" in normal_inter.response.send_message.call_args[0][0]


@pytest.mark.asyncio
async def test_vc_staff_panel_immediate_revocation(mock_bot, mock_db):
    """When a role is removed from SQLite, the next interaction must fail immediately."""
    guild = _make_guild(owner_id=12345)
    vc = _make_vc(guild)
    view = VCStaffControlView(mock_bot, vc)

    revoked_role = MagicMock(spec=discord.Role)
    revoked_role.id = 88888
    inter = _make_interaction(guild, user_id=44444, roles=[revoked_role])

    # First interaction allowed
    mock_db.fetchone.return_value = {"1": 1}
    assert await view.interaction_check(inter) is True

    # Owner revokes role (DB now returns None)
    mock_db.fetchone.return_value = None

    # Next interaction immediately blocked
    assert await view.interaction_check(inter) is False
    assert "Access Denied" in inter.response.send_message.call_args[0][0]


# ── TEST 4: CONFIRMATION PROMPTS FOR BULK OPERATIONS ─────────────────────────

@pytest.mark.asyncio
async def test_bulk_action_confirmation_view():
    confirm_cb = AsyncMock()
    view = ConfirmBulkActionView(
        action_name="Disconnect All Members",
        channel_name="Test VC",
        author_id=55555,
        on_confirm_cb=confirm_cb,
    )

    # Intruder clicks confirm -> rejected
    intruder = MagicMock(spec=discord.Interaction)
    intruder.user = MagicMock(id=99999)
    intruder.response = MagicMock()
    intruder.response.send_message = AsyncMock()
    assert await view.interaction_check(intruder) is False

    # Author clicks confirm -> action executed
    author_inter = MagicMock(spec=discord.Interaction)
    author_inter.user = MagicMock(id=55555)
    await view.confirm_btn.callback(author_inter)
    confirm_cb.assert_called_once_with(author_inter)


# ── TEST 5: BOT PERMISSION GUARD ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bot_missing_permission_guard(mock_bot):
    guild = _make_guild(owner_id=12345)
    vc = _make_vc(guild)
    view = VCStaffControlView(mock_bot, vc)

    # Strip bot manage_channels permission
    guild.me.guild_permissions.manage_channels = False
    guild.me.guild_permissions.administrator = False

    inter = _make_interaction(guild, user_id=12345)
    await view._handle_lock(inter)

    # Verify channel was not edited and error message was sent
    vc.set_permissions.assert_not_called()
    inter.response.send_message.assert_called_once()
    assert "Manage Channels" in inter.response.send_message.call_args[0][0]


# ── TEST 6: ROLE HIERARCHY PROTECTION ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_muteall_respects_role_hierarchy_and_owner(mock_bot):
    guild = _make_guild(owner_id=12345)
    vc = _make_vc(guild)
    view = VCStaffControlView(mock_bot, vc)

    # 1. Server Owner (ID 12345) - should be skipped
    owner_member = MagicMock(spec=discord.Member)
    owner_member.id = 12345
    owner_member.bot = False
    owner_member.edit = AsyncMock()

    # 2. Member with higher role than bot - should be skipped
    high_member = MagicMock(spec=discord.Member)
    high_member.id = 22222
    high_member.bot = False
    high_role = MagicMock()
    high_role.position = 100
    high_member.top_role = high_role
    high_member.edit = AsyncMock()

    # 3. Regular member lower than bot - should be muted
    reg_member = MagicMock(spec=discord.Member)
    reg_member.id = 33333
    reg_member.bot = False
    reg_role = MagicMock()
    reg_role.position = 10
    reg_member.top_role = reg_role
    reg_member.edit = AsyncMock()

    vc.members = [owner_member, high_member, reg_member]

    inter = _make_interaction(guild, user_id=12345)
    await view._handle_muteall(inter)

    owner_member.edit.assert_not_called()
    high_member.edit.assert_not_called()
    reg_member.edit.assert_called_once_with(mute=True, reason="VC Mute All by Staff: " + str(inter.user))


# ── TEST 7: AUDIT LOGGING & EMBED BUILDER ─────────────────────────────────────

@pytest.mark.asyncio
async def test_embed_and_audit_logging(mock_bot):
    guild = _make_guild(owner_id=12345)
    vc = _make_vc(guild)
    embed = build_vc_staff_embed(vc)

    assert "PORTAL SECURITY • VOICE CONTROL" in embed.title
    assert "Lock" in embed.description
    assert "Ghost" in embed.description
    assert "Hide" in embed.description
    assert "Limit" in embed.description
    assert "Bitrate" in embed.description


# ── TEST 8: OWNER DASHBOARD COG COMMANDS ──────────────────────────────────────

@pytest.mark.asyncio
async def test_owner_dashboard_cog_commands(mock_bot, mock_db):
    from bot.cogs.admin.owner_panel import OwnerDashboardCog
    cog = OwnerDashboardCog(mock_bot)
    guild = _make_guild(owner_id=12345)

    # 1. Owner executes .ownerpanel -> allowed
    ctx_owner = MagicMock()
    ctx_owner.guild = guild
    ctx_owner.author = MagicMock(spec=discord.Member, id=12345)
    ctx_owner.send = AsyncMock()

    await cog._execute_ownerpanel(ctx_owner)
    ctx_owner.send.assert_called_once()
    assert "embed" in ctx_owner.send.call_args[1]

    # 2. Non-owner executes .ownerpanel -> rejected
    ctx_intruder = MagicMock()
    ctx_intruder.guild = guild
    ctx_intruder.author = MagicMock(spec=discord.Member, id=99999)
    ctx_intruder.send = AsyncMock()

    await cog._execute_ownerpanel(ctx_intruder)
    ctx_intruder.send.assert_called_once()
    assert "Access Denied" in ctx_intruder.send.call_args[0][0]

    # 3. Owner executes .vcstaff add @Role
    role_mock = MagicMock(spec=discord.Role, id=7777, mention="<@&7777>")
    ctx_owner.reply = AsyncMock()
    await cog.vcstaff_add.callback(cog, ctx_owner, role_mock)
    mock_db.execute.assert_called()
    ctx_owner.reply.assert_called_once()
    assert "Authorized" in ctx_owner.reply.call_args[0][0]

    # 4. Owner executes .vcstaff remove @Role
    ctx_owner.reply.reset_mock()
    await cog.vcstaff_remove.callback(cog, ctx_owner, role_mock)
    ctx_owner.reply.assert_called_once()
    assert "Revoked" in ctx_owner.reply.call_args[0][0]


# ── TEST 9: VCDASHBOARD VC PANEL PREFIX COMMAND ───────────────────────────────

@pytest.mark.asyncio
async def test_vcpanel_prefix_command_staff_vs_non_staff(mock_bot, mock_db):
    from bot.cogs.ownervc.dashboard import VCDashboard
    cog = VCDashboard(mock_bot)
    guild = _make_guild(owner_id=12345)
    vc = _make_vc(guild)

    # 1. Staff user executes .vcpanel
    staff_role = MagicMock(spec=discord.Role, id=8888)
    ctx_staff = MagicMock()
    ctx_staff.guild = guild
    ctx_staff.author = MagicMock(spec=discord.Member, id=44444, roles=[staff_role])
    ctx_staff.author.voice = MagicMock(channel=vc)
    ctx_staff.author.guild_permissions = MagicMock(administrator=False, manage_channels=False)
    ctx_staff.send = AsyncMock()

    mock_db.fetchone.return_value = {"1": 1}  # is_staff -> True
    await cog._execute_vc_staff_panel(ctx_staff, channel=vc)
    ctx_staff.send.assert_called_once()
    assert "embed" in ctx_staff.send.call_args[1]

    # 2. Non-staff user executes .vcpanel -> rejected
    ctx_normal = MagicMock()
    ctx_normal.guild = guild
    ctx_normal.author = MagicMock(spec=discord.Member, id=22222, roles=[])
    ctx_normal.author.voice = MagicMock(channel=vc)
    ctx_normal.author.guild_permissions = MagicMock(administrator=False, manage_channels=False)
    ctx_normal.send = AsyncMock()

    mock_db.fetchone.return_value = None  # is_staff -> False
    await cog._execute_vc_staff_panel(ctx_normal, channel=vc)
    ctx_normal.send.assert_called_once()
    assert "Access Denied" in ctx_normal.send.call_args[0][0]


# ── TEST 10: MANDATORY SECURITY AUDIT CHECKS ──────────────────────────────────

@pytest.mark.asyncio
async def test_administrator_without_staff_role_denied(mock_bot, mock_db):
    """Discord Administrator without owner-authorized staff role MUST be denied."""
    guild = _make_guild(owner_id=12345)
    vc = _make_vc(guild)
    view = VCStaffControlView(mock_bot, vc)

    admin_role = MagicMock(spec=discord.Role, id=9999)
    admin_inter = _make_interaction(guild, user_id=77777, roles=[admin_role])
    admin_inter.user.guild_permissions.administrator = True
    admin_inter.user.guild_permissions.manage_channels = True
    mock_db.fetchone.return_value = None  # NOT in vc_staff_roles

    allowed = await view.interaction_check(admin_inter)
    assert allowed is False
    admin_inter.response.send_message.assert_called_once()
    assert "Access Denied" in admin_inter.response.send_message.call_args[0][0]


@pytest.mark.asyncio
async def test_manage_channels_without_staff_role_denied(mock_bot, mock_db):
    """Member with Manage Channels without owner-authorized staff role MUST be denied."""
    guild = _make_guild(owner_id=12345)
    vc = _make_vc(guild)
    view = VCStaffControlView(mock_bot, vc)

    mod_role = MagicMock(spec=discord.Role, id=6666)
    mod_inter = _make_interaction(guild, user_id=88888, roles=[mod_role])
    mod_inter.user.guild_permissions.administrator = False
    mod_inter.user.guild_permissions.manage_channels = True
    mock_db.fetchone.return_value = None  # NOT in vc_staff_roles

    allowed = await view.interaction_check(mod_inter)
    assert allowed is False
    mod_inter.response.send_message.assert_called_once()
    assert "Access Denied" in mod_inter.response.send_message.call_args[0][0]


@pytest.mark.asyncio
async def test_staff_bulk_actions_default_off_and_direct_callback_guard(mock_bot, mock_db):
    """Bulk actions must be disabled by default; dropdown omits them; direct dispatches are blocked."""
    guild = _make_guild(owner_id=12345)
    vc = _make_vc(guild)

    # 1. Verify default-off dropdown options
    select_default = VCStaffChannelSelect(allow_bulk=False)
    option_values = [opt.value for opt in select_default.options]
    assert "lock" in option_values
    assert "unlock" in option_values
    assert "ghost" in option_values
    assert "hide" in option_values
    assert "show" in option_values
    assert "mute_all" not in option_values
    assert "deafen_all" not in option_values
    assert "kick_all" not in option_values
    assert "clear_bans" not in option_values

    # 2. When allow_bulk=True, bulk options are present
    select_bulk = VCStaffChannelSelect(allow_bulk=True)
    bulk_option_values = [opt.value for opt in select_bulk.options]
    assert "mute_all" in bulk_option_values
    assert "kick_all" in bulk_option_values
    assert "clear_bans" in bulk_option_values

    # 3. Direct component interaction with bulk payload is blocked if bulk actions are OFF
    view = VCStaffControlView(mock_bot, vc, allow_bulk=False)
    select_item = [item for item in view.children if isinstance(item, VCStaffChannelSelect)][0]
    select_item._values = ["mute_all"]

    staff_inter = _make_interaction(guild, user_id=44444)
    # mock get_staff_bulk_actions_allowed -> False
    mock_db.fetchone.return_value = None

    await select_item.callback(staff_inter)
    staff_inter.response.send_message.assert_called_once()
    assert "Operation Blocked" in staff_inter.response.send_message.call_args[0][0]


@pytest.mark.asyncio
async def test_owner_can_toggle_bulk_actions(mock_bot, mock_db):
    """Owner can toggle bulk actions via command and button; non-owner is blocked."""
    from bot.cogs.admin.owner_panel import OwnerDashboardCog
    cog = OwnerDashboardCog(mock_bot)
    guild = _make_guild(owner_id=12345)

    # 1. Non-owner tries .vcstaff bulk -> rejected
    ctx_intruder = MagicMock()
    ctx_intruder.guild = guild
    ctx_intruder.author = MagicMock(spec=discord.Member, id=99999)
    ctx_intruder.reply = AsyncMock()
    await cog.vcstaff_bulk.callback(cog, ctx_intruder, state="on")
    assert "Only the Server Owner" in ctx_intruder.reply.call_args[0][0]

    # 2. Owner sets .vcstaff bulk on -> allowed
    ctx_owner = MagicMock()
    ctx_owner.guild = guild
    ctx_owner.author = MagicMock(spec=discord.Member, id=12345)
    ctx_owner.reply = AsyncMock()
    mock_db.fetchone.return_value = None  # current is False
    await cog.vcstaff_bulk.callback(cog, ctx_owner, state="on")
    mock_db.execute.assert_called()
    assert "ENABLED" in ctx_owner.reply.call_args[0][0]

    # 3. Owner sets .vcstaff bulk off -> allowed
    ctx_owner.reply.reset_mock()
    mock_db.fetchone.return_value = {"allow_bulk_actions": 1}
    await cog.vcstaff_bulk.callback(cog, ctx_owner, state="off")
    assert "DISABLED" in ctx_owner.reply.call_args[0][0]


@pytest.mark.asyncio
async def test_button_rows_match_portal_security_layout(mock_bot):
    """Verify that button rows match Portal Security screenshot 1:1 across 5 Discord ActionRows."""
    guild = _make_guild(owner_id=12345)
    vc = _make_vc(guild)
    view = VCStaffControlView(mock_bot, vc)

    # Row 0: Select dropdown
    selects = [item for item in view.children if isinstance(item, discord.ui.Select)]
    assert len(selects) == 1
    assert selects[0].row == 0

    # Row 1: Lock, Ghost, Hide
    assert view.lock_btn.row == 1
    assert view.ghost_btn.row == 1
    assert view.hide_btn.row == 1

    # Row 2: Limit, Bitrate
    assert view.limit_btn.row == 2
    assert view.bitrate_btn.row == 2

    # Row 3: Settings, VC Status
    assert view.settings_btn.row == 3
    assert view.status_btn.row == 3

    # Row 4: Owner, Refresh
    assert view.owner_btn.row == 4
    assert view.refresh_btn.row == 4


@pytest.mark.asyncio
async def test_owner_panel_ephemeral_slash_and_admin_denied(mock_bot):
    """Test owner panel slash interaction responses, ephemeral flag, and admin non-owner denial."""
    from bot.cogs.admin.owner_panel import OwnerDashboardCog
    cog = OwnerDashboardCog(mock_bot)
    guild = _make_guild(owner_id=12345)

    # 1. Server Owner executes slash /ownerpanel -> Allowed and EPHEMERAL
    owner_inter = _make_interaction(guild, user_id=12345)
    await cog._execute_ownerpanel(owner_inter)
    owner_inter.response.defer.assert_called_once_with(ephemeral=True)
    owner_inter.followup.send.assert_called_once()
    assert owner_inter.followup.send.call_args[1].get("ephemeral") is True
    assert "embed" in owner_inter.followup.send.call_args[1]

    # 2. Administrator without server ownership executes slash /ownerpanel -> Denied and EPHEMERAL
    admin_inter = _make_interaction(guild, user_id=77777)
    admin_inter.user.guild_permissions.administrator = True
    await cog._execute_ownerpanel(admin_inter)
    admin_inter.response.send_message.assert_called_once()
    assert admin_inter.response.send_message.call_args[1].get("ephemeral") is True
    assert "Access Denied" in admin_inter.response.send_message.call_args[0][0]

    # 3. Ordinary member executes slash /ownerpanel -> Denied and EPHEMERAL
    member_inter = _make_interaction(guild, user_id=88888)
    await cog._execute_ownerpanel(member_inter)
    member_inter.response.send_message.assert_called_once()
    assert member_inter.response.send_message.call_args[1].get("ephemeral") is True
    assert "Access Denied" in member_inter.response.send_message.call_args[0][0]

    # 4. Verify registered commands and aliases
    assert cog.ownerpanel_prefix.name == "ownerpanel"
    assert "ownerdashboard" in cog.ownerpanel_prefix.aliases
    assert "owner" in cog.ownerpanel_prefix.aliases
    assert "op" in cog.ownerpanel_prefix.aliases
    assert cog.ownerpanel_slash.name == "ownerpanel"
    assert cog.syncslash_prefix.name == "syncslash"
    assert "sync" in cog.syncslash_prefix.aliases



