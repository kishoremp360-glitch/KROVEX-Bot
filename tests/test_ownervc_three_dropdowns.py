"""Test suite for KROVEX OwnerVC Three-Dropdown Control Center.

Verifies:
1. Dashboard layout has exactly three dropdowns.
2. Bot owner global bypass works with zero permission errors.
3. Live VC information embed layout matches THOR APEX format.
4. Voice moderation options include VC loop controls and NO bulk movement.
5. Voice privacy & capacity controls.
6. Message moderation controls.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.cogs.ownervc.dashboard import (
    OwnerVCControlView,
    VoiceModerationSelect,
    VoicePrivacyCapacitySelect,
    MessageModerationSelect,
    build_owner_vc_embed,
)
from bot.config import BotConfig
from bot.core.bot import DeathBot


def test_three_dropdowns_structure():
    """Verify that OwnerVCControlView contains exactly three dropdown items and no extra dropdowns."""
    mock_bot = MagicMock()
    mock_channel = MagicMock(spec=discord.VoiceChannel)
    mock_channel.guild = MagicMock()
    mock_channel.guild.default_role = MagicMock()
    mock_channel.overwrites_for.return_value = MagicMock(connect=None, view_channel=None)
    mock_channel.members = []
    mock_channel.user_limit = 0
    mock_channel.bitrate = 64000

    view = OwnerVCControlView(mock_bot, mock_channel)

    # Exactly 3 select menus
    selects = [item for item in view.children if isinstance(item, discord.ui.Select)]
    assert len(selects) == 3

    assert isinstance(selects[0], VoiceModerationSelect)
    assert selects[0].placeholder == "Voice moderation"

    assert isinstance(selects[1], VoicePrivacyCapacitySelect)
    assert selects[1].placeholder == "Voice room privacy and capacity"

    assert isinstance(selects[2], MessageModerationSelect)
    assert selects[2].placeholder == "Message moderation"


def test_dropdown_one_voice_moderation_options():
    """Verify Dropdown 1 options include bulk actions, individual actions, VC loop controls, and NO bulk movement."""
    select = VoiceModerationSelect()
    values = [opt.value for opt in select.options]

    # Bulk actions
    assert "mute_all" in values
    assert "unmute_all" in values
    assert "deafen_all" in values
    assert "undeafen_all" in values
    assert "kick_all" in values

    # Individual actions
    assert "mute" in values
    assert "unmute" in values
    assert "deafen" in values
    assert "undeafen" in values
    assert "kick" in values
    assert "ban" in values
    assert "unban" in values

    # VC Loop controls
    assert "loop_activate" in values
    assert "loop_stop" in values
    assert "loop_status" in values

    # Strict Exclusion: NO multi-member move or bulk movement
    for opt in select.options:
        label = opt.label.lower()
        assert "multiple" not in label
        assert "bulk move" not in label


def test_dropdown_two_privacy_and_capacity_options():
    """Verify Dropdown 2 options match privacy, bitrate, limit, and operator specifications."""
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
    assert "add_operator" in values
    assert "remove_operator" in values
    assert "operators" in values
    assert "info" in values


def test_dropdown_three_message_moderation_options():
    """Verify Dropdown 3 options match purge, timeout, and message controls."""
    select = MessageModerationSelect()
    values = [opt.value for opt in select.options]

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
    assert "unlock_text" in values
    assert "slowmode" in values


def test_live_ownervc_embed_header_formatting():
    """Verify embed header displays verified live metadata matching THOR APEX layout."""
    mock_channel = MagicMock(spec=discord.VoiceChannel)
    mock_channel.name = "❄️. Fun Time!"
    mock_channel.guild.owner_id = 999888777
    mock_channel.user_limit = 0
    mock_channel.bitrate = 64000
    mock_channel.members = []

    mock_ow = MagicMock()
    mock_ow.connect = None
    mock_ow.view_channel = None
    mock_channel.overwrites_for.return_value = mock_ow

    embed = build_owner_vc_embed(mock_channel, ban_count=0)

    assert embed.title == "Owner & Staff Moderation Dashboard"
    desc = embed.description
    assert "❄️. Fun Time!" in desc
    assert "connected" in desc
    assert "Limit" in desc
    assert "64 kbps" in desc
    assert "Anti-mute" in desc
    assert "Anti-deafen" in desc
    assert "voice-banned here" in desc
    assert "Voice · Room privacy · Message moderation" in desc


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

    # Prefix command with administrator permission requirement
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
