"""Interactive views and confirmation dialogs for the server economy system."""
from __future__ import annotations

import discord

from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji

BRAND_COLOR = 0x9D4EDD


class TransferConfirmView(discord.ui.View):
    """Safety confirmation view for large peer-to-peer balance transfers."""

    def __init__(self, sender_id: int, receiver_id: int, amount: int, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self.amount = amount
        self.confirmed: bool = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.sender_id:
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} This confirmation is not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm Transfer", style=discord.ButtonStyle.success, emoji="💸")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = True
        self.stop()
        await interaction.response.edit_message(content="Processing transfer...", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji=KrovexEmoji.CROSS.partial)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = False
        self.stop()
        embed = EmbedBuilder.warning(title="Transfer Cancelled", description="The currency transfer was cancelled by the sender.")
        await interaction.response.edit_message(embed=embed, view=None)


async def setup(bot: Any) -> None:
    """Extension dummy setup."""
    pass

