"""Unit tests for Finding P1-05: Server Setup Wizard Save & Apply verification and reliability."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.admin.setup_wizard import ServerSetupView, WizardCancelView, SetupWizard


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 12345
    guild.name = "Krovex Test Guild"
    guild.verification_level = discord.VerificationLevel.medium
    guild.system_channel = MagicMock(spec=discord.TextChannel)
    guild.system_channel.mention = "#general"
    guild.afk_channel = None
    guild.edit = AsyncMock()
    guild.icon = None
    guild.me = MagicMock(spec=discord.Member)
    guild.me.guild_permissions.administrator = True
    guild.me.guild_permissions.manage_guild = True
    return guild


@pytest.mark.asyncio
async def test_save_and_apply_success(mock_guild):
    """Admin clicks Save & Apply: prefix saved to DB, success embed sent, buttons disabled."""
    admin_id = 111111
    bot = MagicMock()
    bot.guild_repo = MagicMock()
    bot.guild_repo.set_prefix = AsyncMock(return_value=True)

    view = ServerSetupView(
        bot=bot,
        author_id=admin_id,
        guild=mock_guild,
        pending_prefix="?",
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = admin_id
    interaction.user.guild_permissions.administrator = True
    interaction.guild = mock_guild
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.edit_original_response = AsyncMock()

    await view.save_btn.callback(interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    bot.guild_repo.set_prefix.assert_awaited_once_with(mock_guild.id, "?")
    interaction.followup.send.assert_awaited_once()
    assert all(child.disabled for child in view.children)


@pytest.mark.asyncio
async def test_cancel_wizard(mock_guild):
    """Admin clicks Cancel Wizard: cancels without DB writes and disables buttons."""
    admin_id = 111111
    bot = MagicMock()
    bot.guild_repo = MagicMock()
    bot.guild_repo.set_prefix = AsyncMock()

    view = ServerSetupView(
        bot=bot,
        author_id=admin_id,
        guild=mock_guild,
        pending_prefix="?",
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = admin_id
    interaction.user.guild_permissions.administrator = True
    interaction.guild = mock_guild
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await view.cancel_btn.callback(interaction)

    bot.guild_repo.set_prefix.assert_not_called()
    interaction.response.send_message.assert_awaited_once()
    assert "cancelled" in interaction.response.send_message.call_args[0][0].lower()
    assert all(child.disabled for child in view.children)


@pytest.mark.asyncio
async def test_unauthorized_user_rejected_from_setup_wizard(mock_guild):
    """Non-admin or non-author is rejected by interaction_check."""
    admin_id = 111111
    intruder_id = 999999
    bot = MagicMock()

    view = ServerSetupView(
        bot=bot,
        author_id=admin_id,
        guild=mock_guild,
        pending_prefix="?",
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = intruder_id
    interaction.user.guild_permissions.administrator = False
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    allowed = await view.interaction_check(interaction)
    assert allowed is False
    interaction.response.send_message.assert_awaited_once()
    assert "not for you" in interaction.response.send_message.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_database_failure_reports_error_without_false_success(mock_guild):
    """If DB operation fails, wizard reports failure and does not claim success."""
    admin_id = 111111
    bot = MagicMock()
    bot.guild_repo = MagicMock()
    bot.guild_repo.set_prefix = AsyncMock(side_effect=RuntimeError("SQLite connection lost"))

    view = ServerSetupView(
        bot=bot,
        author_id=admin_id,
        guild=mock_guild,
        pending_prefix="?",
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = admin_id
    interaction.user.guild_permissions.administrator = True
    interaction.guild = mock_guild
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await view.save_btn.callback(interaction)

    interaction.followup.send.assert_awaited_once()
    msg = str(interaction.followup.send.call_args)
    assert "failed" in msg.lower() or "error" in msg.lower()
    assert "verified and saved" not in msg.lower()


@pytest.mark.asyncio
async def test_timeout_disables_wizard_buttons(mock_guild):
    """On timeout, wizard buttons are disabled."""
    view = ServerSetupView(
        bot=MagicMock(),
        author_id=111111,
        guild=mock_guild,
    )
    assert any(not child.disabled for child in view.children)

    await view.on_timeout()
    assert all(child.disabled for child in view.children)


@pytest.mark.asyncio
async def test_preview_btn_diff_display(mock_guild):
    """Clicking Dry-Run Diff Preview sends an ephemeral preview without making changes."""
    admin_id = 111111
    bot = MagicMock()
    bot.guild_repo = MagicMock()
    bot.guild_repo.get_prefix = AsyncMock(return_value="!")

    mock_guild.roles = []
    view = ServerSetupView(
        bot=bot,
        author_id=admin_id,
        guild=mock_guild,
        pending_prefix="?",
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = admin_id
    interaction.user.guild_permissions.administrator = True
    interaction.guild = mock_guild
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await view.preview_btn.callback(interaction)

    interaction.response.send_message.assert_awaited_once()
    kwargs = interaction.response.send_message.call_args[1]
    assert kwargs.get("ephemeral") is True
    embed = kwargs.get("embed")
    assert "Dry-Run Diff Preview" in embed.title
    assert "Prefix" in embed.description
    assert "[UPDATE]" in embed.description


@pytest.mark.asyncio
async def test_rollback_restores_previous_configuration(mock_guild):
    """Setup rollback restores pre-apply snapshot."""
    from bot.core.context import UnifiedContext
    admin_id = 111111
    bot = MagicMock()
    bot.guild_repo = MagicMock()
    bot.guild_repo.set_prefix = AsyncMock(return_value=True)
    bot._guild_setup_snapshots = {
        mock_guild.id: {
            "prefix": "!",
            "system_channel_id": None,
            "afk_channel_id": None,
            "timestamp": "2026-11-16T12:00:00Z",
        }
    }

    wizard = SetupWizard(bot)
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = mock_guild
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.guild_permissions.administrator = True
    ctx.defer = AsyncMock()
    ctx.reply = AsyncMock()

    await wizard._execute_setuprollback(ctx)

    bot.guild_repo.set_prefix.assert_awaited_once_with(mock_guild.id, "!")
    ctx.reply.assert_awaited_once()
    embed = ctx.reply.call_args[1].get("embed")
    assert "Setup Configuration Reverted" in embed.title

