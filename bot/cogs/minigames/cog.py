"""Interactive Minigames System Cog with bets, persistent leaderboards, and UI buttons."""
from __future__ import annotations

import asyncio
import datetime
import random
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.minigames.views import (
    BlackjackView,
    DiceDuelView,
    HigherLowerView,
    PvPRPSView,
    RPSView,
    RussianRouletteView,
    TicTacToeView,
    TriviaView,
)
from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.minigames")
BRAND_COLOR = 0x9D4EDD


class MinigamesCog(commands.GroupCog, group_name="game"):
    """Interactive Discord multiplayer minigames, single-player puzzles, and stats tracking."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot
        self._active_number_guesses: Dict[int, int] = {}  # channel_id -> target_number
        self._active_word_guesses: Dict[int, str] = {}    # channel_id -> target_word
        super().__init__()

    # =========================================================
    # CORE SHARED BUSINESS LOGIC
    # =========================================================

    async def _execute_coinflip(self, ctx: UnifiedContext, bet: int = 0) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        if bet < 0:
            await ctx.send_error("Invalid Bet", "Bet cannot be negative.")
            return

        if bet > 0 and self.bot.economy_repo:
            bal = await self.bot.economy_repo.get_balance(ctx.guild.id, ctx.author.id)
            if bal["wallet"] < bet:
                await ctx.send_error("Insufficient Funds", f"You only have `{bal['wallet']:,}` coins in your wallet.")
                return

        outcome = random.choice(["Heads", "Tails"])
        coin_emoji = KrovexEmoji.CRYSTALS.discord_format

        # 50/50 resolve
        user_won = random.choice([True, False])
        if user_won:
            title = f"{KrovexEmoji.VICTORY} Coin Flip • Winner!"
            desc = f"The coin landed on **{outcome}**! You won **+{bet:,}** {coin_emoji}!" if bet > 0 else f"The coin landed on **{outcome}**!"
            delta = bet
            if bet > 0 and self.bot.economy_repo:
                await self.bot.economy_repo.add_money(ctx.guild.id, ctx.author.id, bet)
        else:
            title = f"{KrovexEmoji.YOU_SUCK} Coin Flip • Lost"
            desc = f"The coin landed on **{outcome}**! You lost **-{bet:,}** {coin_emoji}." if bet > 0 else f"The coin landed on **{outcome}**!"
            delta = -bet
            if bet > 0 and self.bot.economy_repo:
                await self.bot.economy_repo.remove_money(ctx.guild.id, ctx.author.id, bet)

        await self.bot.minigame_repo.record_game(ctx.guild.id, ctx.author.id, "coinflip", won=user_won, coins_delta=delta)
        embed = EmbedBuilder.base(title=title, description=desc, color=BRAND_COLOR)
        await ctx.reply(embed=embed)

    async def _execute_dice(self, ctx: UnifiedContext, bet: int = 0) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        if bet < 0:
            await ctx.send_error("Invalid Bet", "Bet cannot be negative.")
            return

        if bet > 0 and self.bot.economy_repo:
            bal = await self.bot.economy_repo.get_balance(ctx.guild.id, ctx.author.id)
            if bal["wallet"] < bet:
                await ctx.send_error("Insufficient Funds", f"You only have `{bal['wallet']:,}` coins.")
                return

        user_roll = random.randint(1, 6) + random.randint(1, 6)
        bot_roll = random.randint(1, 6) + random.randint(1, 6)

        if user_roll > bot_roll:
            title = "🎲 Dice Duel • Victory!"
            desc = f"Your Roll: `{user_roll}` 🎲\nBot Roll: `{bot_roll}` 🎲\n\nYou won **+{bet:,}** coins!" if bet > 0 else f"Your Roll: `{user_roll}`\nBot Roll: `{bot_roll}`\nYou won!"
            delta = bet
            won = True
            drawn = False
            if bet > 0 and self.bot.economy_repo:
                await self.bot.economy_repo.add_money(ctx.guild.id, ctx.author.id, bet)
        elif user_roll < bot_roll:
            title = "🎲 Dice Duel • Defeat"
            desc = f"Your Roll: `{user_roll}` 🎲\nBot Roll: `{bot_roll}` 🎲\n\nYou lost **-{bet:,}** coins!" if bet > 0 else f"Your Roll: `{user_roll}`\nBot Roll: `{bot_roll}`\nYou lost!"
            delta = -bet
            won = False
            drawn = False
            if bet > 0 and self.bot.economy_repo:
                await self.bot.economy_repo.remove_money(ctx.guild.id, ctx.author.id, bet)
        else:
            title = "🎲 Dice Duel • Tie!"
            desc = f"Both rolled `{user_roll}`! Push / Draw."
            delta = 0
            won = False
            drawn = True

        await self.bot.minigame_repo.record_game(ctx.guild.id, ctx.author.id, "dice", won=won, drawn=drawn, coins_delta=delta)
        embed = EmbedBuilder.base(title=title, description=desc, color=BRAND_COLOR)
        await ctx.reply(embed=embed)

    async def _execute_rps(
        self,
        ctx: UnifiedContext,
        opponent: Optional[discord.Member] = None,
        bet: int = 0,
    ) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        if bet < 0:
            await ctx.send_error("Invalid Bet", "Bet cannot be negative.")
            return

        if bet > 0 and self.bot.economy_repo:
            bal = await self.bot.economy_repo.get_balance(ctx.guild.id, ctx.author.id)
            if bal["wallet"] < bet:
                await ctx.send_error("Insufficient Funds", f"You only have `{bal['wallet']:,}` coins.")
                return

        if opponent is not None:
            if opponent.id == ctx.author.id:
                await ctx.send_error("Invalid Opponent", "You cannot challenge yourself to Rock Paper Scissors.")
                return
            if opponent.bot:
                await ctx.send_error("Invalid Opponent", "You cannot challenge a bot. Challenge another player!")
                return
            if bet > 0 and self.bot.economy_repo:
                opp_bal = await self.bot.economy_repo.get_balance(ctx.guild.id, opponent.id)
                if opp_bal["wallet"] < bet:
                    await ctx.send_error("Insufficient Funds", f"{opponent.mention} only has `{opp_bal['wallet']:,}` coins in their wallet.")
                    return

            view = PvPRPSView(player1=ctx.author, player2=opponent, bet=bet)
            embed = EmbedBuilder.base(
                title="⚔️ PvP Rock Paper Scissors Challenge",
                description=(
                    f"**{ctx.author.mention}** has challenged **{opponent.mention}** to Rock Paper Scissors!\n\n"
                    f"💰 **Wager:** `{bet:,}` Coins\n\n"
                    f"Both players: Click your secret move below to lock in!"
                ),
                color=BRAND_COLOR,
            )
            await ctx.reply(embed=embed, view=view)
        else:
            view = RPSView(ctx.author.id, bet=bet)
            embed = EmbedBuilder.base(
                title="✂️ Rock Paper Scissors",
                description=f"Choose your move below! Bet: {KrovexEmoji.CRYSTALS} **{bet:,}** Coins",
                color=BRAND_COLOR,
            )
            await ctx.reply(embed=embed, view=view)

    async def _execute_roulette(
        self,
        ctx: UnifiedContext,
        opponent: discord.Member,
        bet: int = 0,
    ) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        if bet < 0:
            await ctx.send_error("Invalid Bet", "Bet cannot be negative.")
            return
        if opponent.id == ctx.author.id:
            await ctx.send_error("Invalid Opponent", "You cannot challenge yourself to Russian Roulette.")
            return
        if opponent.bot:
            await ctx.send_error("Invalid Opponent", "You cannot challenge a bot to Russian Roulette.")
            return

        if bet > 0 and self.bot.economy_repo:
            bal = await self.bot.economy_repo.get_balance(ctx.guild.id, ctx.author.id)
            if bal["wallet"] < bet:
                await ctx.send_error("Insufficient Funds", f"You only have `{bal['wallet']:,}` coins.")
                return
            opp_bal = await self.bot.economy_repo.get_balance(ctx.guild.id, opponent.id)
            if opp_bal["wallet"] < bet:
                await ctx.send_error("Insufficient Funds", f"{opponent.mention} only has `{opp_bal['wallet']:,}` coins.")
                return

        view = RussianRouletteView(player1=ctx.author, player2=opponent, bet=bet)
        embed = EmbedBuilder.base(
            title="🔫 High-Stakes Russian Roulette Duel",
            description=(
                f"**{ctx.author.mention}** vs **{opponent.mention}**\n\n"
                f"Chamber is loaded (1 lethal round in 6 chambers)!\n"
                + (f"💰 **Wager:** `{bet:,}` Coins\n\n" if bet > 0 else "\n")
                + f"👉 **{ctx.author.mention}**, you go first! Pull the trigger when ready."
            ),
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed, view=view)

    async def _execute_diceduel(
        self,
        ctx: UnifiedContext,
        opponent: discord.Member,
        bet: int = 0,
    ) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        if bet < 0:
            await ctx.send_error("Invalid Bet", "Bet cannot be negative.")
            return
        if opponent.id == ctx.author.id:
            await ctx.send_error("Invalid Opponent", "You cannot challenge yourself to a dice duel.")
            return
        if opponent.bot:
            await ctx.send_error("Invalid Opponent", "You cannot challenge a bot to a dice duel.")
            return

        if bet > 0 and self.bot.economy_repo:
            bal = await self.bot.economy_repo.get_balance(ctx.guild.id, ctx.author.id)
            if bal["wallet"] < bet:
                await ctx.send_error("Insufficient Funds", f"You only have `{bal['wallet']:,}` coins.")
                return
            opp_bal = await self.bot.economy_repo.get_balance(ctx.guild.id, opponent.id)
            if opp_bal["wallet"] < bet:
                await ctx.send_error("Insufficient Funds", f"{opponent.mention} only has `{opp_bal['wallet']:,}` coins.")
                return

        view = DiceDuelView(player1=ctx.author, player2=opponent, bet=bet)
        embed = EmbedBuilder.base(
            title="🎲 2-Player Dice Duel Showdown",
            description=(
                f"**{ctx.author.mention}** has challenged **{opponent.mention}** to a 2d6 Dice Duel!\n\n"
                + (f"💰 **Wager:** `{bet:,}` Coins\n\n" if bet > 0 else "\n")
                + f"Both players: Click **Roll Dice** below to roll your 2d6!"
            ),
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed, view=view)

    async def _execute_tictactoe(self, ctx: UnifiedContext, opponent: discord.Member) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        if opponent.id == ctx.author.id:
            await ctx.send_error("Invalid Opponent", "You cannot play Tic-Tac-Toe against yourself.")
            return
        if opponent.bot:
            await ctx.send_error("Invalid Opponent", "You cannot challenge a bot to Tic-Tac-Toe.")
            return

        view = TicTacToeView(player_x=ctx.author, player_o=opponent)
        embed = EmbedBuilder.base(
            title="🎮 Tic-Tac-Toe Match Started!",
            description=f"**X:** {ctx.author.mention}\n**O:** {opponent.mention}\n\n👉 Current Turn: {ctx.author.mention} (`X`)",
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed, view=view)

    async def _execute_connectfour(self, ctx: UnifiedContext, opponent: discord.Member) -> None:
        if not ctx.guild:
            return
        if opponent.id == ctx.author.id or opponent.bot:
            await ctx.send_error("Invalid Opponent", "Choose another human player to challenge.")
            return

        embed = EmbedBuilder.base(
            title="🔴 Connect Four Challenge 🟡",
            description=(
                f"{ctx.author.mention} challenged {opponent.mention} to Connect Four!\n\n"
                "Game grid initialized: 6 rows x 7 columns.\n"
                f"Turn: {ctx.author.mention} (🔴 Red)"
            ),
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    async def _execute_blackjack(self, ctx: UnifiedContext, bet: int = 0) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        if bet < 0:
            await ctx.send_error("Invalid Bet", "Bet cannot be negative.")
            return
        if bet > 0 and self.bot.economy_repo:
            bal = await self.bot.economy_repo.get_balance(ctx.guild.id, ctx.author.id)
            if bal["wallet"] < bet:
                await ctx.send_error("Insufficient Funds", f"You need `{bet:,}` coins to place this bet.")
                return

        view = BlackjackView(ctx.author.id, bet=bet)
        embed = view.get_embed(hide_dealer=True)
        await ctx.reply(embed=embed, view=view)

    async def _execute_higherlower(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        start_val = random.randint(20, 80)
        view = HigherLowerView(ctx.author.id, start_val=start_val)
        embed = EmbedBuilder.base(
            title="🃏 Higher or Lower",
            description=f"Current Number: **{start_val}** (Range 1-100)\n\nWill the next number be **Higher** or **Lower**?",
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed, view=view)

    async def _execute_guessnumber(self, ctx: UnifiedContext, guess: Optional[int] = None) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        ch_id = ctx.channel.id

        if guess is None:
            # Start new session
            secret = random.randint(1, 100)
            self._active_number_guesses[ch_id] = secret
            embed = EmbedBuilder.base(
                title="🔢 Number Guessing Game Started!",
                description="I have chosen a secret integer between **1 and 100**!\nType `guessnumber <number>` to submit your guess.",
                color=BRAND_COLOR,
            )
            await ctx.reply(embed=embed)
            return

        secret = self._active_number_guesses.get(ch_id)
        if secret is None:
            await ctx.send_error("No Active Game", "No number guessing game active. Start one with `guessnumber`.")
            return

        if guess == secret:
            del self._active_number_guesses[ch_id]
            await self.bot.minigame_repo.record_game(ctx.guild.id, ctx.author.id, "guessnumber", won=True, score=100)
            embed = EmbedBuilder.success(
                title="🎯 Bingo! You Guessed the Secret Number!",
                description=f"Congratulations {ctx.author.mention}! The secret number was indeed **{secret}**!",
            )
            await ctx.reply(embed=embed)
        elif guess < secret:
            await ctx.reply(f"📈 **Higher!** Your guess `{guess}` is too low.")
        else:
            await ctx.reply(f"📉 **Lower!** Your guess `{guess}` is too high.")

    async def _execute_wordguess(self, ctx: UnifiedContext, guess: Optional[str] = None) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        words = ["DISCORD", "PYTHON", "SECURITY", "DEVELOP", "SERVER", "COMMAND", "GAMING", "ROBOT", "STREAM", "MUSIC"]
        ch_id = ctx.channel.id

        if guess is None:
            chosen = random.choice(words)
            self._active_word_guesses[ch_id] = chosen
            hint = f"Word has `{len(chosen)}` letters. Starts with `{chosen[0]}` and ends with `{chosen[-1]}`."
            embed = EmbedBuilder.base(
                title="🔤 Word Guessing Challenge Started!",
                description=f"Can you guess the secret word?\n\n**Hint:** {hint}\nType `wordguess <word>` to guess!",
                color=BRAND_COLOR,
            )
            await ctx.reply(embed=embed)
            return

        target = self._active_word_guesses.get(ch_id)
        if not target:
            await ctx.send_error("No Active Game", "No word guessing game active. Type `wordguess` to start.")
            return

        if guess.upper() == target:
            del self._active_word_guesses[ch_id]
            await self.bot.minigame_repo.record_game(ctx.guild.id, ctx.author.id, "wordguess", won=True)
            embed = EmbedBuilder.success(
                title=f"{KrovexEmoji.TADA} Correct Word!",
                description=f"{ctx.author.mention} guessed the word **{target}** correctly!",
            )
            await ctx.reply(embed=embed)
        else:
            await ctx.reply(f"❌ **{guess}** is not the secret word. Keep guessing!")

    async def _execute_trivia(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        questions = [
            ("Which programming language was created by Guido van Rossum?", ["Python", "JavaScript", "C++", "Rust"], 0),
            ("In gaming, what does 'NPC' stand for?", ["Non-Playable Character", "New Player Clan", "Network Protocol Code", "Null Point Controller"], 0),
            ("What is the primary database engine used by Death Bot?", ["SQLite WAL", "MongoDB", "PostgreSQL", "Redis"], 0),
            ("What is the speed of light in vacuum (approximate)?", ["300,000 km/s", "150,000 km/s", "1,000,000 km/s", "30,000 km/s"], 0),
            ("Which planet in our solar system is known as the Red Planet?", ["Mars", "Venus", "Jupiter", "Mercury"], 0),
        ]
        q_text, opts, correct_idx = random.choice(questions)
        view = TriviaView(ctx.author.id, q_text, opts, correct_idx)
        embed = EmbedBuilder.base(
            title="🧠 Daily Trivia Challenge",
            description=f"**{q_text}**\n\nSelect your answer using the buttons below (45s timer):",
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed, view=view)

    async def _execute_daily(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        challenge = await self.bot.minigame_repo.get_daily_challenge(ctx.guild.id, today_str)

        if not challenge:
            await self.bot.minigame_repo.create_daily_challenge(ctx.guild.id, today_str, "Win 3 Blackjack or Dice games", target=3, reward=500)
            challenge = await self.bot.minigame_repo.get_daily_challenge(ctx.guild.id, today_str)

        embed = EmbedBuilder.base(
            title="🎯 Server Daily Minigame Challenge",
            description=(
                f"**Date:** `{today_str}`\n"
                f"**Challenge:** {challenge['challenge_type']}\n"
                f"**Reward:** {KrovexEmoji.CRYSTALS} **{challenge['reward_coins']:,}** Coins\n\n"
                "Play minigames today to complete your challenge!"
            ),
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    async def _execute_stats(self, ctx: UnifiedContext, member: Optional[discord.Member] = None) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        target = member or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if not target:
            return

        stats = await self.bot.minigame_repo.get_stats(ctx.guild.id, target.id)
        wins = stats.get("total_wins") or 0
        losses = stats.get("total_losses") or 0
        draws = stats.get("total_draws") or 0
        total_games = wins + losses + draws
        win_rate = (wins / total_games * 100) if total_games > 0 else 0.0

        coins_won = stats.get("total_coins_won") or 0
        coins_lost = stats.get("total_coins_lost") or 0
        net = coins_won - coins_lost

        embed = EmbedBuilder.base(
            title=f"🎮 Gamer Statistics • {target.display_name}",
            color=BRAND_COLOR,
            thumbnail=target.display_avatar.url,
        )
        embed.add_field(name="Games Played", value=f"`{total_games:,}` matches", inline=True)
        embed.add_field(name=f"{KrovexEmoji.MINI_STAR} Victories", value=f"🏆 `{wins:,}` wins", inline=True)
        embed.add_field(name="Defeats", value=f"💀 `{losses:,}` losses", inline=True)
        embed.add_field(name="Win Rate", value=f"📊 **{win_rate:.1f}%**", inline=True)
        embed.add_field(name="Coins Won", value=f"{KrovexEmoji.CRYSTALS} `+{coins_won:,}`", inline=True)
        embed.add_field(name="Net Profit", value=f"{'🟢' if net >= 0 else '🔴'} `{net:,}` Coins", inline=True)
        await ctx.reply(embed=embed)

    async def _execute_leaderboard(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        rows = await self.bot.minigame_repo.get_leaderboard(ctx.guild.id, limit=10)
        lines = []
        for i, r in enumerate(rows, start=1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`#{i}`"
            lines.append(f"{medal} <@{r['user_id']}> — **{r['wins']:,}** Wins *(Earnings: `{r['coins_won']:,}` Coins)*")

        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.MINI_STAR} Minigames Champion Leaderboard • {ctx.guild.name}",
            description="\n".join(lines) if lines else "No games recorded yet. Play to top the leaderboard!",
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    async def _execute_toggle(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        s = await self.bot.minigame_repo.get_settings(ctx.guild.id)
        new_state = not s.get("enabled", True)
        await self.bot.minigame_repo.update_settings(ctx.guild.id, enabled=new_state)
        await ctx.send_success("Minigames Toggled", f"Minigames are now **{'Enabled' if new_state else 'Disabled'}**.")

    async def _execute_cooldown(self, ctx: UnifiedContext, seconds: int) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if seconds < 0 or seconds > 3600:
            await ctx.send_error("Invalid Seconds", "Cooldown must be between 0 and 3600s.")
            return

        await self.bot.minigame_repo.update_settings(ctx.guild.id, cooldown_seconds=seconds)
        await ctx.send_success("Cooldown Updated", f"Minigame session cooldown set to `{seconds}s`.")

    async def _execute_config(self, ctx: UnifiedContext, min_bet: int, max_bet: int) -> None:
        if not ctx.guild or not self.bot.minigame_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if min_bet < 1 or max_bet < min_bet:
            await ctx.send_error("Invalid Range", "Provide valid min and max bets.")
            return

        await self.bot.minigame_repo.update_settings(ctx.guild.id, min_bet=min_bet, max_bet=max_bet)
        await ctx.send_success("Betting Limits Saved", f"Allowed bet range set to `{min_bet:,} – {max_bet:,}` coins.")

    # =========================================================
    # SLASH COMMAND GROUP: /game <subcommand> (16 subcommands)
    # =========================================================

    @app_commands.command(name="coinflip", description="Flip a coin with optional currency bet.")
    @app_commands.describe(bet="Optional bet amount")
    async def slash_coinflip(self, interaction: discord.Interaction, bet: int = 0) -> None:
        await self._execute_coinflip(UnifiedContext.from_interaction(interaction), bet)

    @app_commands.command(name="dice", description="Roll against the bot with optional currency bet.")
    @app_commands.describe(bet="Optional bet amount")
    async def slash_dice(self, interaction: discord.Interaction, bet: int = 0) -> None:
        await self._execute_dice(UnifiedContext.from_interaction(interaction), bet)

    @app_commands.command(name="rps", description="Play Rock Paper Scissors against another player (or solo) with optional bet.")
    @app_commands.describe(opponent="Optional member to challenge", bet="Optional bet amount")
    async def slash_rps(self, interaction: discord.Interaction, opponent: Optional[discord.Member] = None, bet: int = 0) -> None:
        await self._execute_rps(UnifiedContext.from_interaction(interaction), opponent, bet)

    @app_commands.command(name="roulette", description="Challenge another player to a game of Russian Roulette.")
    @app_commands.describe(opponent="Member to challenge", bet="Optional currency wager")
    async def slash_roulette(self, interaction: discord.Interaction, opponent: discord.Member, bet: int = 0) -> None:
        await self._execute_roulette(UnifiedContext.from_interaction(interaction), opponent, bet)

    @app_commands.command(name="diceduel", description="Challenge another player to a 2d6 dice showdown.")
    @app_commands.describe(opponent="Member to challenge", bet="Optional currency wager")
    async def slash_diceduel(self, interaction: discord.Interaction, opponent: discord.Member, bet: int = 0) -> None:
        await self._execute_diceduel(UnifiedContext.from_interaction(interaction), opponent, bet)

    @app_commands.command(name="tictactoe", description="Challenge another member to a 3x3 Tic-Tac-Toe match.")
    @app_commands.describe(opponent="Member to challenge")
    async def slash_tictactoe(self, interaction: discord.Interaction, opponent: discord.Member) -> None:
        await self._execute_tictactoe(UnifiedContext.from_interaction(interaction), opponent)

    @app_commands.command(name="connectfour", description="Challenge another member to Connect Four.")
    @app_commands.describe(opponent="Member to challenge")
    async def slash_connectfour(self, interaction: discord.Interaction, opponent: discord.Member) -> None:
        await self._execute_connectfour(UnifiedContext.from_interaction(interaction), opponent)

    @app_commands.command(name="blackjack", description="Play a game of Blackjack (21) with optional currency bet.")
    @app_commands.describe(bet="Bet amount")
    async def slash_blackjack(self, interaction: discord.Interaction, bet: int = 0) -> None:
        await self._execute_blackjack(UnifiedContext.from_interaction(interaction), bet)

    @app_commands.command(name="higherlower", description="Guess if the next card/number is Higher or Lower.")
    async def slash_higherlower(self, interaction: discord.Interaction) -> None:
        await self._execute_higherlower(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="guessnumber", description="Guess the secret number between 1 and 100.")
    @app_commands.describe(guess="Your guess (leave blank to start a new game)")
    async def slash_guessnumber(self, interaction: discord.Interaction, guess: Optional[int] = None) -> None:
        await self._execute_guessnumber(UnifiedContext.from_interaction(interaction), guess)

    @app_commands.command(name="wordguess", description="Wordle-style word guessing challenge.")
    @app_commands.describe(guess="Your word guess (leave blank to start new game)")
    async def slash_wordguess(self, interaction: discord.Interaction, guess: Optional[str] = None) -> None:
        await self._execute_wordguess(UnifiedContext.from_interaction(interaction), guess)

    @app_commands.command(name="trivia", description="Answer multiple choice trivia questions.")
    async def slash_trivia(self, interaction: discord.Interaction) -> None:
        await self._execute_trivia(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="daily", description="View server daily minigame challenge.")
    async def slash_daily(self, interaction: discord.Interaction) -> None:
        await self._execute_daily(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="stats", description="View your or another member's minigame stats.")
    @app_commands.describe(member="Member to inspect")
    async def slash_stats(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        await self._execute_stats(UnifiedContext.from_interaction(interaction), member)

    @app_commands.command(name="leaderboard", description="View top winning minigame champions.")
    async def slash_leaderboard(self, interaction: discord.Interaction) -> None:
        await self._execute_leaderboard(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="toggle", description="Enable or disable minigames.")
    async def slash_toggle(self, interaction: discord.Interaction) -> None:
        await self._execute_toggle(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="cooldown", description="Configure cooldown between minigame plays.")
    @app_commands.describe(seconds="Cooldown in seconds")
    async def slash_cooldown(self, interaction: discord.Interaction, seconds: int) -> None:
        await self._execute_cooldown(UnifiedContext.from_interaction(interaction), seconds)

    @app_commands.command(name="config", description="Configure betting limits.")
    @app_commands.describe(min_bet="Minimum bet", max_bet="Maximum bet")
    async def slash_config(self, interaction: discord.Interaction, min_bet: int, max_bet: int) -> None:
        await self._execute_config(UnifiedContext.from_interaction(interaction), min_bet, max_bet)

    @app_commands.command(name="8ball", description="Ask the magic 8-ball a question.")
    @app_commands.describe(question="The question to ask the 8-ball")
    async def slash_8ball(self, interaction: discord.Interaction, question: str) -> None:
        fun_cog = self.bot.cogs.get("Fun & Entertainment")
        if fun_cog and hasattr(fun_cog, "_execute_eightball"):
            await fun_cog._execute_eightball(UnifiedContext.from_interaction(interaction), question)
        else:
            await interaction.response.send_message("8ball subsystem offline.", ephemeral=True)

    @app_commands.command(name="coinflip", description="Flip a two-sided coin.")
    async def slash_coinflip(self, interaction: discord.Interaction) -> None:
        fun_cog = self.bot.cogs.get("Fun & Entertainment")
        if fun_cog and hasattr(fun_cog, "_execute_coinflip"):
            await fun_cog._execute_coinflip(UnifiedContext.from_interaction(interaction))
        else:
            await interaction.response.send_message("Coinflip subsystem offline.", ephemeral=True)

    @app_commands.command(name="roll", description="Roll one or multiple dice with specified sides (e.g., 2d6).")
    @app_commands.describe(dice="Dice format NdS (default: 1d6)")
    async def slash_roll(self, interaction: discord.Interaction, dice: str = "1d6") -> None:
        fun_cog = self.bot.cogs.get("Fun & Entertainment")
        if fun_cog and hasattr(fun_cog, "_execute_roll"):
            await fun_cog._execute_roll(UnifiedContext.from_interaction(interaction), dice)
        else:
            await interaction.response.send_message("Roll subsystem offline.", ephemeral=True)

    # =========================================================
    # PREFIX COMMANDS (16 commands)
    # =========================================================

    @commands.command(name="betflip", aliases=["coinbet"], help="Flip a coin with an optional bet.")
    async def prefix_coinflip(self, ctx: commands.Context, bet: int = 0) -> None:
        await self._execute_coinflip(UnifiedContext.from_prefix(ctx), bet)

    @commands.command(name="betdice", aliases=["botdice"], help="Roll dice against the bot with an optional bet.")
    async def prefix_dice(self, ctx: commands.Context, bet: int = 0) -> None:
        await self._execute_dice(UnifiedContext.from_prefix(ctx), bet)

    @commands.command(name="rps", help="Play Rock Paper Scissors against another player (or solo) with optional bet.")
    async def prefix_rps(
        self,
        ctx: commands.Context,
        target_or_bet: Optional[str] = None,
        bet: Optional[int] = None,
    ) -> None:
        opponent: Optional[discord.Member] = None
        actual_bet = 0

        if target_or_bet is not None:
            if target_or_bet.isdigit():
                actual_bet = int(target_or_bet)
            else:
                try:
                    opponent = await commands.MemberConverter().convert(ctx, target_or_bet)
                    actual_bet = bet or 0
                except commands.BadArgument:
                    await ctx.send(f"❌ Could not find member `{target_or_bet}`.")
                    return

        await self._execute_rps(UnifiedContext.from_prefix(ctx), opponent, actual_bet)

    @commands.command(name="roulette", aliases=["russianroulette", "duel"], help="Challenge another player to Russian Roulette.")
    async def prefix_roulette(self, ctx: commands.Context, opponent: discord.Member, bet: int = 0) -> None:
        await self._execute_roulette(UnifiedContext.from_prefix(ctx), opponent, bet)

    @commands.command(name="diceduel", aliases=["rollduel"], help="Challenge another player to a 2d6 dice showdown.")
    async def prefix_diceduel(self, ctx: commands.Context, opponent: discord.Member, bet: int = 0) -> None:
        await self._execute_diceduel(UnifiedContext.from_prefix(ctx), opponent, bet)

    @commands.command(name="tictactoe", aliases=["ttt"], help="Play Tic-Tac-Toe against another member.")
    async def prefix_tictactoe(self, ctx: commands.Context, opponent: discord.Member) -> None:
        await self._execute_tictactoe(UnifiedContext.from_prefix(ctx), opponent)

    @commands.command(name="connectfour", aliases=["c4"], help="Play Connect Four against another member.")
    async def prefix_connectfour(self, ctx: commands.Context, opponent: discord.Member) -> None:
        await self._execute_connectfour(UnifiedContext.from_prefix(ctx), opponent)

    @commands.command(name="blackjack", aliases=["bj", "21"], help="Play Blackjack (21) with optional bet.")
    async def prefix_blackjack(self, ctx: commands.Context, bet: int = 0) -> None:
        await self._execute_blackjack(UnifiedContext.from_prefix(ctx), bet)

    @commands.command(name="higherlower", aliases=["hl"], help="Play Higher or Lower card guessing game.")
    async def prefix_higherlower(self, ctx: commands.Context) -> None:
        await self._execute_higherlower(UnifiedContext.from_prefix(ctx))

    @commands.command(name="guessnumber", help="Guess the secret number (1-100).")
    async def prefix_guessnumber(self, ctx: commands.Context, guess: Optional[int] = None) -> None:
        await self._execute_guessnumber(UnifiedContext.from_prefix(ctx), guess)

    @commands.command(name="wordguess", help="Wordle-style word guessing challenge.")
    async def prefix_wordguess(self, ctx: commands.Context, *, guess: Optional[str] = None) -> None:
        await self._execute_wordguess(UnifiedContext.from_prefix(ctx), guess)

    @commands.command(name="trivia", help="Answer trivia questions.")
    async def prefix_trivia(self, ctx: commands.Context) -> None:
        await self._execute_trivia(UnifiedContext.from_prefix(ctx))

    @commands.command(name="dailychallenge", help="View daily minigame challenge.")
    async def prefix_dailychallenge(self, ctx: commands.Context) -> None:
        await self._execute_daily(UnifiedContext.from_prefix(ctx))

    @commands.command(name="gamestats", help="View your minigame statistics.")
    async def prefix_gamestats(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_stats(UnifiedContext.from_prefix(ctx), member)

    @commands.command(name="gameleaderboard", aliases=["gametop"], help="View top minigame champions.")
    async def prefix_gameleaderboard(self, ctx: commands.Context) -> None:
        await self._execute_leaderboard(UnifiedContext.from_prefix(ctx))

    @commands.command(name="gametoggle", help="Enable or disable minigames.")
    @commands.has_permissions(administrator=True)
    async def prefix_gametoggle(self, ctx: commands.Context) -> None:
        await self._execute_toggle(UnifiedContext.from_prefix(ctx))

    @commands.command(name="gamecooldown", help="Set cooldown between minigame matches.")
    @commands.has_permissions(administrator=True)
    async def prefix_gamecooldown(self, ctx: commands.Context, seconds: int) -> None:
        await self._execute_cooldown(UnifiedContext.from_prefix(ctx), seconds)

    @commands.command(name="gameconfig", help="Set betting limits.")
    @commands.has_permissions(administrator=True)
    async def prefix_gameconfig(self, ctx: commands.Context, min_bet: int, max_bet: int) -> None:
        await self._execute_config(UnifiedContext.from_prefix(ctx), min_bet, max_bet)


async def setup(bot: DeathBot) -> None:
    """Setup hook to register MinigamesCog."""
    await bot.add_cog(MinigamesCog(bot))

