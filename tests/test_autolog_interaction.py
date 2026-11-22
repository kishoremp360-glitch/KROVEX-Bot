"""Automated Tests for /logs autolog Immediate Deferral, Timeout Prevention, and Followup Delivery."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.config import BotConfig
from bot.core.bot import DeathBot
from bot.core.context import UnifiedContext
from bot.cogs.logging.cog import Logging


@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=DeathBot)
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.logging_repo = AsyncMock()
    return bot


def _make_mock_interaction(guild_id: int = 123456):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.id = 99887766
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = guild_id
    interaction.guild.name = "Logging Test Guild"
    interaction.guild.categories = []

    # Bot Member
    me = MagicMock(spec=discord.Member)
    me.guild_permissions.manage_channels = True
    me.guild_permissions.administrator = True
    interaction.guild.me = me

    # Default role
    interaction.guild.default_role = MagicMock(spec=discord.Role)

    # Category and channels mock
    cat = MagicMock(spec=discord.CategoryChannel)
    cat.name = "📋 LOGS"
    cat.text_channels = []
    interaction.guild.create_category = AsyncMock(return_value=cat)

    ch = MagicMock(spec=discord.TextChannel)
    ch.id = 111222
    ch.mention = "<#111222>"
    ch.send = AsyncMock()
    cat.create_text_channel = AsyncMock(return_value=ch)

    # Response and followup mocks
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.mark.asyncio
async def test_autolog_defers_immediately(mock_bot):
    """Verify /logs autolog calls interaction.response.defer(ephemeral=True) immediately upon execution."""
    cog = Logging(mock_bot)
    interaction = _make_mock_interaction()
    ctx = UnifiedContext.from_interaction(interaction)

    await cog._execute_autolog(ctx)

    # Verify defer was called with ephemeral=True
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    # Verify interaction.response.send_message was NEVER called after defer
    interaction.response.send_message.assert_not_awaited()
    # Verify followup.send was used to deliver the final response
    interaction.followup.send.assert_awaited_once()
    sent_embed = interaction.followup.send.call_args.kwargs.get("embeds")[0]
    assert "KROVEX" in sent_embed.title or "AutoLog" in sent_embed.title


@pytest.mark.asyncio
async def test_autolog_handles_permission_error_via_followup(mock_bot):
    """Verify that if Manage Channels is missing, error is sent via followup without raising unhandled exception."""
    cog = Logging(mock_bot)
    interaction = _make_mock_interaction()
    interaction.guild.me.guild_permissions.manage_channels = False
    ctx = UnifiedContext.from_interaction(interaction)

    await cog._execute_autolog(ctx)

    # Must still defer immediately to acknowledge Discord
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    # Sends error via followup
    interaction.followup.send.assert_awaited_once()
    sent_embed = interaction.followup.send.call_args.kwargs.get("embeds")[0]
    assert "Missing Permissions" in sent_embed.title


@pytest.mark.asyncio
async def test_log_reset_disable_enable_deferral(mock_bot):
    """Verify reset, disable, enable, and logchannel commands also defer immediately."""
    cog = Logging(mock_bot)

    # 1. Reset
    interaction = _make_mock_interaction()
    await cog._execute_logreset(UnifiedContext.from_interaction(interaction))
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.followup.send.assert_awaited_once()

    # 2. Disable
    interaction = _make_mock_interaction()
    await cog._execute_logdisable(UnifiedContext.from_interaction(interaction))
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.followup.send.assert_awaited_once()

    # 3. Enable
    interaction = _make_mock_interaction()
    await cog._execute_logenable(UnifiedContext.from_interaction(interaction))
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.followup.send.assert_awaited_once()

    # 4. Logchannel
    interaction = _make_mock_interaction()
    target_ch = MagicMock(spec=discord.TextChannel)
    target_ch.id = 555666
    target_ch.mention = "<#555666>"
    await cog._execute_logchannel(UnifiedContext.from_interaction(interaction), category="mod", channel=target_ch)
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.followup.send.assert_awaited_once()

