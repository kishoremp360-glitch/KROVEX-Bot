"""Comprehensive automated tests for Server Virtual Economy System."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import pytest
import discord

from bot.cogs.economy.cog import EconomyCog
from bot.core.context import UnifiedContext
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import EconomyRepository


def run_async(coro):
    return asyncio.run(coro)


def test_economy_deposit_withdraw(tmp_path: Path):
    """Verify wallet to bank deposit and withdrawal operations."""
    async def _test():
        db_file = tmp_path / "test_economy_dep.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = EconomyRepository(manager)

        guild_id = 1001
        user_id = 2001

        # Give starter wallet balance
        await repo.add_money(guild_id, user_id, 1000, "wallet")
        bal = await repo.get_balance(guild_id, user_id)
        assert bal["wallet"] == 1000
        assert bal["bank"] == 0

        # Deposit 400
        ok, msg, w, b = await repo.deposit(guild_id, user_id, 400)
        assert ok is True
        assert w == 600
        assert b == 400

        # Overdraw wallet
        ok, msg, w, b = await repo.deposit(guild_id, user_id, 700)
        assert ok is False
        assert "Insufficient funds" in msg

        # Withdraw 250
        ok, msg, w, b = await repo.withdraw(guild_id, user_id, 250)
        assert ok is True
        assert w == 850
        assert b == 150

        # Overdraw bank
        ok, msg, w, b = await repo.withdraw(guild_id, user_id, 300)
        assert ok is False

        await manager.close()

    run_async(_test())


def test_economy_transfer_and_ledger(tmp_path: Path):
    """Verify atomic P2P transfers and transaction recording."""
    async def _test():
        db_file = tmp_path / "test_economy_tr.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = EconomyRepository(manager)

        guild_id = 1001
        user_a = 2001
        user_b = 2002

        await repo.add_money(guild_id, user_a, 500, "wallet")

        # Transfer 200 from A to B
        ok, msg = await repo.transfer(guild_id, user_a, user_b, 200)
        assert ok is True

        bal_a = await repo.get_balance(guild_id, user_a)
        bal_b = await repo.get_balance(guild_id, user_b)
        assert bal_a["wallet"] == 300
        assert bal_b["wallet"] == 200

        # Transfer more than balance -> failure
        ok, msg = await repo.transfer(guild_id, user_a, user_b, 400)
        assert ok is False

        # Check ledger records
        logs = await repo.get_transaction_logs(guild_id)
        assert len(logs) >= 2

        await manager.close()

    run_async(_test())


def test_economy_daily_claim_and_cooldown(tmp_path: Path):
    """Verify daily reward claim, streak increment, and duplicate claim rejection."""
    async def _test():
        db_file = tmp_path / "test_economy_daily.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = EconomyRepository(manager)

        guild_id = 1001
        user_id = 3001

        ok, msg, reward, streak = await repo.claim_daily(guild_id, user_id)
        assert ok is True
        assert reward >= 100
        assert streak == 1

        bal = await repo.get_balance(guild_id, user_id)
        assert bal["wallet"] == reward

        # Immediate second claim -> rejected by 24h cooldown
        ok2, msg2, reward2, streak2 = await repo.claim_daily(guild_id, user_id)
        assert ok2 is False
        assert "already claimed" in msg2.lower()
        assert reward2 == 0

        await manager.close()

    run_async(_test())


def test_economy_admin_controls(tmp_path: Path):
    """Verify admin add, set, remove, and reset controls."""
    async def _test():
        db_file = tmp_path / "test_economy_adm.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = EconomyRepository(manager)

        guild_id = 1001
        user_id = 4001

        # Admin set
        await repo.set_money(guild_id, user_id, wallet=5000, bank=2000)
        bal = await repo.get_balance(guild_id, user_id)
        assert bal["wallet"] == 5000
        assert bal["bank"] == 2000

        # Admin remove
        rem = await repo.remove_money(guild_id, user_id, 1000, "wallet")
        assert rem == 4000

        # Reset single user
        await repo.reset_economy(guild_id, user_id)
        bal_reset = await repo.get_balance(guild_id, user_id)
        assert bal_reset["wallet"] == 0
        assert bal_reset["bank"] == 0

        await manager.close()

    run_async(_test())
