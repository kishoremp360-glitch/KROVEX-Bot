"""Unit tests for Finding P1-03: VCControlView authorization and permission checks."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.ownervc.dashboard import VCControlView


@pytest.fixture
def mock_voice_channel():
    vc = MagicMock(spec=discord.VoiceChannel)
    vc.id = 55555
    vc.name = "Study Lounge"
    vc.members = []
    vc.guild = MagicMock(spec=discord.Guild)
    vc.guild.id = 12345
    vc.guild.default_role = MagicMock(spec=discord.Role)
    vc.guild.owner_id = 999
    vc.set_permissions = AsyncMock()
    return vc


@pytest.mark.asyncio
async def test_unauthorized_member_rejected_by_vc_view(mock_voice_channel):
    """Member without manage_channels or admin is rejected by interaction_check."""
    bot = MagicMock()
    view = VCControlView(bot=bot, channel=mock_voice_channel)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.guild_permissions.administrator = False
    interaction.user.guild_permissions.manage_channels = False
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    allowed = await view.interaction_check(interaction)
    assert allowed is False
    interaction.response.send_message.assert_awaited_once()
    assert "manage channels" in interaction.response.send_message.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_authorized_member_passes_interaction_check(mock_voice_channel):
    """Member with manage_channels passes interaction_check."""
    bot = MagicMock()
    view = VCControlView(bot=bot, channel=mock_voice_channel)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.guild_permissions.administrator = False
    interaction.user.guild_permissions.manage_channels = True
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    allowed = await view.interaction_check(interaction)
    assert allowed is True


@pytest.mark.asyncio
async def test_missing_bot_permission_rejected(mock_voice_channel):
    """If bot lacks manage_channels permission, lock_btn aborts with an error."""
    bot = MagicMock()
    view = VCControlView(bot=bot, channel=mock_voice_channel)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.guild_permissions.administrator = True
    interaction.guild = mock_voice_channel.guild
    interaction.guild.get_channel = MagicMock(return_value=mock_voice_channel)
    interaction.guild.me = MagicMock(spec=discord.Member)
    # Bot lacks manage_channels and administrator
    interaction.guild.me.guild_permissions.administrator = False
    interaction.guild.me.guild_permissions.manage_channels = False
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done.return_value = False

    await view.lock_btn.callback(interaction)

    mock_voice_channel.set_permissions.assert_not_called()
    interaction.response.send_message.assert_awaited_once()
    assert "i need manage channels" in interaction.response.send_message.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_missing_channel_handled_gracefully(mock_voice_channel):
    """If voice channel was deleted, clicking a button reports missing channel."""
    bot = MagicMock()
    view = VCControlView(bot=bot, channel=mock_voice_channel)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.guild_permissions.administrator = True
    interaction.guild = mock_voice_channel.guild
    # Channel not found
    interaction.guild.get_channel = MagicMock(return_value=None)
    interaction.guild.me = MagicMock(spec=discord.Member)
    interaction.guild.me.guild_permissions.manage_channels = True
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await view.lock_btn.callback(interaction)

    mock_voice_channel.set_permissions.assert_not_called()
    interaction.response.send_message.assert_awaited_once()
    assert "no longer exists" in interaction.response.send_message.call_args[0][0].lower()
