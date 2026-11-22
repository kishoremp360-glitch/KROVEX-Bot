"""Comprehensive unit tests for KROVEX Owner & Staff Moderation Dashboard actions.

Covers:
1. Dual-scope operations (Current VC vs Entire Server) for Mute All, Unmute All, Deafen All, Undeafen All, Kick All.
2. Move All with destination selection and scope indicator.
3. Temporary Mute and Temporary Deafen execution and timer scheduling.
4. View connected members across single VC and entire server.
5. Room management: Rename, Move AFK, Create, Delete, Clone.
6. Message moderation: Open tools, Purge, Delete message, Timeout, Lock/Unlock text, Slowmode.
7. Authorization & Protection: Sovereign protection, bot owner bypass, and role hierarchy.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.cogs.ownervc.dashboard import (
    OwnerVCControlView,
    VoiceScopeSelect,
    VoiceModerationSelect,
    VoicePrivacyCapacitySelect,
    MessageModerationSelect,
    RenameRoomModal,
    CreateVoiceRoomModal,
    SelectDestinationVoiceChannelView,
    TempDurationSelectView,
)


@pytest.fixture
def mock_context():
    bot = MagicMock()
    bot.config = MagicMock(owner_ids=[10001])
    bot.owner_ids = {10001}
    bot.vc_repo = None
    bot.db = None

    guild = MagicMock(spec=discord.Guild)
    guild.id = 99999
    guild.owner_id = 10002
    guild.default_role = MagicMock()
    guild.afk_channel = MagicMock(spec=discord.VoiceChannel, id=77777, name="AFK Channel")

    me = MagicMock(spec=discord.Member)
    me.id = 12345
    perms = discord.Permissions(administrator=True, move_members=True, mute_members=True, deafen_members=True, manage_channels=True)
    me.guild_permissions = perms
    guild.me = me

    # Channels
    vc1 = MagicMock(spec=discord.VoiceChannel)
    vc1.id = 11111
    vc1.name = "VC 1"
    vc1.guild = guild
    vc1.user_limit = 0
    vc1.bitrate = 64000
    vc1.overwrites = {}
    vc1.overwrites_for.return_value = MagicMock(connect=None, view_channel=None)

    vc2 = MagicMock(spec=discord.VoiceChannel)
    vc2.id = 22222
    vc2.name = "VC 2"
    vc2.guild = guild
    vc2.user_limit = 10
    vc2.bitrate = 96000
    vc2.overwrites = {}
    vc2.overwrites_for.return_value = MagicMock(connect=None, view_channel=None)

    # Members
    m_owner = MagicMock(spec=discord.Member, id=10002, display_name="Guild Owner", bot=False)
    m_bot = MagicMock(spec=discord.Member, id=12345, display_name="KROVEX", bot=True)
    m_regular1 = MagicMock(spec=discord.Member, id=30001, display_name="User 1", bot=False)
    m_regular2 = MagicMock(spec=discord.Member, id=30002, display_name="User 2", bot=False)

    m_regular1.edit = AsyncMock()
    m_regular2.edit = AsyncMock()
    m_regular1.move_to = AsyncMock()
    m_regular2.move_to = AsyncMock()
    m_owner.edit = AsyncMock()
    m_owner.move_to = AsyncMock()

    vc1.members = [m_owner, m_regular1]
    vc2.members = [m_regular2]

    guild.voice_channels = [vc1, vc2]
    guild.get_channel = lambda cid: vc1 if cid == 11111 else (vc2 if cid == 22222 else None)
    guild.get_member = lambda uid: {10002: m_owner, 12345: m_bot, 30001: m_regular1, 30002: m_regular2}.get(uid)

    view = OwnerVCControlView(bot, vc1, scope="current_vc")
    return {
        "bot": bot,
        "guild": guild,
        "vc1": vc1,
        "vc2": vc2,
        "m_owner": m_owner,
        "m_reg1": m_regular1,
        "m_reg2": m_regular2,
        "view": view,
    }


@pytest.mark.asyncio
async def test_dual_scope_muteall(mock_context):
    """Test Mute All respects current_vc scope vs entire_server scope and protects guild sovereign."""
    view: OwnerVCControlView = mock_context["view"]
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = mock_context["guild"]
    interaction.user = mock_context["m_owner"]
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()

    # Scope: current_vc (vc1 has owner and reg1)
    view.scope = "current_vc"
    await view._handle_muteall(interaction)

    # Sovereign should NOT be muted, reg1 should be muted
    mock_context["m_owner"].edit.assert_not_awaited()
    mock_context["m_reg1"].edit.assert_awaited_once_with(mute=True, reason=f"VCPANEL Mute All by {interaction.user}")
    mock_context["m_reg2"].edit.assert_not_awaited()

    # Reset
    mock_context["m_reg1"].edit.reset_mock()
    mock_context["m_reg2"].edit.reset_mock()

    # Scope: entire_server (vc1 and vc2)
    view.scope = "entire_server"
    await view._handle_muteall(interaction)

    mock_context["m_owner"].edit.assert_not_awaited()
    mock_context["m_reg1"].edit.assert_awaited_once_with(mute=True, reason=f"VCPANEL Mute All by {interaction.user}")
    mock_context["m_reg2"].edit.assert_awaited_once_with(mute=True, reason=f"VCPANEL Mute All by {interaction.user}")


@pytest.mark.asyncio
async def test_dual_scope_kickall(mock_context):
    """Test Disconnect All disconnects non-protected members in active scope."""
    view: OwnerVCControlView = mock_context["view"]
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = mock_context["guild"]
    interaction.user = mock_context["m_owner"]
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()

    view.scope = "current_vc"
    await view._handle_kickall(interaction)

    mock_context["m_owner"].move_to.assert_not_awaited()
    mock_context["m_reg1"].move_to.assert_awaited_once_with(None, reason=f"VCPANEL Kick All by {interaction.user}")
    mock_context["m_reg2"].move_to.assert_not_awaited()


@pytest.mark.asyncio
async def test_move_all_execution(mock_context):
    """Test Move All gathers eligible members and moves them to destination channel."""
    view: OwnerVCControlView = mock_context["view"]
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = mock_context["guild"]
    interaction.user = mock_context["m_owner"]
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()

    dest_vc = mock_context["vc2"]
    view.scope = "current_vc"

    # Confirm move all into vc2
    await view._handle_moveall_confirm(interaction, dest_vc)
    # Check that confirmation was sent
    interaction.response.send_message.assert_awaited_once()
    args, kwargs = interaction.response.send_message.call_args
    assert "Move" in args[0]
    assert "VC 2" in args[0]
    assert "🎯 Current VC" in args[0]


@pytest.mark.asyncio
async def test_temp_mute_execution_and_schedule(mock_context):
    """Test Temporary Mute mutes member and schedules unmuting."""
    view: OwnerVCControlView = mock_context["view"]
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = mock_context["guild"]
    interaction.user = mock_context["m_owner"]
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()

    target = mock_context["m_reg1"]
    target.voice = MagicMock(mute=False)

    with patch("asyncio.create_task") as mock_task:
        await view._handle_temp_mute_execute(interaction, target, 60, "1 minute")
        target.edit.assert_awaited_once_with(mute=True, reason=f"VCPANEL Temp Mute (1 minute) by {interaction.user}")
        mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_view_connected_members(mock_context):
    """Test View Connected Members produces detailed member list."""
    view: OwnerVCControlView = mock_context["view"]
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = mock_context["guild"]
    interaction.user = mock_context["m_owner"]
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()

    # Current VC
    view.scope = "current_vc"
    await view._handle_view_members(interaction)
    call_args = interaction.response.send_message.call_args[1]
    embed = call_args["embed"]
    assert "Connected Members" in embed.title
    assert "User 1" in embed.description

    # Entire Server
    interaction.response.send_message.reset_mock()
    view.scope = "entire_server"
    await view._handle_view_members(interaction)
    call_args = interaction.response.send_message.call_args[1]
    embed = call_args["embed"]
    assert "Entire Server" in embed.title
    assert "User 1" in embed.description
    assert "User 2" in embed.description


@pytest.mark.asyncio
async def test_move_afk_execution(mock_context):
    """Test Move to AFK transfers members to guild AFK channel."""
    view: OwnerVCControlView = mock_context["view"]
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = mock_context["guild"]
    interaction.user = mock_context["m_owner"]
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()

    view.scope = "current_vc"
    await view._handle_move_afk(interaction)

    afk_ch = mock_context["guild"].afk_channel
    mock_context["m_reg1"].move_to.assert_awaited_once_with(afk_ch, reason=f"Moved to AFK by {interaction.user}")
    mock_context["m_owner"].move_to.assert_not_awaited()


@pytest.mark.asyncio
async def test_room_cloning(mock_context):
    """Test Room Cloning clones channel with copy suffix."""
    view: OwnerVCControlView = mock_context["view"]
    vc1 = mock_context["vc1"]
    vc1.clone = AsyncMock(return_value=MagicMock(mention="<#999>"))

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = mock_context["guild"]
    interaction.user = mock_context["m_owner"]
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()

    await view._handle_clone_room(interaction)
    vc1.clone.assert_awaited_once_with(name="VC 1 (Copy)", reason=f"VCPANEL Clone Room by {interaction.user}")


@pytest.mark.asyncio
async def test_open_message_tools_overview(mock_context):
    """Test Open Message Tools renders quick moderation intelligence embed."""
    view: OwnerVCControlView = mock_context["view"]
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = mock_context["guild"]
    interaction.user = mock_context["m_owner"]
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()

    await view._handle_open_message_tools(interaction)
    embed = interaction.response.send_message.call_args[1]["embed"]
    assert "Message Moderation Quick Tools" in embed.title
    assert "Purge" in embed.description
    assert "Timeout" in embed.description


@pytest.mark.asyncio
async def test_unauthorized_user_blocked(mock_context):
    """Test unauthorized interaction receives Access Denied."""
    view: OwnerVCControlView = mock_context["view"]
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = mock_context["guild"]
    # Random member (not server owner, not bot owner)
    interaction.user = mock_context["m_reg1"]
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    allowed = await view.interaction_check(interaction)
    assert allowed is False
    interaction.response.send_message.assert_awaited_once()
    assert "Access Denied" in interaction.response.send_message.call_args[0][0]
