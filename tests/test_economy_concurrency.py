"""Comprehensive concurrency and atomicity tests for EconomyRepository.transfer."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch
import pytest

from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import EconomyRepository


def run_async(coro):
    return asyncio.run(coro)


def test_concurrent_transfers_two_competing_for_one(tmp_path: Path):
    """Verify that two simultaneous transfers from an account that can afford only one results in exactly one success."""
    async def _test():
        db_file = tmp_path / "test_eco_race_two.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = EconomyRepository(manager)

        guild_id = 7001
        sender = 8001
        recipient_1 = 8002
        recipient_2 = 8003

        # Fund sender with exactly 100 coins
        await repo.set_money(guild_id, sender, wallet=100, bank=0)

        # Dispatch 2 simultaneous transfers of 100 coins
        results = await asyncio.gather(
            repo.transfer(guild_id, sender, recipient_1, 100),
            repo.transfer(guild_id, sender, recipient_2, 100),
            return_exceptions=False,
        )

        successes = [r for r in results if r[0] is True]
        failures = [r for r in results if r[0] is False]

        # Exactly 1 must succeed, exactly 1 must fail
        assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"
        assert len(failures) == 1, f"Expected 1 failure, got {len(failures)}"

        # Verify balances: sender must have 0, never negative
        sender_bal = await repo.get_balance(guild_id, sender)
        assert sender_bal["wallet"] == 0, f"Sender wallet must be 0, got {sender_bal['wallet']}"

        # Recipient balances: exactly one has 100, other has 0
        r1_bal = await repo.get_balance(guild_id, recipient_1)
        r2_bal = await repo.get_balance(guild_id, recipient_2)
        total_credited = r1_bal["wallet"] + r2_bal["wallet"]
        assert total_credited == 100, f"Total credited must be 100, got {total_credited}"

        # Ledger check: exactly 2 transfer entries (1 out, 1 in)
        txs = await repo.get_transaction_logs(guild_id, limit=20)
        transfer_txs = [t for t in txs if t["action"].startswith("transfer")]
        assert len(transfer_txs) == 2, f"Ledger must have 2 transfer entries, got {len(transfer_txs)}"

        await manager.close()

    run_async(_test())


def test_concurrent_transfers_many_simultaneous(tmp_path: Path):
    """Verify multiple simultaneous transfers (10 simultaneous tasks competing for 250 coins in chunks of 50)."""
    async def _test():
        db_file = tmp_path / "test_eco_race_many.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = EconomyRepository(manager)

        guild_id = 7002
        sender = 9001
        recipient = 9002

        # Sender has 250 coins, each transfer is 50 coins. Exactly 5 can succeed.
        await repo.set_money(guild_id, sender, wallet=250, bank=0)
        await repo.set_money(guild_id, recipient, wallet=0, bank=0)

        # Launch 10 simultaneous transfers
        async def _do_transfer():
            return await repo.transfer(guild_id, sender, recipient, 50)

        results = await asyncio.gather(*[_do_transfer() for _ in range(10)])

        successes = [r for r in results if r[0] is True]
        failures = [r for r in results if r[0] is False]

        assert len(successes) == 5, f"Expected exactly 5 successes, got {len(successes)}"
        assert len(failures) == 5, f"Expected exactly 5 failures, got {len(failures)}"

        sender_bal = await repo.get_balance(guild_id, sender)
        rec_bal = await repo.get_balance(guild_id, recipient)

        assert sender_bal["wallet"] == 0
        assert rec_bal["wallet"] == 250

        # Ledger matches actual transactions (5 transfers * 2 entries = 10 entries)
        txs = await repo.get_transaction_logs(guild_id, limit=50)
        transfer_txs = [t for t in txs if t["action"].startswith("transfer")]
        assert len(transfer_txs) == 10, f"Expected 10 transfer records, got {len(transfer_txs)}"

        await manager.close()

    run_async(_test())


def test_transfer_insufficient_balance_and_negative_prevention(tmp_path: Path):
    """Verify that insufficient balance is rejected and negative wallet balance is impossible."""
    async def _test():
        db_file = tmp_path / "test_eco_insuff.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = EconomyRepository(manager)

        guild_id = 7003
        sender = 9003
        recipient = 9004

        await repo.set_money(guild_id, sender, wallet=40, bank=0)

        # Attempt to transfer 50 when holding 40
        ok, msg = await repo.transfer(guild_id, sender, recipient, 50)
        assert ok is False
        assert "Insufficient wallet balance" in msg

        # Attempt transfer with negative or 0 amount
        ok_zero, _ = await repo.transfer(guild_id, sender, recipient, 0)
        assert ok_zero is False
        ok_neg, _ = await repo.transfer(guild_id, sender, recipient, -100)
        assert ok_neg is False

        # Self-transfer prevention
        ok_self, msg_self = await repo.transfer(guild_id, sender, sender, 10)
        assert ok_self is False
        assert "cannot transfer currency to yourself" in msg_self

        # Balances untouched
        sender_bal = await repo.get_balance(guild_id, sender)
        assert sender_bal["wallet"] == 40

        await manager.close()

    run_async(_test())


def test_transfer_atomic_rollback_on_failure(tmp_path: Path):
    """Verify that if recipient credit or ledger logging fails, sender's debit is rolled back completely."""
    async def _test():
        db_file = tmp_path / "test_eco_rollback.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = EconomyRepository(manager)

        guild_id = 7004
        sender = 9005
        recipient = 9006

        await repo.set_money(guild_id, sender, wallet=300, bank=0)
        await repo.set_money(guild_id, recipient, wallet=50, bank=0)

        # Force an error during the recipient update phase
        orig_execute = manager.connection.execute

        def _mock_execute(sql, params=()):
            if "UPDATE server_economy SET wallet = wallet +" in sql:
                raise RuntimeError("Simulated database failure during recipient credit")
            return orig_execute(sql, params)

        with patch.object(manager.connection, "execute", side_effect=_mock_execute):
            ok, msg = await repo.transfer(guild_id, sender, recipient, 100)
            assert ok is False
            assert "Failed to complete transfer" in msg

        # Ensure complete rollback: sender still has 300, recipient still has 50
        sender_bal = await repo.get_balance(guild_id, sender)
        rec_bal = await repo.get_balance(guild_id, recipient)
        assert sender_bal["wallet"] == 300, f"Sender wallet must remain 300 after rollback, got {sender_bal['wallet']}"
        assert rec_bal["wallet"] == 50, f"Recipient wallet must remain 50 after rollback, got {rec_bal['wallet']}"

        # No transfer ledger entries should exist after rollback
        txs = await repo.get_transaction_logs(guild_id)
        transfer_txs = [t for t in txs if t["action"].startswith("transfer")]
        assert len(transfer_txs) == 0, f"Expected 0 transfer records, got {len(transfer_txs)}"

        await manager.close()

    run_async(_test())
