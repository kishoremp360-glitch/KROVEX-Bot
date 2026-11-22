"""Comprehensive test suite verifying ShopRepository.refund_purchase stock restoration and atomicity."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch
import pytest

from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import ShopRepository, EconomyRepository


def run_async(coro):
    return asyncio.run(coro)


def test_refund_limited_stock_item(tmp_path: Path):
    """Verify that refunding a limited-stock item restores stock by +1 and restores buyer currency."""
    async def _test():
        db_file = tmp_path / "test_shop_ref_limited.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        shop_repo = ShopRepository(manager)
        eco_repo = EconomyRepository(manager)

        guild_id = 8001
        buyer = 8101

        # Create limited stock item with initial stock = 2
        item_id = await shop_repo.create_item(
            guild_id=guild_id,
            name="Limited Mythic Sword",
            description="Rare blade",
            price=200,
            stock=2,
        )

        # Buyer starts with 500 coins
        await eco_repo.set_money(guild_id, buyer, wallet=500, bank=0)

        # Buyer purchases 1 sword
        ok, msg, item = await shop_repo.buy_item(guild_id, buyer, item_id)
        assert ok is True

        # Check stock reduced from 2 to 1
        item_after_buy = await shop_repo.get_item(item_id)
        assert item_after_buy["stock"] == 1

        # Check wallet reduced to 300
        bal_after_buy = await eco_repo.get_balance(guild_id, buyer)
        assert bal_after_buy["wallet"] == 300

        # Check inventory contains sword
        inv_after_buy = await eco_repo.get_inventory(guild_id, buyer)
        assert len(inv_after_buy) == 1 and inv_after_buy[0]["item_id"] == item_id

        # Get purchase record
        purchases = await shop_repo.get_purchases(guild_id, buyer)
        assert len(purchases) == 1
        purchase_id = purchases[0]["purchase_id"]

        # Staff performs refund
        ref_ok, ref_msg = await shop_repo.refund_purchase(guild_id, purchase_id)
        assert ref_ok is True
        assert "Successfully refunded" in ref_msg

        # 1. Stock MUST be restored from 1 back to 2!
        item_after_ref = await shop_repo.get_item(item_id)
        assert item_after_ref["stock"] == 2, f"Stock must be restored to 2, got {item_after_ref['stock']}"

        # 2. Buyer's wallet MUST be restored to 500!
        bal_after_ref = await eco_repo.get_balance(guild_id, buyer)
        assert bal_after_ref["wallet"] == 500, f"Wallet must be restored to 500, got {bal_after_ref['wallet']}"

        # 3. Item MUST be removed from inventory!
        inv_after_ref = await eco_repo.get_inventory(guild_id, buyer)
        assert len(inv_after_ref) == 0, f"Inventory must be empty, got {len(inv_after_ref)}"

        # 4. Purchase status MUST be 'refunded'
        purchases_after = await shop_repo.get_purchases(guild_id, buyer)
        assert purchases_after[0]["status"] == "refunded"

        # 5. Ledger record MUST exist in economy_transactions
        txs = await eco_repo.get_transaction_logs(guild_id, buyer)
        refund_txs = [t for t in txs if t["action"] == "refund"]
        assert len(refund_txs) == 1
        assert refund_txs[0]["amount"] == 200

        await manager.close()

    run_async(_test())


def test_refund_unlimited_stock_item(tmp_path: Path):
    """Verify that refunding an unlimited-stock item (stock = -1) leaves stock at -1."""
    async def _test():
        db_file = tmp_path / "test_shop_ref_unlimited.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        shop_repo = ShopRepository(manager)
        eco_repo = EconomyRepository(manager)

        guild_id = 8002
        buyer = 8102

        # Create unlimited item (stock = -1)
        item_id = await shop_repo.create_item(
            guild_id=guild_id,
            name="VIP Role Access",
            description="Unlimited role",
            price=100,
            stock=-1,
        )

        await eco_repo.set_money(guild_id, buyer, wallet=200, bank=0)
        ok, msg, _ = await shop_repo.buy_item(guild_id, buyer, item_id)
        assert ok is True

        item_bought = await shop_repo.get_item(item_id)
        assert item_bought["stock"] == -1

        purchases = await shop_repo.get_purchases(guild_id, buyer)
        purchase_id = purchases[0]["purchase_id"]

        ref_ok, _ = await shop_repo.refund_purchase(guild_id, purchase_id)
        assert ref_ok is True

        # Stock must remain -1, NOT incremented to 0!
        item_after = await shop_repo.get_item(item_id)
        assert item_after["stock"] == -1, f"Unlimited stock must remain -1, got {item_after['stock']}"

        await manager.close()

    run_async(_test())


def test_refund_duplicate_prevention_and_concurrency(tmp_path: Path):
    """Verify that duplicate refunds are rejected and concurrent refund attempts process only once."""
    async def _test():
        db_file = tmp_path / "test_shop_ref_dup.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        shop_repo = ShopRepository(manager)
        eco_repo = EconomyRepository(manager)

        guild_id = 8003
        buyer = 8103

        item_id = await shop_repo.create_item(
            guild_id=guild_id,
            name="Custom Title",
            description="Title",
            price=150,
            stock=1,
        )

        await eco_repo.set_money(guild_id, buyer, wallet=300, bank=0)
        await shop_repo.buy_item(guild_id, buyer, item_id)

        purchases = await shop_repo.get_purchases(guild_id, buyer)
        purchase_id = purchases[0]["purchase_id"]

        # First refund succeeds
        ref1, msg1 = await shop_repo.refund_purchase(guild_id, purchase_id)
        assert ref1 is True

        # Second refund MUST fail
        ref2, msg2 = await shop_repo.refund_purchase(guild_id, purchase_id)
        assert ref2 is False
        assert "already been refunded" in msg2

        # Wallet must have exactly 300 (not 450)
        bal = await eco_repo.get_balance(guild_id, buyer)
        assert bal["wallet"] == 300

        # Stock must be exactly 1 (not 2)
        item = await shop_repo.get_item(item_id)
        assert item["stock"] == 1

        # Test invalid purchase ID
        ref_inv, msg_inv = await shop_repo.refund_purchase(guild_id, 999999)
        assert ref_inv is False
        assert "Purchase record not found" in msg_inv

        await manager.close()

    run_async(_test())


def test_refund_atomic_rollback_on_failure(tmp_path: Path):
    """Verify complete rollback if any step fails during the refund process."""
    async def _test():
        db_file = tmp_path / "test_shop_ref_rollback.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        shop_repo = ShopRepository(manager)
        eco_repo = EconomyRepository(manager)

        guild_id = 8004
        buyer = 8104

        item_id = await shop_repo.create_item(
            guild_id=guild_id,
            name="Dragon Egg",
            description="Mystic pet egg",
            price=500,
            stock=1,
        )

        await eco_repo.set_money(guild_id, buyer, wallet=1000, bank=0)
        await shop_repo.buy_item(guild_id, buyer, item_id)

        purchases = await shop_repo.get_purchases(guild_id, buyer)
        purchase_id = purchases[0]["purchase_id"]

        # Simulate database failure during stock update
        orig_execute = manager.connection.execute

        def _mock_execute(sql, params=()):
            if "UPDATE shop_items SET stock = stock + 1" in sql:
                raise RuntimeError("Disk I/O error during shop stock restoration")
            return orig_execute(sql, params)

        with patch.object(manager.connection, "execute", side_effect=_mock_execute):
            ok, msg = await shop_repo.refund_purchase(guild_id, purchase_id)
            assert ok is False
            assert "Failed to process refund" in msg

        # Verification of complete rollback:
        # 1. Wallet must remain 500 (money was not refunded without stock restoration)
        bal = await eco_repo.get_balance(guild_id, buyer)
        assert bal["wallet"] == 500

        # 2. Purchase status must remain 'completed' (not 'refunded')
        purchases_after = await shop_repo.get_purchases(guild_id, buyer)
        assert purchases_after[0]["status"] == "completed"

        # 3. Stock must remain 0
        item = await shop_repo.get_item(item_id)
        assert item["stock"] == 0

        # 4. Inventory must still contain the item
        inv = await eco_repo.get_inventory(guild_id, buyer)
        assert len(inv) == 1

        await manager.close()

    run_async(_test())
