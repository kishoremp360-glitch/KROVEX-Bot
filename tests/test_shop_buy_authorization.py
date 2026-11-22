"""Unit tests for Finding P1-02: ShopBuyConfirmView authorization and double-purchase protection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.shop.views import ShopBuyConfirmView


@pytest.fixture
def sample_item():
    return {
        "item_id": 42,
        "name": "VIP Badge",
        "price": 500,
        "stock": 10,
        "role_id": None,
        "description": "Exclusive badge",
    }


@pytest.mark.asyncio
async def test_unauthorized_user_rejected_from_shop_buy(sample_item):
    """An unauthorized user clicking Buy Item must be rejected without calling repo."""
    buyer_id = 111111
    intruder_id = 999999

    view = ShopBuyConfirmView(sample_item, buyer_id=buyer_id)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = intruder_id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    # interaction_check must return False
    allowed = await view.interaction_check(interaction)
    assert allowed is False
    interaction.response.send_message.assert_awaited_once()
    assert "not for you" in interaction.response.send_message.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_authorized_user_allowed_shop_buy(sample_item):
    """The authorized purchaser passes interaction_check and completes transaction."""
    buyer_id = 111111

    view = ShopBuyConfirmView(sample_item, buyer_id=buyer_id)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = buyer_id
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 12345
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()

    bot = MagicMock()
    bot.shop_repo = MagicMock()
    bot.shop_repo.buy_item = AsyncMock(return_value=(True, "Purchased VIP Badge for 500 coins", {}))
    interaction.client = bot

    allowed = await view.interaction_check(interaction)
    assert allowed is True

    button = MagicMock(spec=discord.ui.Button)
    await view.buy_btn.callback(interaction)

    bot.shop_repo.buy_item.assert_awaited_once_with(12345, buyer_id, 42)
    interaction.response.edit_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_clicks_prevented(sample_item):
    """Second click on buy_btn must be rejected by double-purchase guard."""
    buyer_id = 111111

    view = ShopBuyConfirmView(sample_item, buyer_id=buyer_id)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = buyer_id
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 12345
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()

    bot = MagicMock()
    bot.shop_repo = MagicMock()
    bot.shop_repo.buy_item = AsyncMock(return_value=(True, "Success", {}))
    interaction.client = bot

    # First click
    await view.buy_btn.callback(interaction)
    assert bot.shop_repo.buy_item.call_count == 1

    # Second click
    interaction2 = MagicMock(spec=discord.Interaction)
    interaction2.user = interaction.user
    interaction2.guild = interaction.guild
    interaction2.response = MagicMock()
    interaction2.response.send_message = AsyncMock()
    interaction2.client = bot

    await view.buy_btn.callback(interaction2)
    # Repo must NOT be called a second time
    assert bot.shop_repo.buy_item.call_count == 1
    interaction2.response.send_message.assert_awaited_once()
    assert "already been processed" in interaction2.response.send_message.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_timeout_disables_components(sample_item):
    """View timeout must disable all child buttons."""
    view = ShopBuyConfirmView(sample_item, buyer_id=111111)
    assert any(not child.disabled for child in view.children)

    await view.on_timeout()
    assert all(child.disabled for child in view.children)
