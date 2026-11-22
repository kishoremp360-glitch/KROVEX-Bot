"""Interactive UI components and persistent views for the server shop."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import discord

from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.shop.views")
BRAND_COLOR = 0x9D4EDD


class ShopItemSelect(discord.ui.Select):
    """Dropdown menu to select an item to inspect or purchase."""

    def __init__(self, items: List[Dict[str, Any]]) -> None:
        options = []
        for it in items[:25]:
            stock_str = "Unlimited" if it["stock"] < 0 else f"{it['stock']} left"
            options.append(
                discord.SelectOption(
                    label=it["name"][:100],
                    value=str(it["item_id"]),
                    description=f"{it['price']} Coins • {stock_str}"[:100],
                    emoji="🏷️",
                )
            )
        super().__init__(
            placeholder="Select an item to view or buy...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="shop:select_item",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        item_id = int(self.values[0])
        bot: "DeathBot" = interaction.client  # type: ignore
        if not bot.shop_repo:
            return

        item = await bot.shop_repo.get_item(item_id)
        if not item:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)
            return

        stock_str = "Unlimited" if item["stock"] < 0 else f"{item['stock']} in stock"
        role_mention = f"<@&{item['role_id']}>" if item.get("role_id") else "`None`"

        embed = EmbedBuilder.base(
            title=f"🛍️ Item Details • {item['name']}",
            description=item.get("description") or "No description provided.",
            color=BRAND_COLOR,
        )
        embed.add_field(name="Price", value=f"🪙 **{item['price']:,}** Coins", inline=True)
        embed.add_field(name="Stock", value=f"📦 **{stock_str}**", inline=True)
        embed.add_field(name="Role Unlock", value=role_mention, inline=True)

        view = ShopBuyConfirmView(item, buyer_id=interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ShopBuyConfirmView(discord.ui.View):
    """Confirmation button for purchasing a shop item with buyer authorization and concurrency protection."""

    def __init__(self, item: Dict[str, Any], buyer_id: Optional[int] = None) -> None:
        super().__init__(timeout=120.0)
        self.item = item
        self.buyer_id = buyer_id
        self._lock = asyncio.Lock()
        self._purchased = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.buyer_id is not None and interaction.user.id != self.buyer_id:
            await interaction.response.send_message(
                f"{KrovexEmoji.CROSS} This purchase confirmation is not for you.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True

    @discord.ui.button(label="Buy Item", style=discord.ButtonStyle.success, emoji="🛒")
    async def buy_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot: "DeathBot" = interaction.client  # type: ignore
        guild = interaction.guild
        user = interaction.user

        if not guild or not isinstance(user, discord.Member) or not bot.shop_repo:
            return

        async with self._lock:
            if self._purchased:
                await interaction.response.send_message("⚠️ This purchase has already been processed.", ephemeral=True)
                return
            self._purchased = True

            ok, msg, pdata = await bot.shop_repo.buy_item(guild.id, user.id, self.item["item_id"])
            if not ok:
                for child in self.children:
                    if hasattr(child, "disabled"):
                        child.disabled = True
                await interaction.response.edit_message(content=f"{KrovexEmoji.CROSS} {msg}", view=None)
                self.stop()
                return

            # Handle role grant if item has role_id
            role_granted_msg = ""
            role_id = self.item.get("role_id")
            if role_id:
                role = guild.get_role(role_id)
                if role:
                    if guild.me.guild_permissions.manage_roles and guild.me.top_role.position > role.position:
                        try:
                            await user.add_roles(role, reason=f"Purchased item {self.item['name']}")
                            role_granted_msg = f"\n{KrovexEmoji.TADA} You have been granted the {role.mention} role!"
                        except Exception as e:
                            logger.error("Could not grant purchased role: %s", e)
                    else:
                        role_granted_msg = f"\n⚠️ Note: The bot could not automatically grant {role.mention} due to role hierarchy. Please contact staff."

            embed = EmbedBuilder.success(
                title="Purchase Successful!",
                description=f"{msg}{role_granted_msg}\n\n*Item added to your inventory. View with `inventory`.*",
            )
            for child in self.children:
                if hasattr(child, "disabled"):
                    child.disabled = True
            await interaction.response.edit_message(embed=embed, view=None)
            self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji=KrovexEmoji.CROSS.partial)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            self._purchased = True
            for child in self.children:
                if hasattr(child, "disabled"):
                    child.disabled = True
            await interaction.response.edit_message(content="Purchase cancelled.", view=None)
            self.stop()


class ShopPanelView(discord.ui.View):
    """Persistent catalog panel displayed in the server shop channel."""

    def __init__(self, items: Optional[List[Dict[str, Any]]] = None) -> None:
        super().__init__(timeout=None)
        if items:
            self.add_item(ShopItemSelect(items))

    @discord.ui.button(label="View Inventory", emoji="🎒", style=discord.ButtonStyle.secondary, custom_id="shop:view_inv", row=1)
    async def view_inv(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot: "DeathBot" = interaction.client  # type: ignore
        if not bot.economy_repo or not interaction.guild:
            return

        inv = await bot.economy_repo.get_inventory(interaction.guild.id, interaction.user.id)
        if not inv:
            await interaction.response.send_message("🎒 Your inventory is currently empty.", ephemeral=True)
            return

        lines = [f"• **{it['name']}** x`{it['quantity']}` — {it.get('description', '')}" for it in inv]
        embed = EmbedBuilder.base(
            title=f"🎒 Your Inventory • {interaction.user.display_name}",
            description="\n".join(lines),
            color=BRAND_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: Any) -> None:
    """Extension dummy setup."""
    pass

