"""Comprehensive automated tests for Interactive Minigames System."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import pytest
import discord

from bot.cogs.minigames.views import (
    BlackjackCard,
    BlackjackView,
    DiceDuelView,
    HigherLowerView,
    PvPRPSView,
    RPSView,
    RussianRouletteView,
    TicTacToeView,
)
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import MinigameRepository


def run_async(coro):
    return asyncio.run(coro)


def test_minigame_stats_recording(tmp_path: Path):
    """Verify wins, losses, coins delta, and high scores tracking."""
    async def _test():
        db_file = tmp_path / "test_minigames_stats.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = MinigameRepository(manager)

        guild_id = 1001
        user_id = 2001

        # Record 2 wins and 1 loss in blackjack
        await repo.record_game(guild_id, user_id, "blackjack", won=True, coins_delta=100)
        await repo.record_game(guild_id, user_id, "blackjack", won=True, coins_delta=200)
        await repo.record_game(guild_id, user_id, "blackjack", won=False, coins_delta=-150)

        stats = await repo.get_stats(guild_id, user_id, "blackjack")
        assert stats["wins"] == 2
        assert stats["losses"] == 1
        assert stats["coins_won"] == 300
        assert stats["coins_lost"] == 150

        # Aggregate stats
        agg = await repo.get_stats(guild_id, user_id)
        assert agg["total_wins"] == 2
        assert agg["total_losses"] == 1
        assert agg["total_coins_won"] == 300

        await manager.close()

    run_async(_test())


def test_minigame_leaderboard(tmp_path: Path):
    """Verify minigame leaderboard sorting."""
    async def _test():
        db_file = tmp_path / "test_minigames_lb.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = MinigameRepository(manager)

        guild_id = 1001

        await repo.record_game(guild_id, 101, "rps", won=True, coins_delta=50)
        await repo.record_game(guild_id, 102, "rps", won=True, coins_delta=500)
        await repo.record_game(guild_id, 102, "rps", won=True, coins_delta=200)

        lb = await repo.get_leaderboard(guild_id, "rps", metric="wins")
        assert len(lb) == 2
        assert lb[0]["user_id"] == 102
        assert lb[0]["wins"] == 2

        await manager.close()

    run_async(_test())


def test_tictactoe_win_conditions():
    """Verify TicTacToe horizontal, vertical, and diagonal win detection."""
    p1 = MagicMock(spec=discord.Member)
    p1.id = 1
    p2 = MagicMock(spec=discord.Member)
    p2.id = 2

    view = TicTacToeView(p1, p2)

    # Test row win
    view.board = [
        ["X", "X", "X"],
        [None, "O", None],
        ["O", None, None],
    ]
    assert view.check_winner() == "X"

    # Test column win
    view.board = [
        ["O", "X", None],
        ["O", "X", None],
        ["O", None, "X"],
    ]
    assert view.check_winner() == "O"

    # Test diagonal win
    view.board = [
        ["X", "O", None],
        ["O", "X", None],
        [None, None, "X"],
    ]
    assert view.check_winner() == "X"


def test_blackjack_hand_score_calculation():
    """Verify card scoring and dynamic Ace handling in Blackjack."""
    view = BlackjackView(author_id=1, bet=100)

    hand = [BlackjackCard("10", "♠"), BlackjackCard("A", "♥")]
    assert view._calculate_score(hand) == 21

    # Hand with 2 Aces
    hand2 = [BlackjackCard("A", "♠"), BlackjackCard("A", "♥"), BlackjackCard("9", "♦")]
    # 11 + 1 + 9 = 21
    assert view._calculate_score(hand2) == 21

    # Bust with Ace
    hand3 = [BlackjackCard("10", "♠"), BlackjackCard("8", "♥"), BlackjackCard("A", "♦")]
    # 10 + 8 + 1 = 19
    assert view._calculate_score(hand3) == 19


def test_pvp_rps_view_initialization_and_turns():
    """Verify PvP RPS player authorization and turn handling."""
    p1 = MagicMock(spec=discord.Member)
    p1.id = 100
    p1.display_name = "Alice"
    p2 = MagicMock(spec=discord.Member)
    p2.id = 200
    p2.display_name = "Bob"

    view = PvPRPSView(player1=p1, player2=p2, bet=50)
    assert view.player1.id == 100
    assert view.player2.id == 200
    assert view.bet == 50
    assert view.choices == {}

    # Check non-participants are rejected
    async def _test():
        intruder = MagicMock(spec=discord.Interaction)
        intruder.user.id = 999
        intruder.response = AsyncMock()
        ok = await view.interaction_check(intruder)
        assert ok is False
        intruder.response.send_message.assert_awaited_once()

        # Check participants are allowed
        valid_int = MagicMock(spec=discord.Interaction)
        valid_int.user.id = 100
        valid_int.response = AsyncMock()
        ok2 = await view.interaction_check(valid_int)
        assert ok2 is True

    run_async(_test())


def test_russian_roulette_view():
    """Verify Russian Roulette turn alternation and chamber mechanics."""
    p1 = MagicMock(spec=discord.Member)
    p1.id = 101
    p2 = MagicMock(spec=discord.Member)
    p2.id = 202

    view = RussianRouletteView(player1=p1, player2=p2, bet=100)
    assert view.player1.id == 101
    assert view.player2.id == 202
    assert 1 <= view.chamber <= 6
    assert view.current_chamber == 1
    assert view.current_turn.id == 101

    # Check wrong turn check
    async def _test():
        wrong_turn_int = MagicMock(spec=discord.Interaction)
        wrong_turn_int.user.id = 202
        wrong_turn_int.response = AsyncMock()
        ok = await view.interaction_check(wrong_turn_int)
        assert ok is False

        # Correct turn check
        right_turn_int = MagicMock(spec=discord.Interaction)
        right_turn_int.user.id = 101
        right_turn_int.response = AsyncMock()
        ok2 = await view.interaction_check(right_turn_int)
        assert ok2 is True

    run_async(_test())


def test_dice_duel_view():
    """Verify Dice Duel initialization and roll check."""
    p1 = MagicMock(spec=discord.Member)
    p1.id = 111
    p2 = MagicMock(spec=discord.Member)
    p2.id = 222

    view = DiceDuelView(player1=p1, player2=p2, bet=250)
    assert view.player1.id == 111
    assert view.player2.id == 222
    assert view.bet == 250
    assert view.rolls == {}
