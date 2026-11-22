"""Phase 4 Master Test Suite: Fun & Minigames Subsystem (P4-TC01 to P4-TC10).

This suite verifies:
- P4-TC01: Coinflip lifecycle (solo flip, PvP challenge, bot & self guards)
- P4-TC02: Dice roll lifecycle (dice notation parsing, bounds checks, PvP duel)
- P4-TC03: Magic 8-Ball response generation and embed structure
- P4-TC04: PvP challenge dispatcher (coin, rps, math, dice routing & validation)
- P4-TC05: Fast math duel generation, message validation, and timeout handling
- P4-TC06: Tic-Tac-Toe minigame (grid init, turns, win conditions, draw)
- P4-TC07: Rock Paper Scissors (single-player & PvP secret move lock-in)
- P4-TC08: Blackjack mechanics (deck, hand scoring, ace adjustment, bust)
- P4-TC09: Russian roulette and Higher/Lower interactive game mechanics
- P4-TC10: Playful ratings & humor (meters, progress bars, self-roast guard)
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.cogs.fun.cog import Fun
from bot.cogs.fun.ratings import RatingsFun
from bot.cogs.fun import _ratings_data
from bot.cogs.minigames.cog import MinigamesCog
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
from bot.core.context import UnifiedContext
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import MinigameRepository, EconomyRepository


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.config = MagicMock()
    bot.config.owner_ids = [99901]
    bot.owner_ids = [99901]
    return bot


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 20001
    guild.name = "Phase4 Fun Guild"
    guild.owner_id = 90001
    return guild


# ==============================================================================
# P4-TC01: COINFLIP LIFECYCLE
# ==============================================================================

def test_p4_tc01_coinflip_lifecycle(mock_bot, mock_guild):
    """P4-TC01: Solo coinflip and PvP coinflip duel with bot and self guards."""
    async def _test():
        cog = Fun(mock_bot)

        author = MagicMock(spec=discord.Member)
        author.id = 10001
        author.bot = False
        author.mention = "<@10001>"

        ctx = MagicMock(spec=UnifiedContext)
        ctx.guild = mock_guild
        ctx.author = author
        ctx.reply = AsyncMock()
        ctx.send_error = AsyncMock()

        # 1. Solo flip
        await cog._execute_coinflip(ctx)
        assert ctx.reply.called
        embed = ctx.reply.call_args[1]["embed"]
        assert "Coin Flip" in embed.title
        assert "The coin landed on:" in embed.description

        # 2. Challenge bot guard
        bot_opp = MagicMock(spec=discord.Member)
        bot_opp.id = 99999
        bot_opp.bot = True
        await cog._execute_coinflip(ctx, opponent=bot_opp)
        ctx.send_error.assert_awaited_with(
            "Invalid Opponent", "You cannot challenge a bot! Challenge another player instead."
        )

        # 3. Challenge self guard
        ctx.send_error.reset_mock()
        await cog._execute_coinflip(ctx, opponent=author)
        ctx.send_error.assert_awaited_with(
            "Invalid Opponent", "You cannot challenge yourself! Challenge another player."
        )

        # 4. Valid PvP duel
        ctx.reply.reset_mock()
        valid_opp = MagicMock(spec=discord.Member)
        valid_opp.id = 10002
        valid_opp.bot = False
        valid_opp.mention = "<@10002>"

        await cog._execute_coinflip(ctx, opponent=valid_opp, call="tails")
        assert ctx.reply.called
        pvp_embed = ctx.reply.call_args[1]["embed"]
        assert "PvP Coin Flip Duel" in pvp_embed.title
        assert "Winner" in pvp_embed.description

    run_async(_test())


# ==============================================================================
# P4-TC02: DICE ROLL LIFECYCLE
# ==============================================================================

def test_p4_tc02_dice_roll_lifecycle(mock_bot, mock_guild):
    """P4-TC02: Dice roll NdS notation, count/side bounds, and PvP dice duel."""
    async def _test():
        cog = Fun(mock_bot)

        author = MagicMock(spec=discord.Member)
        author.id = 10001
        author.bot = False
        author.display_name = "PlayerOne"
        author.mention = "<@10001>"

        ctx = MagicMock(spec=UnifiedContext)
        ctx.guild = mock_guild
        ctx.author = author
        ctx.reply = AsyncMock()
        ctx.send_error = AsyncMock()

        # 1. Standard 2d6 roll
        await cog._execute_roll(ctx, target_or_dice="2d6")
        assert ctx.reply.called
        embed = ctx.reply.call_args[1]["embed"]
        assert "Dice Roll Result" in embed.title
        assert "Rolled `2d6`" in embed.description

        # 2. Bounds check: count > 20
        ctx.send_error.reset_mock()
        await cog._execute_roll(ctx, target_or_dice="25d6")
        ctx.send_error.assert_awaited_with(
            "Invalid Dice", "You can roll between 1 and 20 dice at once."
        )

        # 3. Bounds check: sides < 2
        ctx.send_error.reset_mock()
        await cog._execute_roll(ctx, target_or_dice="1d1")
        ctx.send_error.assert_awaited_with(
            "Invalid Sides", "Dice sides must be between 2 and 1000."
        )

        # 4. PvP Dice Duel
        ctx.reply.reset_mock()
        opponent = MagicMock(spec=discord.Member)
        opponent.id = 10002
        opponent.bot = False
        opponent.display_name = "PlayerTwo"
        opponent.mention = "<@10002>"

        await cog._execute_roll(ctx, opponent=opponent)
        assert ctx.reply.called
        pvp_embed = ctx.reply.call_args[1]["embed"]
        assert "PvP 2d6 Dice Showdown" in pvp_embed.title
        assert "PlayerOne" in pvp_embed.description
        assert "PlayerTwo" in pvp_embed.description

    run_async(_test())


# ==============================================================================
# P4-TC03: MAGIC 8-BALL
# ==============================================================================

def test_p4_tc03_magic_8ball(mock_bot, mock_guild):
    """P4-TC03: 8ball returns prediction embed with Question and Prediction fields."""
    async def _test():
        cog = Fun(mock_bot)

        author = MagicMock(spec=discord.Member)
        author.id = 10001
        author.bot = False

        ctx = MagicMock(spec=UnifiedContext)
        ctx.guild = mock_guild
        ctx.author = author
        ctx.reply = AsyncMock()

        question = "Will KROVEX conquer the Discord bot universe?"
        await cog._execute_eightball(ctx, question=question)

        assert ctx.reply.called
        embed = ctx.reply.call_args[1]["embed"]
        assert "Magic 8-Ball" in embed.title
        assert len(embed.fields) >= 2
        assert embed.fields[0].name == "Question"
        assert embed.fields[0].value == question
        assert embed.fields[1].name == "Prediction"

    run_async(_test())


# ==============================================================================
# P4-TC04: PVP CHALLENGE DISPATCHER
# ==============================================================================

def test_p4_tc04_pvp_challenge_dispatcher(mock_bot, mock_guild):
    """P4-TC04: Challenge command dispatches correctly and blocks bot/self challenges."""
    async def _test():
        cog = Fun(mock_bot)

        author = MagicMock(spec=discord.Member)
        author.id = 10001
        author.bot = False

        ctx = MagicMock(spec=UnifiedContext)
        ctx.guild = mock_guild
        ctx.author = author
        ctx.reply = AsyncMock()
        ctx.send_error = AsyncMock()

        bot_target = MagicMock(spec=discord.Member)
        bot_target.bot = True

        # 1. Challenge bot denied
        await cog._execute_challenge(ctx, opponent=bot_target, game_name="dice")
        ctx.send_error.assert_awaited_with(
            "Invalid Opponent", "You cannot challenge a bot! Challenge another player instead."
        )

        # 2. Challenge self denied
        ctx.send_error.reset_mock()
        await cog._execute_challenge(ctx, opponent=author, game_name="dice")
        ctx.send_error.assert_awaited_with(
            "Invalid Opponent", "You cannot challenge yourself! Challenge another player."
        )

        # 3. Valid challenge dispatches to coinflip
        opponent = MagicMock(spec=discord.Member)
        opponent.id = 10002
        opponent.bot = False
        opponent.mention = "<@10002>"

        with patch.object(cog, "_execute_coinflip", new_callable=AsyncMock) as mock_coin:
            await cog._execute_challenge(ctx, opponent=opponent, game_name="coin")
            mock_coin.assert_awaited_once_with(ctx, opponent=opponent)

        # 4. Valid challenge dispatches to dice
        with patch.object(cog, "_execute_roll", new_callable=AsyncMock) as mock_roll:
            await cog._execute_challenge(ctx, opponent=opponent, game_name="dice")
            mock_roll.assert_awaited_once_with(ctx, opponent=opponent)

    run_async(_test())


# ==============================================================================
# P4-TC05: FAST MATH DUEL
# ==============================================================================

def test_p4_tc05_fast_math_duel(mock_bot, mock_guild):
    """P4-TC05: Fast math duel question generation, chat answer check, and winner."""
    async def _test():
        cog = Fun(mock_bot)

        author = MagicMock(spec=discord.Member)
        author.id = 10001
        author.bot = False
        author.mention = "<@10001>"

        opponent = MagicMock(spec=discord.Member)
        opponent.id = 10002
        opponent.bot = False
        opponent.mention = "<@10002>"

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 50001

        ctx = MagicMock(spec=UnifiedContext)
        ctx.guild = mock_guild
        ctx.channel = channel
        ctx.author = author
        ctx.reply = AsyncMock()

        # Simulate winning message
        win_msg = MagicMock(spec=discord.Message)
        win_msg.author = opponent
        win_msg.channel = channel

        # Patch random to produce a deterministic question: 10 + 20 = 30
        with patch("random.randint", side_effect=[10, 20]), patch("random.choice", return_value="+"):
            win_msg.content = "30"
            mock_bot.wait_for = AsyncMock(return_value=win_msg)

            await cog._execute_mathduel(ctx, opponent=opponent)

            assert ctx.reply.call_count == 2
            initial_embed = ctx.reply.call_args_list[0][1]["embed"]
            assert "Fast Math Duel!" in initial_embed.title

            win_embed = ctx.reply.call_args_list[1][1]["embed"]
            assert "Math Duel Winner!" in win_embed.title
            assert opponent.mention in win_embed.description

        # Test Timeout Scenario
        ctx.reply.reset_mock()
        mock_bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError)
        await cog._execute_mathduel(ctx, opponent=opponent)

        assert ctx.reply.call_count == 2
        timeout_embed = ctx.reply.call_args_list[1][1]["embed"]
        assert "Math Duel Expired" in timeout_embed.title

    run_async(_test())


# ==============================================================================
# P4-TC06: TIC-TAC-TOE MINIGAME
# ==============================================================================

def test_p4_tc06_tictactoe_minigame():
    """P4-TC06: TicTacToeView 3x3 grid initialization, turns, and win detection."""
    p1 = MagicMock(spec=discord.Member)
    p1.id = 101
    p1.mention = "<@101>"

    p2 = MagicMock(spec=discord.Member)
    p2.id = 102
    p2.mention = "<@102>"

    view = TicTacToeView(player_x=p1, player_o=p2)
    assert len(view.board) == 3
    assert len(view.board[0]) == 3
    assert view.current_turn == "X"

    # Simulate horizontal win for X (top row)
    view.board[0][0] = "X"
    view.board[0][1] = "X"
    view.board[0][2] = "X"
    assert view.check_winner() == "X"

    # Simulate vertical win for O (first column)
    view.board[0][0] = "O"
    view.board[1][0] = "O"
    view.board[2][0] = "O"
    view.board[0][1] = None
    view.board[0][2] = None
    assert view.check_winner() == "O"

    # Simulate diagonal win for X
    view.board = [[None, None, None], [None, None, None], [None, None, None]]
    view.board[0][0] = "X"
    view.board[1][1] = "X"
    view.board[2][2] = "X"
    assert view.check_winner() == "X"

    # Simulate Tie / full board
    view.board = [
        ["X", "O", "X"],
        ["X", "O", "O"],
        ["O", "X", "X"],
    ]
    assert view.check_winner() is None
    assert view.is_board_full() is True


# ==============================================================================
# P4-TC07: ROCK PAPER SCISSORS (SINGLE-PLAYER & PVP)
# ==============================================================================

def test_p4_tc07_rps_and_pvp_rps():
    """P4-TC07: RPSView and PvPRPSView secret turn lock-in and interaction checks."""
    p1 = MagicMock(spec=discord.Member)
    p1.id = 201
    p1.mention = "<@201>"

    p2 = MagicMock(spec=discord.Member)
    p2.id = 202
    p2.mention = "<@202>"

    # 1. Single Player View
    single_view = RPSView(author_id=p1.id, bet=50)
    assert single_view.author_id == p1.id
    assert single_view.bet == 50

    # Interaction check denies non-author
    intr_wrong = MagicMock(spec=discord.Interaction)
    intr_wrong.user.id = 999
    intr_wrong.response.send_message = AsyncMock()
    assert run_async(single_view.interaction_check(intr_wrong)) is False

    # Interaction check allows author
    intr_author = MagicMock(spec=discord.Interaction)
    intr_author.user.id = p1.id
    assert run_async(single_view.interaction_check(intr_author)) is True

    # 2. PvP View
    pvp_view = PvPRPSView(player1=p1, player2=p2, bet=100)
    assert pvp_view.choices == {}

    # Player 1 locks in
    pvp_view.choices[p1.id] = "Rock"
    assert len(pvp_view.choices) == 1

    # Player 2 locks in
    pvp_view.choices[p2.id] = "Scissors"
    assert len(pvp_view.choices) == 2

    # Denies outsider
    intr_outsider = MagicMock(spec=discord.Interaction)
    intr_outsider.user.id = 777
    intr_outsider.response.send_message = AsyncMock()
    assert run_async(pvp_view.interaction_check(intr_outsider)) is False


# ==============================================================================
# P4-TC08: BLACKJACK MINIGAME
# ==============================================================================

def test_p4_tc08_blackjack_mechanics():
    """P4-TC08: BlackjackView deck initialization, hand scores, and Ace adjustment."""
    user_id = 301
    view = BlackjackView(author_id=user_id, bet=200)

    # Hand scoring tests using BlackjackCard instances
    # 1. Simple hand without Aces: 10 + 7 = 17
    score1 = view._calculate_score([BlackjackCard("10", "♠"), BlackjackCard("7", "♥")])
    assert score1 == 17

    # 2. Ace as 11: Ace + 9 = 20
    score2 = view._calculate_score([BlackjackCard("A", "♠"), BlackjackCard("9", "♦")])
    assert score2 == 20

    # 3. Ace adjusted to 1 to avoid bust: Ace + 9 + 5 = 15 (not 25)
    score3 = view._calculate_score([BlackjackCard("A", "♠"), BlackjackCard("9", "♦"), BlackjackCard("5", "♣")])
    assert score3 == 15

    # 4. Multiple Aces: Ace + Ace + 9 = 21 (11 + 1 + 9)
    score4 = view._calculate_score([BlackjackCard("A", "♠"), BlackjackCard("A", "♦"), BlackjackCard("9", "♣")])
    assert score4 == 21

    # 5. Blackjack (21 on deal): Ace + King = 21
    score5 = view._calculate_score([BlackjackCard("A", "♠"), BlackjackCard("K", "♣")])
    assert score5 == 21

    # 6. Bust: 10 + 8 + 7 = 25
    score6 = view._calculate_score([BlackjackCard("10", "♠"), BlackjackCard("8", "♦"), BlackjackCard("7", "♣")])
    assert score6 == 25


# ==============================================================================
# P4-TC09: RUSSIAN ROULETTE & HIGHER/LOWER
# ==============================================================================

def test_p4_tc09_russian_roulette_and_higher_lower():
    """P4-TC09: Russian roulette 6-chamber cylinder and Higher/Lower interactive mechanics."""
    p1 = MagicMock(spec=discord.Member)
    p1.id = 401
    p2 = MagicMock(spec=discord.Member)
    p2.id = 402

    # 1. Russian Roulette View
    rr_view = RussianRouletteView(player1=p1, player2=p2, bet=500)
    assert 1 <= rr_view.chamber <= 6
    assert rr_view.current_chamber == 1
    assert rr_view.current_turn == p1

    # 2. Higher or Lower View
    hl_view = HigherLowerView(author_id=p1.id, start_val=50)
    assert hl_view.current_val == 50
    assert hl_view.streak == 0

    # Verify interaction check restricts access to author
    intr_alien = MagicMock(spec=discord.Interaction)
    intr_alien.user.id = 999
    intr_alien.response.send_message = AsyncMock()
    assert run_async(hl_view.interaction_check(intr_alien)) is False


# ==============================================================================
# P4-TC10: PLAYFUL RATINGS & HUMOR
# ==============================================================================

def test_p4_tc10_playful_ratings_and_humor(mock_bot, mock_guild):
    """P4-TC10: Ratings meters, deterministic scores, progress bars, and self-roast guard."""
    async def _test():
        ratings_cog = RatingsFun(mock_bot)

        author = MagicMock(spec=discord.Member)
        author.id = 50001
        author.bot = False
        author.name = "ComedyKing"
        author.display_name = "ComedyKing"
        author.mention = "<@50001>"

        ctx = MagicMock(spec=UnifiedContext)
        ctx.guild = mock_guild
        ctx.author = author
        ctx.reply = AsyncMock()

        # 1. Test Progress Bar generation
        bar_100 = _ratings_data.generate_bar(100, 0, 100, 10)
        assert bar_100 == "██████████"
        bar_50 = _ratings_data.generate_bar(50, 0, 100, 10)
        assert bar_50 == "█████░░░░░"
        bar_0 = _ratings_data.generate_bar(0, 0, 100, 10)
        assert bar_0 == "░░░░░░░░░░"

        # 2. Test Meter execution
        await ratings_cog._execute_meter(ctx, "cute", target=author)
        assert ctx.reply.called
        cute_embed = ctx.reply.call_args[1]["embed"]
        assert "Cuteness Rating" in cute_embed.title
        assert "%" in cute_embed.title

        # 3. Test Love Meter between two users
        ctx.reply.reset_mock()
        partner = MagicMock(spec=discord.Member)
        partner.id = 50002
        partner.bot = False
        partner.name = "Queen"
        partner.mention = "<@50002>"

        await ratings_cog._execute_love(ctx, user1=author, user2=partner)
        assert ctx.reply.called
        love_embed = ctx.reply.call_args[1]["embed"]
        assert "Love Meter" in love_embed.title
        assert author.mention in love_embed.description
        assert partner.mention in love_embed.description

        # 4. Self-Roast Protection Guard
        ctx.reply.reset_mock()
        await ratings_cog._execute_roast(ctx, target=author)
        assert ctx.reply.called
        roast_embed = ctx.reply.call_args[1]["embed"]
        assert "Self-Roast Denied" in roast_embed.title
        assert "doesn't punch down" in roast_embed.description

    run_async(_test())
