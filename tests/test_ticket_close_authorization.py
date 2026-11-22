"""Unit tests for Finding P1-04: TicketCloseConfirmView authorization and double-close protection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.tickets.views import TicketCloseConfirmView


@pytest.fixture
def mock_ticket_channel():
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 88888
    channel.name = "ticket-0042"
    channel.send = AsyncMock()
    channel.delete = AsyncMock()
    return channel


@pytest.mark.asyncio
async def test_unauthorized_member_rejected_from_closing_ticket(mock_ticket_channel):
    """An unauthorized member must be rejected by interaction_check without closing ticket."""
    creator_id = 111111
    intruder_id = 999999

    view = TicketCloseConfirmView(creator_id=creator_id)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = intruder_id
    interaction.user.roles = []
    interaction.user.guild_permissions.administrator = False
    interaction.user.guild_permissions.manage_channels = False
    interaction.channel_id = mock_ticket_channel.id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    bot = MagicMock()
    bot.ticket_repo = MagicMock()
    bot.ticket_repo.get_ticket_by_channel = AsyncMock(return_value={"creator_id": creator_id, "status": "open"})
    bot.ticket_repo.get_settings = AsyncMock(return_value={"staff_role_id": None})
    interaction.client = bot

    allowed = await view.interaction_check(interaction)
    assert allowed is False
    interaction.response.send_message.assert_awaited_once()
    assert "only the ticket creator or authorized support staff" in interaction.response.send_message.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_ticket_creator_allowed_to_close(mock_ticket_channel):
    """The ticket creator passes interaction_check."""
    creator_id = 111111

    view = TicketCloseConfirmView(creator_id=creator_id)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = creator_id
    interaction.user.roles = []
    interaction.user.guild_permissions.administrator = False
    interaction.user.guild_permissions.manage_channels = False
    interaction.channel_id = mock_ticket_channel.id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    bot = MagicMock()
    bot.ticket_repo = MagicMock()
    interaction.client = bot

    allowed = await view.interaction_check(interaction)
    assert allowed is True


@pytest.mark.asyncio
async def test_staff_role_member_allowed_to_close(mock_ticket_channel):
    """A member with the configured staff_role_id passes interaction_check."""
    creator_id = 111111
    staff_id = 222222
    staff_role_id = 777777

    view = TicketCloseConfirmView(creator_id=creator_id)

    staff_role = MagicMock(spec=discord.Role)
    staff_role.id = staff_role_id

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = staff_id
    interaction.user.roles = [staff_role]
    interaction.user.guild_permissions.administrator = False
    interaction.user.guild_permissions.manage_channels = False
    interaction.channel_id = mock_ticket_channel.id
    interaction.guild_id = 12345
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    bot = MagicMock()
    bot.ticket_repo = MagicMock()
    bot.ticket_repo.get_ticket_by_channel = AsyncMock(return_value={"creator_id": creator_id, "status": "open"})
    bot.ticket_repo.get_settings = AsyncMock(return_value={"staff_role_id": staff_role_id})
    interaction.client = bot

    allowed = await view.interaction_check(interaction)
    assert allowed is True


@pytest.mark.asyncio
async def test_duplicate_close_clicks_prevented(mock_ticket_channel):
    """Repeated clicks on confirm_btn must be blocked by the concurrency guard."""
    creator_id = 111111
    view = TicketCloseConfirmView(creator_id=creator_id)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = creator_id
    interaction.channel = mock_ticket_channel
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.name = "Test Guild"
    interaction.guild_id = 12345
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    bot = MagicMock()
    bot.ticket_repo = MagicMock()
    bot.ticket_repo.get_ticket_by_channel = AsyncMock(return_value={"creator_id": creator_id, "status": "open"})
    bot.ticket_repo.get_settings = AsyncMock(return_value={})
    bot.ticket_repo.close_ticket = AsyncMock()
    bot.dm_queue_service = MagicMock()
    bot.dm_queue_service.enqueue = AsyncMock()
    interaction.client = bot

    # First click
    await view.confirm_btn.callback(interaction)
    assert bot.ticket_repo.close_ticket.call_count == 1

    # Second click
    interaction2 = MagicMock(spec=discord.Interaction)
    interaction2.user = interaction.user
    interaction2.channel = interaction.channel
    interaction2.response = MagicMock()
    interaction2.response.send_message = AsyncMock()
    interaction2.client = bot

    await view.confirm_btn.callback(interaction2)
    # Must NOT call close_ticket a second time
    assert bot.ticket_repo.close_ticket.call_count == 1
    interaction2.response.send_message.assert_awaited_once()
    assert "already being closed" in interaction2.response.send_message.call_args[0][0].lower()
