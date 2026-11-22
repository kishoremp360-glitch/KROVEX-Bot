"""Test suite for KROVEX OwnerVC Dashboard with Three Dropdown Sections & Scope Selector.

Verifies:
1. Dashboard layout has VoiceScopeSelect (row 0), exactly 3 section dropdowns (rows 1-3), and row 4 quick action buttons.
2. Bot owner global bypass works with zero permission errors.
3. Live VC information embed layout matches THOR APEX format and reflects active scope.
4. Voice moderation options include Move All, Temporary Mute/Deafen, Member inspection, and VC loop controls.
5. Voice privacy & capacity controls include Rename, AFK transfer, Create, Delete, and Clone room.
6. Message moderation controls include Open Message Tools, purge, timeout, and text locking.
7. Scope selector switches between Current VC and Entire Server.
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
    build_owner_vc_embed,
)
from bot.config import BotConfig
from bot.core.bot import DeathBot


def test_three_dropdowns_structure():
    """Verify that OwnerVCControlView contains the scope selector and exactly three section dropdowns."""
    mock_bot = MagicMock()
    mock_channel = MagicMock(spec=discord.VoiceChannel)
    mock_channel.guild = MagicMock()
    mock_channel.guild.default_role = MagicMock()
    mock_channel.overwrites_for.return_value = MagicMock(connect=None, view_channel=None)
    mock_channel.members = []
    mock_channel.user_limit = 0
    mock_channel.bitrate = 64000

    view = OwnerVCControlView(mock_bot, mock_channel)

    # 4 select menus in total: 1 Scope selector (row 0) + 3 section dropdowns (rows 1, 2, 3)
    selects = [item for item in view.children if isinstance(item, discord.ui.Select)]
    assert len(selects) == 4

    assert isinstance(selects[0], VoiceScopeSelect)
    assert selects[0].row == 0

    assert isinstance(selects[1], VoiceModerationSelect)
    assert selects[1].placeholder == "Voice moderation"
    assert selects[1].row == 1

    assert isinstance(selects[2], VoicePrivacyCapacitySelect)
    assert selects[2].placeholder == "Voice room privacy and capacity"
    assert selects[2].row == 2

    assert isinstance(selects[3], MessageModerationSelect)
    assert selects[3].placeholder == "Message moderation"
    assert selects[3].row == 3

    # Row 4 buttons: Switch VC, Voice Control Centre, Owner Governance
    buttons = [item for item in view.children if isinstance(item, discord.ui.Button)]
    assert len(buttons) == 3
    btn_labels = [b.label for b in buttons]
    assert "Switch VC" in btn_labels
    assert "Voice Control Centre" in btn_labels
    assert "Owner Governance" in btn_labels


def test_scope_selector_options():
    """Verify VoiceScopeSelect provides Current VC and Entire Server options."""
    select = VoiceScopeSelect(current_scope="current_vc")
    values = [opt.value for opt in select.options]
    assert "current_vc" in values
    assert "entire_server" in values


def test_dropdown_one_voice_moderation_options():
    """Verify Dropdown 1 options include bulk actions, individual actions, Move All, temp actions, and VC loop."""
    select = VoiceModerationSelect()
    values = [opt.value for opt in select.options]

    # Bulk actions
    assert "mute_all" in values
    assert "unmute_all" in values
    assert "deafen_all" in values
    assert "undeafen_all" in values
    assert "move_all" in values
    assert "kick_all" in values

    # Individual actions
    assert "mute" in values
    assert "unmute" in values
    assert "deafen" in values
    assert "undeafen" in values
    assert "drag" in values
    assert "kick" in values
    assert "ban" in values
    assert "unban" in values
    assert "temp_mute" in values
    assert "temp_deafen" in values
    assert "view_members" in values

    # VC Loop controls
    assert "loop_activate" in values
    assert "loop_stop" in values
    assert "loop_status" in values


def test_dropdown_two_privacy_and_capacity_options():
    """Verify Dropdown 2 options match privacy, bitrate, limit, room management, and operator specifications."""
    select = VoicePrivacyCapacitySelect()
    values = [opt.value for opt in select.options]

    assert "lock" in values
    assert "unlock" in values
    assert "ghost" in values
    assert "hide" in values
    assert "show" in values
    assert "set_limit" in values
    assert "remove_limit" in values
    assert "view_limit" in values
    assert "bitrate" in values
    assert "view_bitrate" in values
    assert "rename_room" in values
    assert "move_afk" in values
    assert "create_room" in values
    assert "delete_room" in values
    assert "clone_room" in values
    assert "add_operator" in values
    assert "remove_operator" in values
    assert "operators" in values
    assert "info" in values


def test_dropdown_three_message_moderation_options():
    """Verify Dropdown 3 options match open tools, purge, timeout, and message controls."""
    select = MessageModerationSelect()
    values = [opt.value for opt in select.options]

    assert "open_tools" in values
    assert "purge_10" in values
    assert "purge_25" in values
    assert "purge_50" in values
    assert "delete_msg" in values
    assert "timeout" in values
    assert "untimeout" in values
    assert "view_mod_info" in values
    assert "lock_text" in values
    assert "unlock_text" in values
    assert "slowmode" in values


def test_live_ownervc_embed_header_formatting():
    """Verify embed header displays verified live metadata matching THOR APEX layout and scope."""
    mock_channel = MagicMock(spec=discord.VoiceChannel)
    mock_channel.name = "❄️. Fun Time!"
    mock_channel.guild.owner_id = 999888777
    mock_channel.guild.default_role = MagicMock()
    mock_channel.user_limit = 0
    mock_channel.bitrate = 64000
    mock_channel.members = []

    mock_ow = MagicMock()
    mock_ow.connect = None
    mock_ow.view_channel = None
    mock_channel.overwrites_for.return_value = mock_ow

    # Current VC scope
    embed_vc = build_owner_vc_embed(mock_channel, ban_count=0, scope="current_vc")
    assert embed_vc.title == "Owner & Staff Moderation Dashboard"
    desc_vc = embed_vc.description
    assert "❄️. Fun Time!" in desc_vc
    assert "connected" in desc_vc
    assert "Limit" in desc_vc
    assert "64 kbps" in desc_vc
    assert "Anti-mute" in desc_vc
    assert "Anti-deafen" in desc_vc
    assert "voice-banned here" in desc_vc
    assert "Voice · Room privacy · Message moderation" in desc_vc
    assert "Current VC Scope" in desc_vc

    # Entire Server scope
    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.owner_id = 999888777
    mock_guild.voice_channels = [mock_channel]
    mock_guild.default_role = MagicMock()
    embed_server = build_owner_vc_embed(mock_channel, ban_count=0, guild=mock_guild, scope="entire_server")
    desc_server = embed_server.description
    assert "Entire Server Scope" in desc_server


@pytest.mark.asyncio
async def test_bot_owner_global_permission_bypass():
    """Verify that configured bot owners bypass all command permission checks without prompting."""
    bot = DeathBot(BotConfig.from_env(validate=False))
    bot.config = BotConfig(
        token="test_token",
        client_id=123,
        dev_guild_id=456,
        owner_ids=[777888999],
    )

    from discord.ext import commands
    @commands.command(name="test_admin_cmd")
    @commands.has_permissions(administrator=True)
    async def dummy_admin_cmd(ctx):
        pass

    mock_ctx = MagicMock(spec=commands.Context)
    mock_ctx.bot = bot
    mock_ctx.author.id = 777888999  # Bot owner
    mock_ctx.command = dummy_admin_cmd

    # Bot owner should bypass can_run completely
    can_run = await dummy_admin_cmd.can_run(mock_ctx)
    assert can_run is True

    # Non-owner without administrator should fail
    mock_ctx.author.id = 111222333  # Non-owner
    mock_ctx.author.guild_permissions = discord.Permissions(administrator=False)
    with pytest.raises(commands.CheckFailure):
        await dummy_admin_cmd.can_run(mock_ctx)


@pytest.mark.asyncio
async def test_ownerdashboard_interaction_intercept():
    """Verify that slash interaction for /ownerdashboard is intercepted and routes to owner panel."""
    bot = DeathBot(BotConfig.from_env(validate=False))
    mock_cog = MagicMock()
    mock_cog._execute_ownerpanel = AsyncMock()
    bot.get_cog = MagicMock(return_value=mock_cog)

    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.type = discord.InteractionType.application_command
    mock_interaction.data = {"name": "ownerdashboard"}

    await bot.on_interaction(mock_interaction)

    mock_cog._execute_ownerpanel.assert_awaited_once_with(mock_interaction)
