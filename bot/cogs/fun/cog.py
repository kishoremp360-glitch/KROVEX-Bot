"""Entertainment, mini-games, PvP challenges, and randomness cog."""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

BRAND_COLOR = 0x9D4EDD


class Fun(commands.Cog, name="Fun & Entertainment"):
    """Mini-games, chance-based queries, PvP challenges, and entertainment tools."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    async def _execute_coinflip(
        self,
        ctx: UnifiedContext,
        opponent: Optional[discord.Member] = None,
        call: Optional[str] = "heads",
    ) -> None:
        """Shared logic for coinflip, supporting solo flip and PvP challenge."""
        if opponent is not None:
            if opponent.bot:
                await ctx.send_error("Invalid Opponent", "You cannot challenge a bot! Challenge another player instead.")
                return
            if opponent.id == ctx.author.id:
                await ctx.send_error("Invalid Opponent", "You cannot challenge yourself! Challenge another player.")
                return

            chosen_call = (call or "heads").lower().strip()
            if chosen_call not in ("heads", "tails", "h", "t"):
                chosen_call = "heads"
            author_call = "Heads" if chosen_call.startswith("h") else "Tails"
            opp_call = "Tails" if author_call == "Heads" else "Heads"

            outcome = random.choice(["Heads", "Tails"])
            winner = ctx.author if outcome == author_call else opponent
            loser = opponent if winner == ctx.author else ctx.author

            embed = EmbedBuilder.base(
                title="🪙 PvP Coin Flip Duel",
                description=(
                    f"**Challenger:** {ctx.author.mention} picked **{author_call}**\n"
                    f"**Opponent:** {opponent.mention} gets **{opp_call}**\n\n"
                    f"The coin spun in the air and landed on: **{outcome}**!\n\n"
                    f"🏆 **Winner:** {winner.mention} wins the showdown! 🎉\n"
                    f"Better luck next time, {loser.mention}!"
                ),
                color=BRAND_COLOR,
            )
            await ctx.reply(embed=embed)
            return

        outcome = random.choice(["Heads", "Tails"])
        coin_emoji = "🪙"
        embed = EmbedBuilder.base(
            title=f"{coin_emoji} Coin Flip",
            description=f"The coin landed on: **{outcome}**!",
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    @commands.command(name="coinflip", aliases=["flip", "coin"], help="Flip a coin or challenge another player (e.g. coinflip @user heads).")
    async def coinflip_prefix(
        self,
        ctx: commands.Context,
        opponent: Optional[discord.Member] = None,
        call: Optional[str] = "heads",
    ) -> None:
        await self._execute_coinflip(UnifiedContext.from_prefix(ctx), opponent, call)

    async def _execute_roll(
        self,
        ctx: UnifiedContext,
        target_or_dice: Optional[str] = None,
        opponent: Optional[discord.Member] = None,
    ) -> None:
        """Shared logic for dice roll, supporting solo roll and PvP dice duel."""
        dice_str = "1d6"
        target_opponent: Optional[discord.Member] = opponent

        # Parse arguments: check if target_or_dice is a member mention or dice notation
        if target_or_dice:
            if target_or_dice.startswith("<@") and target_or_dice.endswith(">"):
                # First argument was a member mention
                cleaned = target_or_dice.strip("<@!>")
                if ctx.guild and cleaned.isdigit():
                    target_opponent = ctx.guild.get_member(int(cleaned))
            elif "d" in target_or_dice.lower() or target_or_dice.isdigit():
                dice_str = target_or_dice

        if target_opponent is not None:
            if target_opponent.bot:
                await ctx.send_error("Invalid Opponent", "You cannot challenge a bot! Challenge another player instead.")
                return
            if target_opponent.id == ctx.author.id:
                await ctx.send_error("Invalid Opponent", "You cannot challenge yourself! Challenge another player.")
                return

            p1_roll1, p1_roll2 = random.randint(1, 6), random.randint(1, 6)
            p2_roll1, p2_roll2 = random.randint(1, 6), random.randint(1, 6)
            p1_total = p1_roll1 + p1_roll2
            p2_total = p2_roll1 + p2_roll2

            if p1_total > p2_total:
                result_line = f"🏆 **Winner:** {ctx.author.mention} dominates with **{p1_total}** vs {p2_total}! 🎉"
            elif p2_total > p1_total:
                result_line = f"🏆 **Winner:** {target_opponent.mention} dominates with **{p2_total}** vs {p1_total}! 🎉"
            else:
                result_line = f"🤝 **Draw!** Both rolled **{p1_total}**! What a match!"

            embed = EmbedBuilder.base(
                title="🎲 PvP 2d6 Dice Showdown",
                description=(
                    f"**{ctx.author.mention}** challenged **{target_opponent.mention}** to a dice duel!\n\n"
                    f"🎲 **{ctx.author.display_name}:** `{p1_roll1}` + `{p1_roll2}` = **{p1_total}**\n"
                    f"🎲 **{target_opponent.display_name}:** `{p2_roll1}` + `{p2_roll2}` = **{p2_total}**\n\n"
                    f"{result_line}"
                ),
                color=BRAND_COLOR,
            )
            await ctx.reply(embed=embed)
            return

        try:
            parts = dice_str.lower().split("d")
            if len(parts) == 1:
                count = 1
                sides = int(parts[0])
            else:
                count = int(parts[0]) if parts[0] else 1
                sides = int(parts[1])

            if count < 1 or count > 20:
                await ctx.send_error("Invalid Dice", "You can roll between 1 and 20 dice at once.")
                return
            if sides < 2 or sides > 1000:
                await ctx.send_error("Invalid Sides", "Dice sides must be between 2 and 1000.")
                return

            rolls = [random.randint(1, sides) for _ in range(count)]
            total = sum(rolls)

            embed = EmbedBuilder.base(
                title="🎲 Dice Roll Result",
                description=f"Rolled `{count}d{sides}`: {', '.join(str(r) for r in rolls)}\n\n**Total:** `{total}`",
                color=BRAND_COLOR,
            )
            await ctx.reply(embed=embed)
        except ValueError:
            await ctx.send_error("Format Error", "Usage: `roll [NdS] [opponent]`, e.g., `roll 2d6` or `roll @user`.")

    @commands.command(name="roll", aliases=["dice"], help="Roll dice or challenge another player (e.g. roll @user or roll 2d6).")
    async def roll_prefix(
        self,
        ctx: commands.Context,
        target_or_dice: Optional[str] = None,
        opponent: Optional[discord.Member] = None,
    ) -> None:
        await self._execute_roll(UnifiedContext.from_prefix(ctx), target_or_dice, opponent)

    async def _execute_eightball(self, ctx: UnifiedContext, question: str) -> None:
        """Shared logic for 8-ball."""
        responses = [
            "It is certain.",
            "Without a doubt.",
            "You may rely on it.",
            "Yes, definitely.",
            "As I see it, yes.",
            "Most likely.",
            "Reply hazy, try again.",
            "Ask again later.",
            "Better not tell you now.",
            "Cannot predict now.",
            "Don't count on it.",
            "My reply is no.",
            "My sources say no.",
            "Outlook not so good.",
            "Very doubtful.",
        ]
        answer = random.choice(responses)
        embed = EmbedBuilder.base(
            title="🎱 Magic 8-Ball",
            color=BRAND_COLOR,
        )
        embed.add_field(name="Question", value=question, inline=False)
        embed.add_field(name="Prediction", value=f"*{answer}*", inline=False)
        await ctx.reply(embed=embed)

    @commands.command(name="8ball", aliases=["eightball", "ask"], help="Ask the magic 8-ball a question.")
    async def eightball_prefix(self, ctx: commands.Context, *, question: str) -> None:
        await self._execute_eightball(UnifiedContext.from_prefix(ctx), question)

    async def _execute_challenge(
        self,
        ctx: UnifiedContext,
        opponent: discord.Member,
        game_name: str = "dice",
    ) -> None:
        """Challenge another player to a mini-game showdown."""
        if opponent.bot:
            await ctx.send_error("Invalid Opponent", "You cannot challenge a bot! Challenge another player instead.")
            return
        if opponent.id == ctx.author.id:
            await ctx.send_error("Invalid Opponent", "You cannot challenge yourself! Challenge another player.")
            return

        choice = game_name.lower().strip()
        if choice in ("coin", "coinflip", "flip"):
            await self._execute_coinflip(ctx, opponent=opponent)
        elif choice in ("rps", "rockpaperscissors"):
            minigames = self.bot.get_cog("game")
            if minigames and hasattr(minigames, "_execute_rps"):
                await minigames._execute_rps(ctx, bet=0, opponent=opponent)
            else:
                await ctx.send_error("Game Offline", "Rock Paper Scissors is currently unavailable.")
        elif choice in ("math", "mathduel", "fastmath"):
            await self._execute_mathduel(ctx, opponent)
        else:
            await self._execute_roll(ctx, opponent=opponent)

    @commands.command(name="challenge", aliases=["pvp", "playerchallenge"], help="Challenge another player to a mini-game (e.g. challenge @user [dice/coin/rps/math]).")
    async def challenge_prefix(
        self,
        ctx: commands.Context,
        opponent: discord.Member,
        game: str = "dice",
    ) -> None:
        await self._execute_challenge(UnifiedContext.from_prefix(ctx), opponent, game)

    async def _execute_mathduel(
        self,
        ctx: UnifiedContext,
        opponent: discord.Member,
    ) -> None:
        """Rapid mental math showdown between two players."""
        if opponent.bot:
            await ctx.send_error("Invalid Opponent", "You cannot challenge a bot! Challenge another player instead.")
            return
        if opponent.id == ctx.author.id:
            await ctx.send_error("Invalid Opponent", "You cannot challenge yourself! Challenge another player.")
            return

        num1 = random.randint(12, 99)
        num2 = random.randint(7, 49)
        op_symbol = random.choice(["+", "-", "*"])
        if op_symbol == "+":
            expected = num1 + num2
        elif op_symbol == "-":
            expected = num1 - num2
        else:
            num1 = random.randint(3, 15)
            num2 = random.randint(3, 12)
            expected = num1 * num2

        embed = EmbedBuilder.base(
            title="🧠 Fast Math Duel!",
            description=(
                f"**{ctx.author.mention}** vs **{opponent.mention}**\n\n"
                f"Solve this equation first in chat:\n"
                f"# `{num1} {op_symbol} {num2} = ?`\n\n"
                f"⏱️ You have **15 seconds** to reply with the exact number!"
            ),
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

        def check(m: discord.Message) -> bool:
            if m.channel.id != ctx.channel.id:
                return False
            if m.author.id not in (ctx.author.id, opponent.id):
                return False
            return m.content.strip() == str(expected)

        try:
            msg = await self.bot.wait_for("message", timeout=15.0, check=check)
            winner = msg.author
            loser = opponent if winner.id == ctx.author.id else ctx.author
            win_embed = EmbedBuilder.base(
                title="🏆 Math Duel Winner!",
                description=(
                    f"🎉 {winner.mention} answered correctly with **{expected}**!\n\n"
                    f"Lightning-fast brain power! Well played, {loser.mention}."
                ),
                color=0x00F5A0,
            )
            await ctx.reply(embed=win_embed)
        except asyncio.TimeoutError:
            timeout_embed = EmbedBuilder.base(
                title="⏰ Math Duel Expired",
                description=f"Time's up! Neither player solved it in time.\nThe correct answer was **{expected}**.",
                color=0xF59E0B,
            )
            await ctx.reply(embed=timeout_embed)

    @commands.command(name="mathduel", aliases=["fastmath", "math"], help="Challenge another player to a rapid mental math duel.")
    async def mathduel_prefix(self, ctx: commands.Context, opponent: discord.Member) -> None:
        await self._execute_mathduel(UnifiedContext.from_prefix(ctx), opponent)


async def setup(bot: DeathBot) -> None:
    """Setup hook to register cog."""
    await bot.add_cog(Fun(bot))
