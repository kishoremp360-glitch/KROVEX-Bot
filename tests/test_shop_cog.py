"""Comprehensive automated tests for Server Shop and Marketplace."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import pytest
import discord

from bot.cogs.shop.cog import ShopCog
from bot.core.context import UnifiedContext
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import EconomyRepository, ShopRepository


def run_async(coro):
    return asyncio.run(coro)


def test_shop_item_creation_and_editing(tmp_path: Path):
    """Verify item creation, updating, and removal."""
    async def _test():
        db_file = tmp_path / "test_shop_crud.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        eco_repo = EconomyRepository(manager)
        shop_repo = ShopRepository(manager)

        guild_id = 1001

        # Create item with limited stock
        item_id = await shop_repo.create_item(
            guild_id,
            name="VIP Pass",
            description="Grants exclusive lounge access",
            price=1500,
            stock=5,
        )
        assert item_id > 0

        item = await shop_repo.get_item(item_id)
        assert item["name"] == "VIP Pass"
        assert item["price"] == 1500
        assert item["stock"] == 5

        # Edit item
        await shop_repo.edit_item(item_id, price=1200, stock=10)
        edited = await shop_repo.get_item(item_id)
        assert edited["price"] == 1200
        assert edited["stock"] == 10

        # Delete item
        ok = await shop_repo.delete_item(guild_id, item_id)
        assert ok is True
        assert await shop_repo.get_item(item_id) is None

        await manager.close()

    run_async(_test())


def test_shop_purchase_and_stock_decrement(tmp_path: Path):
    """Verify purchase atomic debit, stock reduction, and inventory integration."""
    async def _test():
        db_file = tmp_path / "test_shop_buy.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        eco_repo = EconomyRepository(manager)
        shop_repo = ShopRepository(manager)

        guild_id = 1001
        user_id = 2001

        item_id = await shop_repo.create_item(guild_id, "Magic Wand", "Casts cool spells", 500, stock=2)

        # Attempt purchase with 0 balance -> should fail
        ok, msg, _ = await shop_repo.buy_item(guild_id, user_id, item_id)
        assert ok is False
        assert "Insufficient funds" in msg

        # Grant balance and buy 1st unit
        await eco_repo.add_money(guild_id, user_id, 1000, "wallet")
        ok, msg, pdata = await shop_repo.buy_item(guild_id, user_id, item_id)
        assert ok is True

        bal = await eco_repo.get_balance(guild_id, user_id)
        assert bal["wallet"] == 500  # 1000 - 500

        item = await shop_repo.get_item(item_id)
        assert item["stock"] == 1  # 2 - 1

        inv = await eco_repo.get_inventory(guild_id, user_id)
        assert len(inv) == 1
        assert inv[0]["name"] == "Magic Wand"
        assert inv[0]["quantity"] == 1

        # Buy 2nd unit -> stock becomes 0
        ok, msg, _ = await shop_repo.buy_item(guild_id, user_id, item_id)
        assert ok is True
        item = await shop_repo.get_item(item_id)
        assert item["stock"] == 0

        # Buy 3rd unit -> out of stock
        await eco_repo.add_money(guild_id, user_id, 1000, "wallet")
        ok, msg, _ = await shop_repo.buy_item(guild_id, user_id, item_id)
        assert ok is False
        assert "out of stock" in msg.lower()

        await manager.close()

    run_async(_test())


def test_shop_sell_and_refund(tmp_path: Path):
    """Verify selling items from inventory and staff refund processing."""
    async def _test():
        db_file = tmp_path / "test_shop_refund.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        eco_repo = EconomyRepository(manager)
        shop_repo = ShopRepository(manager)

        guild_id = 1001
        user_id = 3001

        item_id = await shop_repo.create_item(guild_id, "Shield", "Defense gear", 400, stock=-1)
        await eco_repo.add_money(guild_id, user_id, 1000, "wallet")

        ok, msg, pdata = await shop_repo.buy_item(guild_id, user_id, item_id)
        assert ok is True
        purchase_id = pdata["purchase_id"]

        # Sell item back to market (50% refund = 200 coins)
        ok_sell, msg_sell, coins = await shop_repo.sell_item(guild_id, user_id, item_id, refund_rate=0.5)
        assert ok_sell is True
        assert coins == 200
        bal = await eco_repo.get_balance(guild_id, user_id)
        assert bal["wallet"] == 800  # 1000 - 400 + 200

        # Refund previous purchase
        ok_ref, msg_ref = await shop_repo.refund_purchase(guild_id, purchase_id)
        assert ok_ref is True
        assert "restored" in msg_ref

        await manager.close()

    run_async(_test())
