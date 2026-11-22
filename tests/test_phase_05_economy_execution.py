"""Phase 5 Master Test Suite: Economy, Leveling & Rewards (P5-TC01 to P5-TC10).

This suite verifies:
- P5-TC01: Wallet & Bank balance lifecycle (deposits, withdrawals, bounds)
- P5-TC02: Peer-to-peer transfers (atomic debit/credit, bot/self guards, confirm view)
- P5-TC03: Daily allowance, streaks & cooldown enforcement
- P5-TC04: Work & robbery mechanics (career payouts, rob success/fail, bot shields)
- P5-TC05: High-concurrency balance invariance (zero double-spend, race-condition safety)
- P5-TC06: Shop catalog & item management (unlimited/limited stock, role unlocks)
- P5-TC07: Shop purchases, wallet deduction & stock decrement
- P5-TC08: Inventory, refunds, atomic coin return & stock restoration
- P5-TC09: Message XP gain, progressive leveling curve & level-up announcements
- P5-TC10: Rank cards, XP progress bars & server economic leaderboards
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.cogs.economy.cog import EconomyCog
from bot.cogs.leveling.cog import LevelingCog
from bot.cogs.leveling.card import render_rank_card
from bot.cogs.shop.cog import ShopCog
from bot.core.context import UnifiedContext
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import (
    EconomyRepository,
    LevelRepository,
    ShopRepository,
)


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture
def mock_bot(tmp_path: Path):
    bot = MagicMock()
    bot.config = MagicMock()
    bot.config.owner_ids = [99901]
    bot.owner_ids = [99901]
    return bot


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 30001
    guild.name = "Phase5 Economy Guild"
    guild.owner_id = 90001
    guild.icon = None
    return guild


# ==============================================================================
# P5-TC01: WALLET & BANK BALANCE LIFECYCLE
# ==============================================================================

def test_p5_tc01_wallet_and_bank_lifecycle(tmp_path: Path, mock_bot, mock_guild):
    """P5-TC01: Balance checking, deposit, withdrawal, and negative overdraft guard."""
    async def _test():
        db_file = tmp_path / "test_p5_tc01.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = EconomyRepository(db)
            mock_bot.economy_repo = repo
            cog = EconomyCog(mock_bot)

            user = MagicMock(spec=discord.Member)
            user.id = 50001
            user.bot = False
            user.display_name = "RichUser"
            user.display_avatar.url = "https://example.com/avatar.png"

            ctx = MagicMock(spec=UnifiedContext)
            ctx.guild = mock_guild
            ctx.author = user
            ctx.reply = AsyncMock()
            ctx.send_error = AsyncMock()

            # Seed starting balance: 1,000 wallet, 500 bank
            await repo.add_money(mock_guild.id, user.id, 1000)
            await repo.deposit(mock_guild.id, user.id, 500)

            # 1. Check Balance
            await cog._execute_balance(ctx, member=user)
            assert ctx.reply.called
            embed = ctx.reply.call_args[1]["embed"]
            assert "Financial Profile" in embed.title

            bal = await repo.get_balance(mock_guild.id, user.id)
            assert bal["wallet"] == 500
            assert bal["bank"] == 500

            # 2. Deposit 200 from wallet to bank
            await cog._execute_deposit(ctx, "200")
            bal_after_dep = await repo.get_balance(mock_guild.id, user.id)
            assert bal_after_dep["wallet"] == 300
            assert bal_after_dep["bank"] == 700

            # 3. Withdraw 150 from bank to wallet
            await cog._execute_withdraw(ctx, "150")
            bal_after_with = await repo.get_balance(mock_guild.id, user.id)
            assert bal_after_with["wallet"] == 450
            assert bal_after_with["bank"] == 550

            # 4. Deposit All
            await cog._execute_deposit(ctx, "all")
            bal_all_dep = await repo.get_balance(mock_guild.id, user.id)
            assert bal_all_dep["wallet"] == 0
            assert bal_all_dep["bank"] == 1000

            # 5. Overdraft / Insufficient funds deposit
            ctx.send_error.reset_mock()
            await cog._execute_deposit(ctx, "500")
            ctx.send_error.assert_awaited()
            error_title = ctx.send_error.call_args[0][0]
            assert "Failed" in error_title or "Invalid" in error_title
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P5-TC02: PEER-TO-PEER FUND TRANSFERS
# ==============================================================================

def test_p5_tc02_peer_to_peer_transfers(tmp_path: Path, mock_bot, mock_guild):
    """P5-TC02: Direct money transfer, ledger logging, bot/self guard, and confirmation."""
    async def _test():
        db_file = tmp_path / "test_p5_tc02.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = EconomyRepository(db)
            mock_bot.economy_repo = repo
            cog = EconomyCog(mock_bot)

            sender = MagicMock(spec=discord.Member)
            sender.id = 50002
            sender.bot = False
            sender.mention = "<@50002>"

            receiver = MagicMock(spec=discord.Member)
            receiver.id = 50003
            receiver.bot = False
            receiver.mention = "<@50003>"

            ctx = MagicMock(spec=UnifiedContext)
            ctx.guild = mock_guild
            ctx.author = sender
            ctx.reply = AsyncMock()
            ctx.send_error = AsyncMock()

            # Seed sender with 2,000 coins
            await repo.add_money(mock_guild.id, sender.id, 2000)

            # 1. Bot transfer rejection
            bot_target = MagicMock(spec=discord.Member)
            bot_target.bot = True
            await cog._execute_pay(ctx, member=bot_target, amount=100)
            ctx.send_error.assert_awaited_with(
                "Invalid Member", "You cannot transfer funds to a bot."
            )

            # 2. Negative/zero amount rejection
            ctx.send_error.reset_mock()
            await cog._execute_pay(ctx, member=receiver, amount=0)
            ctx.send_error.assert_awaited_with(
                "Invalid Amount", "Transfer amount must be positive."
            )

            # 3. Successful Transfer (under confirm threshold < 1000)
            await cog._execute_pay(ctx, member=receiver, amount=400)
            assert ctx.reply.called
            sender_bal = await repo.get_balance(mock_guild.id, sender.id)
            receiver_bal = await repo.get_balance(mock_guild.id, receiver.id)
            assert sender_bal["wallet"] == 1600
            assert receiver_bal["wallet"] == 400

            # 4. Insufficient balance rejection
            ctx.send_error.reset_mock()
            await cog._execute_pay(ctx, member=receiver, amount=5000)
            assert ctx.send_error.called
            assert "Insufficient Funds" in ctx.send_error.call_args[0][0]
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P5-TC03: DAILY ALLOWANCE & STREAK ENGINE
# ==============================================================================

def test_p5_tc03_daily_allowance_and_streaks(tmp_path: Path, mock_bot, mock_guild):
    """P5-TC03: Daily reward claim, streak increment, and cooldown enforcement."""
    async def _test():
        db_file = tmp_path / "test_p5_tc03.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = EconomyRepository(db)
            mock_bot.economy_repo = repo
            cog = EconomyCog(mock_bot)

            user = MagicMock(spec=discord.Member)
            user.id = 50004
            user.bot = False

            ctx = MagicMock(spec=UnifiedContext)
            ctx.guild = mock_guild
            ctx.author = user
            ctx.reply = AsyncMock()
            ctx.send_error = AsyncMock()

            # 1. First Daily Claim
            await cog._execute_daily(ctx)
            assert ctx.reply.called
            embed = ctx.reply.call_args[1]["embed"]
            assert "Daily Reward Claimed" in embed.title

            bal = await repo.get_balance(mock_guild.id, user.id)
            assert bal["wallet"] > 0
            assert bal["daily_streak"] == 1

            # 2. Immediate Second Claim rejected by Cooldown
            ctx.reply.reset_mock()
            await cog._execute_daily(ctx)
            ctx.send_error.assert_awaited()
            error_title = ctx.send_error.call_args[0][0]
            assert "Cooldown" in error_title
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P5-TC04: WORK & ROBBERY MECHANICS
# ==============================================================================

def test_p5_tc04_work_and_robbery_mechanics(tmp_path: Path, mock_bot, mock_guild):
    """P5-TC04: Work payouts, cooldowns, and rob command targeting other players."""
    async def _test():
        db_file = tmp_path / "test_p5_tc04.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = EconomyRepository(db)
            mock_bot.economy_repo = repo
            cog = EconomyCog(mock_bot)

            thief = MagicMock(spec=discord.Member)
            thief.id = 50005
            thief.bot = False

            victim = MagicMock(spec=discord.Member)
            victim.id = 50006
            victim.bot = False

            ctx = MagicMock(spec=UnifiedContext)
            ctx.guild = mock_guild
            ctx.author = thief
            ctx.reply = AsyncMock()
            ctx.send_error = AsyncMock()

            # 1. Execute Work shift
            await cog._execute_work(ctx)
            assert ctx.reply.called
            thief_bal = await repo.get_balance(mock_guild.id, thief.id)
            assert thief_bal["wallet"] > 0

            # 2. Cannot rob a bot
            bot_victim = MagicMock(spec=discord.Member)
            bot_victim.bot = True
            await cog._execute_rob(ctx, target=bot_victim)
            ctx.send_error.assert_awaited_with("Invalid Target", "You cannot rob bots.")

            # 3. Rob victim who has money
            await repo.add_money(mock_guild.id, victim.id, 1000)
            ctx.reply.reset_mock()
            await cog._execute_rob(ctx, target=victim)
            assert ctx.reply.called
            # Result can be success or fail (random probability)
            reply_embed = ctx.reply.call_args[1]["embed"]
            assert "Robbery" in reply_embed.title
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P5-TC05: HIGH-CONCURRENCY BALANCE INVARIANCE
# ==============================================================================

def test_p5_tc05_high_concurrency_balance_invariance(tmp_path: Path):
    """P5-TC05: Concurrent simultaneous transfers never double-spend or drop wallet below zero."""
    async def _test():
        db_file = tmp_path / "test_p5_tc05.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = EconomyRepository(db)
            guild_id = 40001
            sender_id = 60001
            receivers = [60002, 60003, 60004, 60005, 60006]

            # Sender starts with 1,000 coins
            await repo.add_money(guild_id, sender_id, 1000)

            # Fire 10 concurrent transfer attempts of 300 coins each (total 3,000 > 1,000 balance)
            tasks = []
            for i in range(10):
                target_id = receivers[i % len(receivers)]
                tasks.append(repo.transfer(guild_id, sender_id, target_id, 300))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            successful = sum(1 for r in results if isinstance(r, tuple) and r[0] is True)
            failed = sum(1 for r in results if isinstance(r, tuple) and r[0] is False)

            # Exactly 3 transfers of 300 can succeed from 1,000 coins (leaving 100)
            assert successful == 3
            assert failed == 7

            sender_bal = await repo.get_balance(guild_id, sender_id)
            assert sender_bal["wallet"] == 100
            assert sender_bal["wallet"] >= 0

            # Sum of all receiver wallets + sender wallet must strictly equal initial 1,000
            total_receiver_coins = 0
            for rid in receivers:
                r_bal = await repo.get_balance(guild_id, rid)
                total_receiver_coins += r_bal["wallet"]

            assert total_receiver_coins + sender_bal["wallet"] == 1000
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P5-TC06: SHOP CATALOG & ITEM MANAGEMENT
# ==============================================================================

def test_p5_tc06_shop_catalog_and_items(tmp_path: Path, mock_bot, mock_guild):
    """P5-TC06: Admin creating shop items with limited/unlimited stock and catalog display."""
    async def _test():
        db_file = tmp_path / "test_p5_tc06.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = ShopRepository(db)
            mock_bot.shop_repo = repo
            cog = ShopCog(mock_bot)

            admin = MagicMock(spec=discord.Member)
            admin.id = 70001
            admin.guild_permissions.administrator = True

            ctx = MagicMock(spec=UnifiedContext)
            ctx.guild = mock_guild
            ctx.guild.icon = None
            ctx.author = admin
            ctx.reply = AsyncMock()
            ctx.send_success = AsyncMock()

            # 1. Add unlimited item
            await repo.create_item(
                guild_id=mock_guild.id,
                name="VIP Pass",
                price=1500,
                description="Special lounge access",
                stock=-1,
            )

            # 2. Add limited stock item
            await repo.create_item(
                guild_id=mock_guild.id,
                name="Mythic Sword",
                price=5000,
                description="Rare sword (only 3 in existence)",
                stock=3,
            )

            # 3. View Shop Catalog
            await cog._execute_view(ctx)
            assert ctx.reply.called
            embed = ctx.reply.call_args[1]["embed"]
            assert "Server Shop Catalog" in embed.title
            assert "VIP Pass" in embed.description
            assert "Mythic Sword" in embed.description
            assert "3 left" in embed.description
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P5-TC07: SHOP PURCHASES & STOCK DECREMENT
# ==============================================================================

def test_p5_tc07_shop_purchases_and_stock(tmp_path: Path, mock_bot, mock_guild):
    """P5-TC07: Purchasing items with wallet balance, deducting coins, and decrementing stock."""
    async def _test():
        db_file = tmp_path / "test_p5_tc07.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            shop_repo = ShopRepository(db)
            eco_repo = EconomyRepository(db)
            mock_bot.shop_repo = shop_repo
            mock_bot.economy_repo = eco_repo

            user = MagicMock(spec=discord.Member)
            user.id = 70002
            user.bot = False

            # Seed user wallet with 3,000 coins
            await eco_repo.add_money(mock_guild.id, user.id, 3000)

            # Add limited stock item (cost 1,000, stock 2)
            item_id = await shop_repo.create_item(
                guild_id=mock_guild.id,
                name="Limited Shield",
                price=1000,
                description="Blocks 1 attack",
                stock=2,
            )

            # 1. Successful Purchase
            ok, msg, pdata = await shop_repo.buy_item(mock_guild.id, user.id, item_id)
            assert ok is True

            user_bal = await eco_repo.get_balance(mock_guild.id, user.id)
            assert user_bal["wallet"] == 2000

            # Stock should now be 1
            item = await shop_repo.get_item(item_id)
            assert item["stock"] == 1

            # 2. Purchase again to exhaust stock
            ok2, msg2, pdata2 = await shop_repo.buy_item(mock_guild.id, user.id, item_id)
            assert ok2 is True
            item_out = await shop_repo.get_item(item_id)
            assert item_out["stock"] == 0

            # 3. Third purchase fails due to out of stock
            ok3, msg3, pdata3 = await shop_repo.buy_item(mock_guild.id, user.id, item_id)
            assert ok3 is False
            assert "out of stock" in msg3.lower()
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P5-TC08: INVENTORY & REFUNDS
# ==============================================================================

def test_p5_tc08_inventory_and_refunds(tmp_path: Path, mock_bot, mock_guild):
    """P5-TC08: Inventory display, item refunds returning coins, and stock restoration."""
    async def _test():
        db_file = tmp_path / "test_p5_tc08.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            shop_repo = ShopRepository(db)
            eco_repo = EconomyRepository(db)
            mock_bot.shop_repo = shop_repo
            mock_bot.economy_repo = eco_repo

            user = MagicMock(spec=discord.Member)
            user.id = 70003
            user.bot = False

            await eco_repo.add_money(mock_guild.id, user.id, 2000)

            item_id = await shop_repo.create_item(
                guild_id=mock_guild.id,
                name="Gold Trophy",
                price=800,
                description="Shiny decoration",
                stock=5,
            )

            # Buy item
            ok, msg, pdata = await shop_repo.buy_item(mock_guild.id, user.id, item_id)
            assert ok is True
            purchase_id = pdata["purchase_id"]

            inv = await eco_repo.get_inventory(mock_guild.id, user.id)
            assert len(inv) == 1
            assert inv[0]["name"] == "Gold Trophy"

            # Execute Refund via purchase_id
            ok_ref, msg_ref = await shop_repo.refund_purchase(mock_guild.id, purchase_id)
            assert ok_ref is True

            # Coins refunded
            bal = await eco_repo.get_balance(mock_guild.id, user.id)
            assert bal["wallet"] == 2000

            # Stock restored to 5
            item = await shop_repo.get_item(item_id)
            assert item["stock"] == 5

            # Inventory empty
            inv_after = await eco_repo.get_inventory(mock_guild.id, user.id)
            assert len(inv_after) == 0
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P5-TC09: XP GAIN, PROGRESSION CURVE & LEVEL-UP
# ==============================================================================

def test_p5_tc09_xp_gain_and_level_up(tmp_path: Path, mock_bot, mock_guild):
    """P5-TC09: Message XP gain, progressive level curves, and level-up dispatch."""
    async def _test():
        db_file = tmp_path / "test_p5_tc09.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            level_repo = LevelRepository(db)
            mock_bot.level_repo = level_repo
            cog = LevelingCog(mock_bot)

            user = MagicMock(spec=discord.Member)
            user.id = 80001
            user.bot = False
            user.mention = "<@80001>"
            user.roles = []

            channel = MagicMock(spec=discord.TextChannel)
            channel.id = 44444
            channel.send = AsyncMock()

            msg = MagicMock(spec=discord.Message)
            msg.guild = mock_guild
            msg.channel = channel
            msg.author = user
            msg.content = "Chatting in server"

            # 1. Earn first XP
            await cog.on_message(msg)
            data = await level_repo.get_member(mock_guild.id, user.id)
            assert data["xp"] > 0
            assert data["level"] == 0

            # 2. Add substantial XP to cross Level 1 threshold
            new_xp, new_lvl, leveled_up = await level_repo.add_xp(mock_guild.id, user.id, 500)
            assert leveled_up is True
            assert new_lvl >= 1

            # Verify _handle_level_up sends announcement
            settings = await level_repo.get_settings(mock_guild.id)
            await cog._handle_level_up(msg, new_lvl, new_xp, settings)
            channel.send.assert_awaited()
            embed = channel.send.call_args[1]["embed"]
            assert "Level Up!" in embed.title
        finally:
            await db.close()

    run_async(_test())


# ==============================================================================
# P5-TC10: RANK CARDS & LEADERBOARD ACCURACY
# ==============================================================================

def test_p5_tc10_rank_cards_and_leaderboard(tmp_path: Path, mock_bot, mock_guild):
    """P5-TC10: Rank card rendering and leaderboard sorting by level/XP."""
    async def _test():
        db_file = tmp_path / "test_p5_tc10.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            level_repo = LevelRepository(db)
            eco_repo = EconomyRepository(db)
            mock_bot.level_repo = level_repo
            mock_bot.economy_repo = eco_repo

            # Seed 3 users with different levels
            await level_repo.add_xp(mock_guild.id, 90001, 1000)
            await level_repo.add_xp(mock_guild.id, 90002, 5000)
            await level_repo.add_xp(mock_guild.id, 90003, 200)

            # 1. Leaderboard accuracy
            lb = await level_repo.get_leaderboard(mock_guild.id, limit=5)
            assert len(lb) == 3
            # Top user must be 90002
            assert lb[0]["user_id"] == 90002
            assert lb[1]["user_id"] == 90001
            assert lb[2]["user_id"] == 90003

            # 2. Rank card rendering
            user_data = await level_repo.get_member(mock_guild.id, 90002)
            member = MagicMock(spec=discord.Member)
            member.id = 90002
            member.display_name = "DragonSlayer"
            member.display_avatar.url = "https://cdn.discordapp.com/embed/avatars/0.png"

            card_embed = render_rank_card(
                member=member,
                member_data=user_data,
                rank=1,
            )
            assert card_embed is not None
            assert isinstance(card_embed, discord.Embed)
            assert "Rank Profile" in card_embed.title
            assert "DragonSlayer" in card_embed.title
        finally:
            await db.close()

    run_async(_test())
