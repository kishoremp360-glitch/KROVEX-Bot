"""Interactive Discord UI views and game boards for Death Bot minigames."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import discord

from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.minigames.views")
BRAND_COLOR = 0x9D4EDD


class RPSView(discord.ui.View):
    """Interactive Rock Paper Scissors game view."""

    def __init__(self, author_id: int, bet: int = 0) -> None:
        super().__init__(timeout=60.0)
        self.author_id = author_id
        self.bet = bet

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This is not your game session.", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]) -> None:
        logger.error("RPSView error on item %s: %s", item, error, exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Could not process your move. Please try again.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Could not process your move. Please try again.", ephemeral=True)
        except Exception:
            pass

    async def _resolve_game(self, interaction: discord.Interaction, user_choice: str) -> None:
        try:
            bot_choice = random.choice(["Rock", "Paper", "Scissors"])
            emojis = {"Rock": "🪨", "Paper": "📄", "Scissors": "✂️"}

            bot: "DeathBot" = interaction.client  # type: ignore
            guild = interaction.guild

            if user_choice == bot_choice:
                result = "draw"
                title = "🤝 It's a Tie!"
                desc = f"You chose {emojis[user_choice]} **{user_choice}**.\nBot chose {emojis[bot_choice]} **{bot_choice}**.\n\nYour bet of `{self.bet}` {KrovexEmoji.CRYSTALS} Coins was refunded."
                delta = 0
            elif (user_choice == "Rock" and bot_choice == "Scissors") or \
                 (user_choice == "Paper" and bot_choice == "Rock") or \
                 (user_choice == "Scissors" and bot_choice == "Paper"):
                result = "win"
                title = f"{KrovexEmoji.VICTORY} {KrovexEmoji.TADA} You Won!"
                desc = f"You chose {emojis[user_choice]} **{user_choice}**.\nBot chose {emojis[bot_choice]} **{bot_choice}**.\n\nYou won **+{self.bet}** {KrovexEmoji.CRYSTALS} Coins!"
                delta = self.bet
            else:
                result = "loss"
                title = f"{KrovexEmoji.YOU_SUCK} You Lost!"
                desc = f"You chose {emojis[user_choice]} **{user_choice}**.\nBot chose {emojis[bot_choice]} **{bot_choice}**.\n\nYou lost **-{self.bet}** {KrovexEmoji.CRYSTALS} Coins!"
                delta = -self.bet

            embed = EmbedBuilder.base(title=title, description=desc, color=BRAND_COLOR)
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=None)
            else:
                await interaction.edit_original_response(embed=embed, view=None)
            self.stop()

            # Background persistence
            if guild and bot.economy_repo and self.bet > 0:
                if result == "win":
                    await bot.economy_repo.add_money(guild.id, self.author_id, self.bet)
                elif result == "loss":
                    await bot.economy_repo.remove_money(guild.id, self.author_id, self.bet)

            if guild and bot.minigame_repo:
                await bot.minigame_repo.record_game(
                    guild.id,
                    self.author_id,
                    "rps",
                    won=(result == "win"),
                    drawn=(result == "draw"),
                    coins_delta=delta,
                )
            self.stop()
        except Exception as exc:
            logger.error("Error executing RPS move: %s", exc, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Failed to resolve game move. Please try again.", ephemeral=True)

    @discord.ui.button(label="Rock", emoji="🪨", style=discord.ButtonStyle.primary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._resolve_game(interaction, "Rock")

    @discord.ui.button(label="Paper", emoji="📄", style=discord.ButtonStyle.primary)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._resolve_game(interaction, "Paper")

    @discord.ui.button(label="Scissors", emoji="✂️", style=discord.ButtonStyle.primary)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._resolve_game(interaction, "Scissors")


class TicTacToeButton(discord.ui.Button["TicTacToeView"]):
    """Individual button representing one square on the 3x3 Tic-Tac-Toe grid."""

    def __init__(self, x: int, y: int) -> None:
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=y)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        view: TicTacToeView = self.view

        # Check turn
        current_player = view.player_x if view.current_turn == "X" else view.player_o
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("❌ It is not your turn!", ephemeral=True)
            return

        # Mark cell
        self.style = discord.ButtonStyle.danger if view.current_turn == "X" else discord.ButtonStyle.success
        self.label = view.current_turn
        self.disabled = True
        view.board[self.y][self.x] = view.current_turn

        winner = view.check_winner()
        if winner:
            winning_player = view.player_x if winner == "X" else view.player_o
            for child in view.children:
                child.disabled = True  # type: ignore
            embed = EmbedBuilder.success(
                title="🏆 Tic-Tac-Toe Victor!",
                description=f"Congratulations {winning_player.mention}! You won the game with `{winner}`!",
            )
            await interaction.response.edit_message(embed=embed, view=view)
            view.stop()
            bot: "DeathBot" = interaction.client  # type: ignore
            if interaction.guild and bot.minigame_repo:
                await bot.minigame_repo.record_game(interaction.guild.id, winning_player.id, "tictactoe", won=True)
                losing_player = view.player_o if winner == "X" else view.player_x
                await bot.minigame_repo.record_game(interaction.guild.id, losing_player.id, "tictactoe", won=False)
            return

        if view.is_board_full():
            for child in view.children:
                child.disabled = True  # type: ignore
            embed = EmbedBuilder.warning(title="🤝 Tic-Tac-Toe Tie!", description="The grid is completely full. Draw game!")
            await interaction.response.edit_message(embed=embed, view=view)
            view.stop()
            bot: "DeathBot" = interaction.client  # type: ignore
            if interaction.guild and bot.minigame_repo:
                await bot.minigame_repo.record_game(interaction.guild.id, view.player_x.id, "tictactoe", won=False, drawn=True)
                await bot.minigame_repo.record_game(interaction.guild.id, view.player_o.id, "tictactoe", won=False, drawn=True)
            return

        # Switch turns
        view.current_turn = "O" if view.current_turn == "X" else "X"
        next_player = view.player_x if view.current_turn == "X" else view.player_o
        embed = EmbedBuilder.base(
            title="🎮 Tic-Tac-Toe Match",
            description=f"**X:** {view.player_x.mention}\n**O:** {view.player_o.mention}\n\n👉 Current Turn: {next_player.mention} (`{view.current_turn}`)",
            color=BRAND_COLOR,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class TicTacToeView(discord.ui.View):
    """Full 3x3 interactive Tic-Tac-Toe grid view."""

    def __init__(self, player_x: discord.Member, player_o: discord.Member) -> None:
        super().__init__(timeout=180.0)
        self.player_x = player_x
        self.player_o = player_o
        self.current_turn = "X"
        self.board = [[None, None, None], [None, None, None], [None, None, None]]

        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y))

    def is_board_full(self) -> bool:
        return all(all(cell is not None for cell in row) for row in self.board)

    def check_winner(self) -> Optional[str]:
        # Rows
        for row in self.board:
            if row[0] is not None and row[0] == row[1] == row[2]:
                return row[0]
        # Columns
        for col in range(3):
            if self.board[0][col] is not None and self.board[0][col] == self.board[1][col] == self.board[2][col]:
                return self.board[0][col]
        # Diagonals
        if self.board[0][0] is not None and self.board[0][0] == self.board[1][1] == self.board[2][2]:
            return self.board[0][0]
        if self.board[0][2] is not None and self.board[0][2] == self.board[1][1] == self.board[2][0]:
            return self.board[0][2]
        return None


class BlackjackCard:
    """Card model for Blackjack."""

    def __init__(self, rank: str, suit: str) -> None:
        self.rank = rank
        self.suit = suit

    @property
    def value(self) -> int:
        if self.rank in ("J", "Q", "K"):
            return 10
        if self.rank == "A":
            return 11
        return int(self.rank)

    def __str__(self) -> str:
        return f"`{self.rank}{self.suit}`"


class BlackjackView(discord.ui.View):
    """Interactive Blackjack (21) table view."""

    SUITS = ["♠", "♥", "♦", "♣"]
    RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]

    def __init__(self, author_id: int, bet: int = 0) -> None:
        super().__init__(timeout=120.0)
        self.author_id = author_id
        self.bet = bet
        self.deck = [BlackjackCard(r, s) for s in self.SUITS for r in self.RANKS]
        random.shuffle(self.deck)

        self.player_hand: List[BlackjackCard] = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand: List[BlackjackCard] = [self.deck.pop(), self.deck.pop()]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Not your blackjack game.", ephemeral=True)
            return False
        return True

    def _calculate_score(self, hand: List[BlackjackCard]) -> int:
        score = sum(c.value for c in hand)
        aces = sum(1 for c in hand if c.rank == "A")
        while score > 21 and aces > 0:
            score -= 10
            aces -= 1
        return score

    def get_embed(self, hide_dealer: bool = True, outcome_title: Optional[str] = None, outcome_desc: Optional[str] = None) -> discord.Embed:
        p_score = self._calculate_score(self.player_hand)
        p_cards = " ".join(str(c) for c in self.player_hand)

        if hide_dealer:
            d_cards = f"{str(self.dealer_hand[0])} `🂠`"
            d_score = "?"
        else:
            d_cards = " ".join(str(c) for c in self.dealer_hand)
            d_score = str(self._calculate_score(self.dealer_hand))

        embed = EmbedBuilder.base(
            title=outcome_title or "🃏 Blackjack Table",
            description=outcome_desc or f"Bet: {KrovexEmoji.CRYSTALS} **{self.bet:,}** Coins",
            color=BRAND_COLOR,
        )
        embed.add_field(name=f"Your Hand ({p_score})", value=p_cards, inline=False)
        embed.add_field(name=f"Dealer's Hand ({d_score})", value=d_cards, inline=False)
        return embed

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="➕")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.player_hand.append(self.deck.pop())
        p_score = self._calculate_score(self.player_hand)

        if p_score > 21:
            # Bust
            bot: "DeathBot" = interaction.client  # type: ignore
            if interaction.guild and bot.economy_repo and self.bet > 0:
                await bot.economy_repo.remove_money(interaction.guild.id, self.author_id, self.bet)
            if interaction.guild and bot.minigame_repo:
                await bot.minigame_repo.record_game(interaction.guild.id, self.author_id, "blackjack", won=False, coins_delta=-self.bet)

            embed = self.get_embed(hide_dealer=False, outcome_title="💥 Busted! You Lost", outcome_desc=f"You busted with `{p_score}`! Lost **-{self.bet}** coins.")
            await interaction.response.edit_message(embed=embed, view=None)
            self.stop()
        else:
            embed = self.get_embed(hide_dealer=True)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="🛑")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        p_score = self._calculate_score(self.player_hand)

        # Dealer draws until 17 or higher
        while self._calculate_score(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())

        d_score = self._calculate_score(self.dealer_hand)
        bot: "DeathBot" = interaction.client  # type: ignore
        guild = interaction.guild

        if d_score > 21 or p_score > d_score:
            # Player wins
            delta = self.bet
            if guild and bot.economy_repo and self.bet > 0:
                await bot.economy_repo.add_money(guild.id, self.author_id, self.bet)
            if guild and bot.minigame_repo:
                await bot.minigame_repo.record_game(guild.id, self.author_id, "blackjack", won=True, coins_delta=delta)
            embed = self.get_embed(hide_dealer=False, outcome_title=f"{KrovexEmoji.VICTORY} {KrovexEmoji.TADA} You Won Blackjack!", outcome_desc=f"You beat the dealer! Won **+{self.bet}** {KrovexEmoji.CRYSTALS} Coins!")
        elif p_score == d_score:
            # Push
            if guild and bot.minigame_repo:
                await bot.minigame_repo.record_game(guild.id, self.author_id, "blackjack", won=False, drawn=True)
            embed = self.get_embed(hide_dealer=False, outcome_title="🤝 Push / Tie!", outcome_desc=f"Both hands scored `{p_score}`. Bet refunded.")
        else:
            # Dealer wins
            delta = -self.bet
            if guild and bot.economy_repo and self.bet > 0:
                await bot.economy_repo.remove_money(guild.id, self.author_id, self.bet)
            if guild and bot.minigame_repo:
                await bot.minigame_repo.record_game(guild.id, self.author_id, "blackjack", won=False, coins_delta=delta)
            embed = self.get_embed(hide_dealer=False, outcome_title=f"{KrovexEmoji.YOU_SUCK} Dealer Won", outcome_desc=f"Dealer had `{d_score}`, you had `{p_score}`. Lost **-{self.bet}** {KrovexEmoji.CRYSTALS} Coins.")

        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()


class HigherLowerView(discord.ui.View):
    """Higher or Lower card game view."""

    def __init__(self, author_id: int, start_val: int = 50, streak: int = 0) -> None:
        super().__init__(timeout=60.0)
        self.author_id = author_id
        self.current_val = start_val
        self.streak = streak

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This is not your game session.", ephemeral=True)
            return False
        return True

    async def _guess(self, interaction: discord.Interaction, is_higher: bool) -> None:
        new_val = random.randint(1, 100)
        correct = (new_val >= self.current_val) if is_higher else (new_val <= self.current_val)

        bot: "DeathBot" = interaction.client  # type: ignore
        guild = interaction.guild

        if correct:
            self.streak += 1
            self.current_val = new_val
            embed = EmbedBuilder.success(
                title=f"✅ Correct! Current Number: {new_val}",
                description=f"🔥 **Current Streak:** `{self.streak}`\nIs the next number (1-100) **Higher** or **Lower**?",
            )
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            embed = EmbedBuilder.danger(
                title="❌ Wrong Guess! Game Over",
                description=f"The number was **{new_val}** (previous was {self.current_val}).\n\n🏆 Final Streak: **{self.streak}**",
            )
            if guild and bot.minigame_repo:
                await bot.minigame_repo.record_game(guild.id, self.author_id, "higherlower", won=(self.streak >= 3), score=self.streak)
            await interaction.response.edit_message(embed=embed, view=None)
            self.stop()

    @discord.ui.button(label="Higher", style=discord.ButtonStyle.success, emoji="⬆️")
    async def higher(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._guess(interaction, True)

    @discord.ui.button(label="Lower", style=discord.ButtonStyle.danger, emoji="⬇️")
    async def lower(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._guess(interaction, False)


class TriviaView(discord.ui.View):
    """Multiple choice trivia interactive view."""

    def __init__(self, author_id: int, question: str, options: List[str], correct_idx: int) -> None:
        super().__init__(timeout=45.0)
        self.author_id = author_id
        self.question = question
        self.options = options
        self.correct_idx = correct_idx

        for i, opt in enumerate(options):
            btn = discord.ui.Button(label=opt[:80], style=discord.ButtonStyle.secondary, custom_id=f"trivia_{i}")
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction) -> None:
            if interaction.user.id != self.author_id:
                await interaction.response.send_message("❌ This trivia prompt is not for you.", ephemeral=True)
                return

            bot: "DeathBot" = interaction.client  # type: ignore
            guild = interaction.guild

            if index == self.correct_idx:
                embed = EmbedBuilder.success(
                    title=f"{KrovexEmoji.VICTORY} {KrovexEmoji.SCORE_100} Correct Answer!",
                    description=f"**Question:** {self.question}\n\n✅ You selected: **{self.options[index]}**!",
                )
                if guild and bot.minigame_repo:
                    await bot.minigame_repo.record_game(guild.id, self.author_id, "trivia", won=True)
            else:
                embed = EmbedBuilder.danger(
                    title=f"{KrovexEmoji.YOU_SUCK} Incorrect!",
                    description=f"**Question:** {self.question}\n\nYour answer: **{self.options[index]}**\nCorrect answer: **{self.options[self.correct_idx]}**",
                )
                if guild and bot.minigame_repo:
                    await bot.minigame_repo.record_game(guild.id, self.author_id, "trivia", won=False)

            await interaction.response.edit_message(embed=embed, view=None)
            self.stop()
        return callback


class PvPRPSView(discord.ui.View):
    """2-Player PvP Rock Paper Scissors View."""

    def __init__(self, player1: discord.Member, player2: discord.Member, bet: int = 0) -> None:
        super().__init__(timeout=120.0)
        self.player1 = player1
        self.player2 = player2
        self.bet = bet
        self.choices: Dict[int, str] = {}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.player1.id, self.player2.id):
            await interaction.response.send_message("❌ You are not part of this Rock Paper Scissors match.", ephemeral=True)
            return False
        return True

    async def _handle_choice(self, interaction: discord.Interaction, choice: str) -> None:
        uid = interaction.user.id
        if uid in self.choices:
            await interaction.response.send_message("❌ You already locked in your move!", ephemeral=True)
            return

        self.choices[uid] = choice
        emojis = {"Rock": "🪨", "Paper": "📄", "Scissors": "✂️"}

        if len(self.choices) < 2:
            other_player = self.player2 if uid == self.player1.id else self.player1
            await interaction.response.send_message(
                f"✅ You chose **{emojis[choice]} {choice}**! Waiting for {other_player.mention}...",
                ephemeral=True,
            )
            embed = EmbedBuilder.base(
                title="✂️ Rock Paper Scissors Duel",
                description=(
                    f"**Player 1:** {self.player1.mention} ({'✅ Locked in' if self.player1.id in self.choices else '⏳ Choosing...'})\n"
                    f"**Player 2:** {self.player2.mention} ({'✅ Locked in' if self.player2.id in self.choices else '⏳ Choosing...'})\n\n"
                    f"Bet: **{self.bet:,}** Coins\n*Click a button below to secretly lock in your move!*"
                ),
                color=BRAND_COLOR,
            )
            await interaction.message.edit(embed=embed, view=self)
            return

        # Both moves locked in
        p1_choice = self.choices[self.player1.id]
        p2_choice = self.choices[self.player2.id]

        bot: "DeathBot" = interaction.client  # type: ignore
        guild = interaction.guild

        if p1_choice == p2_choice:
            title = "🤝 It's a Tie!"
            desc = (
                f"{self.player1.mention} chose {emojis[p1_choice]} **{p1_choice}**\n"
                f"{self.player2.mention} chose {emojis[p2_choice]} **{p2_choice}**\n\n"
                f"Both players threw the exact same move! Bets refunded."
            )
            winner, loser = None, None
        elif (p1_choice == "Rock" and p2_choice == "Scissors") or \
             (p1_choice == "Paper" and p2_choice == "Rock") or \
             (p1_choice == "Scissors" and p2_choice == "Paper"):
            winner = self.player1
            loser = self.player2
            title = f"{KrovexEmoji.VICTORY} {self.player1.display_name} Wins!"
            desc = (
                f"{self.player1.mention} chose {emojis[p1_choice]} **{p1_choice}**\n"
                f"{self.player2.mention} chose {emojis[p2_choice]} **{p2_choice}**\n\n"
                f"🏆 **{self.player1.mention} defeated {self.player2.mention}!**"
            )
            if self.bet > 0:
                desc += f"\nWon **+{self.bet:,}** Coins from the wager!"
        else:
            winner = self.player2
            loser = self.player1
            title = f"{KrovexEmoji.VICTORY} {self.player2.display_name} Wins!"
            desc = (
                f"{self.player1.mention} chose {emojis[p1_choice]} **{p1_choice}**\n"
                f"{self.player2.mention} chose {emojis[p2_choice]} **{p2_choice}**\n\n"
                f"🏆 **{self.player2.mention} defeated {self.player1.mention}!**"
            )
            if self.bet > 0:
                desc += f"\nWon **+{self.bet:,}** Coins from the wager!"

        embed = EmbedBuilder.base(title=title, description=desc, color=BRAND_COLOR)

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.message.edit(embed=embed, view=self)

        self.stop()

        if guild and bot.economy_repo and self.bet > 0 and winner and loser:
            try:
                await bot.economy_repo.add_money(guild.id, winner.id, self.bet)
                await bot.economy_repo.remove_money(guild.id, loser.id, self.bet)
            except Exception as eco_err:
                logger.error("Error transferring RPS wager: %s", eco_err)

    @discord.ui.button(label="Rock", emoji="🪨", style=discord.ButtonStyle.primary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_choice(interaction, "Rock")

    @discord.ui.button(label="Paper", emoji="📄", style=discord.ButtonStyle.primary)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_choice(interaction, "Paper")

    @discord.ui.button(label="Scissors", emoji="✂️", style=discord.ButtonStyle.primary)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_choice(interaction, "Scissors")


class RussianRouletteView(discord.ui.View):
    """High-Stakes 2-Player Russian Roulette Duel."""

    def __init__(self, player1: discord.Member, player2: discord.Member, bet: int = 0) -> None:
        super().__init__(timeout=120.0)
        self.player1 = player1
        self.player2 = player2
        self.bet = bet
        self.chamber = random.randint(1, 6)
        self.current_chamber = 1
        self.current_turn = player1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.player1.id, self.player2.id):
            await interaction.response.send_message("❌ You are not part of this duel.", ephemeral=True)
            return False
        if interaction.user.id != self.current_turn.id:
            await interaction.response.send_message(f"⏳ It is {self.current_turn.mention}'s turn to pull the trigger!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Pull Trigger", emoji="🔫", style=discord.ButtonStyle.danger)
    async def pull_trigger(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.current_chamber == self.chamber:
            loser = self.current_turn
            winner = self.player2 if loser.id == self.player1.id else self.player1

            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True

            embed = EmbedBuilder.base(
                title="💥 BANG! Chamber Fired!",
                description=(
                    f"💀 **{loser.mention} pulled the trigger on chamber #{self.current_chamber}... BANG!**\n\n"
                    f"🏆 **{winner.mention} survives the Russian Roulette duel!**"
                    + (f"\nWon **+{self.bet:,}** Coins from the wager!" if self.bet > 0 else "")
                ),
                color=0xFF0033,
            )
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()

            bot: "DeathBot" = interaction.client  # type: ignore
            if interaction.guild and bot.economy_repo and self.bet > 0:
                try:
                    await bot.economy_repo.add_money(interaction.guild.id, winner.id, self.bet)
                    await bot.economy_repo.remove_money(interaction.guild.id, loser.id, self.bet)
                except Exception:
                    pass
        else:
            prev_player = self.current_turn
            self.current_turn = self.player2 if self.current_turn.id == self.player1.id else self.player1
            self.current_chamber += 1

            embed = EmbedBuilder.base(
                title="😅 *Click!* Chamber Empty",
                description=(
                    f"💨 {prev_player.mention} pulled the trigger on chamber #{self.current_chamber - 1}... **Click! Safe!**\n\n"
                    f"👉 It is now {self.current_turn.mention}'s turn to pull the trigger! (Chamber #{self.current_chamber}/6)"
                ),
                color=BRAND_COLOR,
            )
            await interaction.response.edit_message(embed=embed, view=self)


class DiceDuelView(discord.ui.View):
    """2-Player Dice Duel Minigame."""

    def __init__(self, player1: discord.Member, player2: discord.Member, bet: int = 0) -> None:
        super().__init__(timeout=90.0)
        self.player1 = player1
        self.player2 = player2
        self.bet = bet
        self.rolls: Dict[int, int] = {}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.player1.id, self.player2.id):
            await interaction.response.send_message("❌ You are not part of this dice duel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Roll Dice (2d6)", emoji="🎲", style=discord.ButtonStyle.success)
    async def roll(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        uid = interaction.user.id
        if uid in self.rolls:
            await interaction.response.send_message("❌ You already rolled your dice!", ephemeral=True)
            return

        roll_val = random.randint(1, 6) + random.randint(1, 6)
        self.rolls[uid] = roll_val

        if len(self.rolls) < 2:
            other_player = self.player2 if uid == self.player1.id else self.player1
            embed = EmbedBuilder.base(
                title="🎲 Dice Duel in Progress",
                description=(
                    f"**{interaction.user.display_name}** rolled **`{roll_val}`**! 🎲\n\n"
                    f"Waiting for {other_player.mention} to roll..."
                ),
                color=BRAND_COLOR,
            )
            await interaction.response.edit_message(embed=embed, view=self)
            return

        r1 = self.rolls[self.player1.id]
        r2 = self.rolls[self.player2.id]

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        if r1 == r2:
            title = "🤝 Tie Roll!"
            desc = f"{self.player1.mention} rolled `{r1}`\n{self.player2.mention} rolled `{r2}`\n\nIt's a dead tie! Bets refunded."
            winner, loser = None, None
        elif r1 > r2:
            title = f"🎲 {self.player1.display_name} Wins!"
            desc = f"{self.player1.mention} rolled **`{r1}`**\n{self.player2.mention} rolled **`{r2}`**\n\n🏆 **{self.player1.mention} wins the dice duel!**"
            winner, loser = self.player1, self.player2
        else:
            title = f"🎲 {self.player2.display_name} Wins!"
            desc = f"{self.player1.mention} rolled **`{r1}`**\n{self.player2.mention} rolled **`{r2}`**\n\n🏆 **{self.player2.mention} wins the dice duel!**"
            winner, loser = self.player2, self.player1

        if self.bet > 0 and winner:
            desc += f"\nWon **+{self.bet:,}** Coins from the wager!"

        embed = EmbedBuilder.base(title=title, description=desc, color=BRAND_COLOR)
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

        bot: "DeathBot" = interaction.client  # type: ignore
        if interaction.guild and bot.economy_repo and self.bet > 0 and winner and loser:
            try:
                await bot.economy_repo.add_money(interaction.guild.id, winner.id, self.bet)
                await bot.economy_repo.remove_money(interaction.guild.id, loser.id, self.bet)
            except Exception:
                pass


async def setup(bot: Any) -> None:
    """Extension dummy setup."""
    pass


