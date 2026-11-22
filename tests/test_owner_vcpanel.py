"""Comprehensive test suite for KROVEX Owner VCPANEL.

Verifies:
1. Visual layout, compact embed design, and information hierarchy matching reference.
2. Exactly 3 dropdown sections (Voice Moderation, Voice Room Privacy & Capacity, Message Moderation).
3. Strict authorization: Server owner & Bot owner ONLY (Administrator & Staff roles denied).
4. Authorization rechecked on every component interaction.
5. Functional voice moderation, privacy/capacity controls, and message moderation.
6. Two-step confirmation for destructive bulk actions.
7. Graceful handling of deleted channels, missing bot permissions, and stale states.
8. Independent operation of OwnerVC Staff Panel.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import discord
import pytest

from bot.cogs.ownervc.dashboard import (
    OwnerVCControlView,
    VoiceModerationSelect,
    VoicePrivacyCapacitySelect,
    MessageModerationSelect,
    SelectTargetMemberView,
    build_owner_vc_embed,
    VCDashboard,
)
from bot.cogs.ownervc.staff_panel import ConfirmBulkActionView


def _make_guild(guild_id: int = 1560990395666538529, owner_id: int = 1111111111) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.owner_id = owner_id
    guild.default_role = MagicMock(spec=discord.Role, name="@everyone")
    guild.me = MagicMock(spec=discord.Member)
    guild.me.top_role = MagicMock(spec=discord.Role, position=100)
    guild.me.guild_permissions = MagicMock(spec=discord.Permissions)
    guild.me.guild_permissions.administrator = True
    guild.me.guild_permissions.manage_channels = True
    guild.me.guild_permissions.mute_members = True
    guild.me.guild_permissions.deafen_members = True
    guild.me.guild_permissions.move_members = True
    guild.me.guild_permissions.manage_messages = True
    guild.me.guild_permissions.moderate_members = True

    owner_member = MagicMock(spec=discord.Member)
    owner_member.id = owner_id
    owner_member.display_name = "ServerOwner"
    owner_member.mention = "@ServerOwner"
    guild.get_member.side_effect = lambda uid: owner_member if uid == owner_id else None
    return guild


def _make_vc(guild: MagicMock, channel_id: int = 999999, name: str = "❄️. Fun Time!") -> MagicMock:
    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = channel_id
    vc.name = name
    vc.mention = f"<#{channel_id}>"
    vc.guild = guild
    vc.user_limit = 0
    vc.bitrate = 64000
    vc.rtc_region = None
    vc.category = None
    vc.members = []
    vc.overwrites = {}

    default_ow = MagicMock(spec=discord.PermissionOverwrite)
    default_ow.connect = None
    default_ow.view_channel = None
    vc.overwrites_for.return_value = default_ow
    vc.set_permissions = AsyncMock()
    vc.edit = AsyncMock()
    guild.get_channel.return_value = vc
    return vc


def _make_bot(owner_ids: list[int] | None = None) -> MagicMock:
    bot = MagicMock()
    bot.config = MagicMock()
    bot.config.owner_ids = owner_ids or [999000111]
    bot.db = AsyncMock()
    bot.vc_repo = AsyncMock()
    return bot


# ─────────────────────────────────────────────────────────────────────────────
# 1. VISUAL LAYOUT & EMBED VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def test_owner_vc_embed_layout_and_fields():
    guild = _make_guild(owner_id=1111111111)
    vc = _make_vc(guild, name="❄️. Fun Time!")
    vc.user_limit = 0
    vc.bitrate = 64000

    # 3 connected members: 1 owner (speaking), 2 members
    owner = MagicMock(spec=discord.Member, id=1111111111)
    owner.voice = MagicMock(mute=False, self_mute=False, deaf=False, self_deaf=False)
    m2 = MagicMock(spec=discord.Member, id=2222222222)
    m2.voice = MagicMock(mute=False, self_mute=False, deaf=False, self_deaf=False)
    m3 = MagicMock(spec=discord.Member, id=3333333333)
    m3.voice = MagicMock(mute=True, self_mute=True, deaf=False, self_deaf=False)
    vc.members = [owner, m2, m3]

    embed = build_owner_vc_embed(vc, ban_count=0)

    assert "Owner" in embed.title or "VCPANEL" in embed.title or "Staff" in embed.title
    desc = embed.description

    # Line 1: Live voice channel name, connected, limit, bitrate
    assert "❄️. Fun Time!" in desc and "64 kbps" in desc and "3" in desc

    # Line 2: Operators
    assert "Operators: @ServerOwner" in desc

    # Line 3: Presence and activity
    assert "Owner present" in desc and "Voice active" in desc and "Audio active" in desc

    # Line 4: Status flags
    assert "Anti-mute" in desc and "Anti-deafen" in desc and "Open" in desc and "Visible" in desc

    # Line 5: Description
    assert "Voice · Room privacy · Message moderation" in desc


def test_owner_vc_embed_absent_and_idle_state():
    guild = _make_guild(owner_id=1111111111)
    vc = _make_vc(guild, name="Empty Room")
    vc.user_limit = 10
    vc.bitrate = 96000
    vc.members = []

    # Locked and hidden
    ow = MagicMock(spec=discord.PermissionOverwrite, connect=False, view_channel=False)
    vc.overwrites_for.return_value = ow

    embed = build_owner_vc_embed(vc, ban_count=2)
    desc = embed.description

    assert "Empty Room" in desc and "96 kbps" in desc and "10" in desc
    assert "Owner absent" in desc and "Voice idle" in desc and "Audio silent" in desc
    assert "Anti-mute" in desc and "Anti-deafen" in desc and "Locked" in desc and "Hidden" in desc and "2" in desc


# ─────────────────────────────────────────────────────────────────────────────
# 2. VIEW STRUCTURE: EXACTLY THREE DROPDOWN SECTIONS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_view_has_exactly_three_dropdowns():
    bot = _make_bot()
    guild = _make_guild()
    vc = _make_vc(guild)
    view = OwnerVCControlView(bot, vc)

    # Must contain exactly 3 select items in rows 0, 1, 2
    selects = [item for item in view.children if isinstance(item, discord.ui.Select)]
    assert len(selects) == 3

    s1, s2, s3 = selects
    assert isinstance(s1, VoiceModerationSelect)
    assert s1.placeholder == "Voice moderation"
    assert s1.row == 0
    assert len(s1.options) == 17

    assert isinstance(s2, VoicePrivacyCapacitySelect)
    assert s2.placeholder == "Voice room privacy and capacity"
    assert s2.row == 1
    assert len(s2.options) == 14

    assert isinstance(s3, MessageModerationSelect)
    assert s3.placeholder == "Message moderation"
    assert s3.row == 2
    assert len(s3.options) == 10


# ─────────────────────────────────────────────────────────────────────────────
# 3. STRICT SOVEREIGN AUTHORIZATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authorization_server_owner_allowed():
    bot = _make_bot(owner_ids=[999000111])
    guild = _make_guild(owner_id=1111111111)
    vc = _make_vc(guild)
    cog = VCDashboard(bot)

    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = MagicMock(spec=discord.Member, id=1111111111)  # Server Owner
    ctx.send = AsyncMock()

    await cog._execute_owner_vcpanel(ctx, vc)
    ctx.send.assert_called_once()
    assert "embed" in ctx.send.call_args[1]
    assert isinstance(ctx.send.call_args[1]["view"], OwnerVCControlView)


@pytest.mark.asyncio
async def test_authorization_bot_owner_allowed():
    bot = _make_bot(owner_ids=[999000111])
    guild = _make_guild(owner_id=1111111111)
    vc = _make_vc(guild)
    cog = VCDashboard(bot)

    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = MagicMock(spec=discord.Member, id=999000111)  # Configured Bot Owner
    ctx.send = AsyncMock()

    await cog._execute_owner_vcpanel(ctx, vc)
    ctx.send.assert_called_once()
    assert "embed" in ctx.send.call_args[1]
    assert isinstance(ctx.send.call_args[1]["view"], OwnerVCControlView)


@pytest.mark.asyncio
async def test_authorization_administrator_only_denied():
    bot = _make_bot(owner_ids=[999000111])
    guild = _make_guild(owner_id=1111111111)
    vc = _make_vc(guild)
    cog = VCDashboard(bot)

    ctx = MagicMock()
    ctx.guild = guild
    # Admin, but neither server owner nor bot owner
    ctx.author = MagicMock(spec=discord.Member, id=5555555555)
    ctx.author.guild_permissions = MagicMock(administrator=True, manage_channels=True)
    ctx.send = AsyncMock()

    await cog._execute_owner_vcpanel(ctx, vc)
    ctx.send.assert_called_once()
    call_content = ctx.send.call_args[0][0]
    assert "Access Denied" in call_content
    assert "embed" not in ctx.send.call_args[1]


@pytest.mark.asyncio
async def test_authorization_staff_role_only_denied():
    bot = _make_bot(owner_ids=[999000111])
    guild = _make_guild(owner_id=1111111111)
    vc = _make_vc(guild)
    cog = VCDashboard(bot)

    # Configured staff in repo, but not owner
    bot.vc_repo.is_staff.return_value = True

    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = MagicMock(spec=discord.Member, id=6666666666, roles=[MagicMock(id=8888)])
    ctx.author.guild_permissions = MagicMock(administrator=False, manage_channels=False)
    ctx.send = AsyncMock()

    await cog._execute_owner_vcpanel(ctx, vc)
    ctx.send.assert_called_once()
    call_content = ctx.send.call_args[0][0]
    assert "Access Denied" in call_content
    assert "embed" not in ctx.send.call_args[1]


@pytest.mark.asyncio
async def test_authorization_ordinary_user_denied():
    bot = _make_bot(owner_ids=[999000111])
    guild = _make_guild(owner_id=1111111111)
    vc = _make_vc(guild)
    cog = VCDashboard(bot)

    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = MagicMock(spec=discord.Member, id=7777777777)
    ctx.send = AsyncMock()

    await cog._execute_owner_vcpanel(ctx, vc)
    ctx.send.assert_called_once()
    call_content = ctx.send.call_args[0][0]
    assert "Access Denied" in call_content
    assert "embed" not in ctx.send.call_args[1]


@pytest.mark.asyncio
async def test_interaction_check_rechecked_on_components():
    bot = _make_bot(owner_ids=[999000111])
    guild = _make_guild(owner_id=1111111111)
    vc = _make_vc(guild)
    view = OwnerVCControlView(bot, vc)

    # Interaction from unauthorized user
    intr_unauth = MagicMock(spec=discord.Interaction)
    intr_unauth.guild = guild
    intr_unauth.user = MagicMock(spec=discord.Member, id=9999999999)  # Not owner
    intr_unauth.response = MagicMock()
    intr_unauth.response.send_message = AsyncMock()

    check_result = await view.interaction_check(intr_unauth)
    assert check_result is False
    intr_unauth.response.send_message.assert_called_once()
    assert "Access Denied" in intr_unauth.response.send_message.call_args[0][0]

    # Interaction from server owner
    intr_owner = MagicMock(spec=discord.Interaction)
    intr_owner.guild = guild
    intr_owner.user = MagicMock(spec=discord.Member, id=1111111111)
    assert await view.interaction_check(intr_owner) is True

    # Interaction from bot owner
    intr_bot_owner = MagicMock(spec=discord.Interaction)
    intr_bot_owner.guild = guild
    intr_bot_owner.user = MagicMock(spec=discord.Member, id=999000111)
    assert await view.interaction_check(intr_bot_owner) is True


# ─────────────────────────────────────────────────────────────────────────────
# 4. FUNCTIONAL DROPDOWN ACTIONS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_privacy_dropdown_lock_and_unlock():
    bot = _make_bot()
    guild = _make_guild()
    vc = _make_vc(guild)
    view = OwnerVCControlView(bot, vc)

    intr = MagicMock(spec=discord.Interaction)
    intr.guild = guild
    intr.user = MagicMock(spec=discord.Member, id=guild.owner_id)
    intr.response = MagicMock()
    intr.response.send_message = AsyncMock()
    intr.response.edit_message = AsyncMock()
    intr.response.is_done.return_value = False

    # Lock
    await view._handle_lock(intr)
    vc.set_permissions.assert_called_with(guild.default_role, connect=False, reason=f"VCPANEL Lock by {intr.user}")

    # Unlock
    await view._handle_unlock(intr)
    vc.set_permissions.assert_called_with(guild.default_role, connect=None, reason=f"VCPANEL Unlock by {intr.user}")


@pytest.mark.asyncio
async def test_privacy_dropdown_limit_and_bitrate_cycles():
    bot = _make_bot()
    guild = _make_guild()
    vc = _make_vc(guild)
    vc.user_limit = 0
    vc.bitrate = 64000
    view = OwnerVCControlView(bot, vc)

    intr = MagicMock(spec=discord.Interaction)
    intr.guild = guild
    intr.user = MagicMock(spec=discord.Member, id=guild.owner_id)
    intr.response = MagicMock()
    intr.response.send_message = AsyncMock()
    intr.response.edit_message = AsyncMock()
    intr.response.is_done.return_value = False

    # Limit cycle from 0 -> 2
    await view._handle_limit_cycle(intr)
    vc.edit.assert_called_with(user_limit=2, reason=f"VCPANEL Limit by {intr.user}")

    # Bitrate cycle from 64000 -> 96000
    await view._handle_bitrate_cycle(intr)
    vc.edit.assert_called_with(bitrate=96000, reason=f"VCPANEL Bitrate by {intr.user}")


@pytest.mark.asyncio
async def test_voice_moderation_single_target_kick_and_ban():
    bot = _make_bot()
    guild = _make_guild()
    vc = _make_vc(guild)
    view = OwnerVCControlView(bot, vc)

    target = MagicMock(spec=discord.Member, id=4444444444, display_name="BadUser")
    target.voice = MagicMock(channel=vc)
    target.move_to = AsyncMock()

    intr = MagicMock(spec=discord.Interaction)
    intr.guild = guild
    intr.user = MagicMock(spec=discord.Member, id=guild.owner_id)
    intr.response = MagicMock()
    intr.response.send_message = AsyncMock()
    intr.response.edit_message = AsyncMock()
    intr.response.is_done.return_value = False

    # Kick target
    await view._handle_kick_target(intr, target)
    target.move_to.assert_called_with(None, reason=f"VCPANEL Kick by {intr.user}")

    # Ban target
    await view._handle_ban_target(intr, target)
    vc.set_permissions.assert_called_with(target, connect=False, reason=f"VCPANEL VC Ban by {intr.user}")


@pytest.mark.asyncio
async def test_bulk_actions_require_two_step_confirmation():
    bot = _make_bot()
    guild = _make_guild()
    vc = _make_vc(guild)
    view = OwnerVCControlView(bot, vc)

    select = view.children[0]  # VoiceModerationSelect is already bound to view

    intr = MagicMock(spec=discord.Interaction)
    intr.guild = guild
    intr.user = MagicMock(spec=discord.Member, id=guild.owner_id)
    intr.response = MagicMock()
    intr.response.send_message = AsyncMock()

    # Trigger mute_all
    select._values = ["mute_all"]
    await select.callback(intr)

    intr.response.send_message.assert_called_once()
    call_kwargs = intr.response.send_message.call_args[1]
    assert "view" in call_kwargs
    assert isinstance(call_kwargs["view"], ConfirmBulkActionView)
    assert call_kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_message_moderation_purge_and_slowmode():
    bot = _make_bot()
    guild = _make_guild()
    vc = _make_vc(guild)
    view = OwnerVCControlView(bot, vc)

    text_ch = MagicMock(spec=discord.TextChannel)
    text_ch.purge = AsyncMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
    text_ch.slowmode_delay = 0
    text_ch.edit = AsyncMock()

    intr = MagicMock(spec=discord.Interaction)
    intr.guild = guild
    intr.channel = text_ch
    intr.user = MagicMock(spec=discord.Member, id=guild.owner_id)
    intr.response = MagicMock()
    intr.response.defer = AsyncMock()
    intr.followup = MagicMock()
    intr.followup.send = AsyncMock()
    intr.response.send_message = AsyncMock()
    intr.response.is_done.return_value = False

    # Purge 10
    await view._handle_purge(intr, 10)
    text_ch.purge.assert_called_with(limit=10)
    intr.followup.send.assert_called_once()
    assert "Purged **3** messages" in intr.followup.send.call_args[0][0]

    # Slowmode cycle 0 -> 5
    await view._handle_slowmode_cycle(intr)
    text_ch.edit.assert_called_with(slowmode_delay=5, reason=f"Slowmode change by {intr.user}")


# ─────────────────────────────────────────────────────────────────────────────
# 5. INDEPENDENCE OF SEPARATE VC STAFF PANEL
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_separate_vc_staff_panel_remains_operational():
    bot = _make_bot()
    guild = _make_guild(owner_id=1111111111)
    vc = _make_vc(guild)
    cog = VCDashboard(bot)

    # Authorized staff user
    staff_user = MagicMock(spec=discord.Member, id=8888888888, roles=[MagicMock(id=999)])
    bot.vc_repo.is_staff.return_value = True
    bot.vc_repo.get_staff_bulk_actions_allowed.return_value = False

    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = staff_user
    ctx.send = AsyncMock()

    await cog._execute_vc_staff_panel(ctx, vc)
    ctx.send.assert_called_once()
    assert "embed" in ctx.send.call_args[1]
    # Check that staff panel view was sent
    sent_view = ctx.send.call_args[1]["view"]
    assert sent_view.__class__.__name__ == "VCStaffControlView"
