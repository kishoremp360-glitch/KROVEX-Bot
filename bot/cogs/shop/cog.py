"""Configurable Server Shop Cog connected to virtual economy and inventory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.shop.views import ShopPanelView
from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.shop")
BRAND_COLOR = 0x9D4EDD


class ShopCog(commands.GroupCog, group_name="shop"):
    """Server marketplace, catalog management, role purchases, and transaction refunds."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot
        super().__init__()

    async def cog_load(self) -> None:
        """Register persistent views on load."""
        self.bot.add_view(ShopPanelView())

    # =========================================================
    # CORE SHARED BUSINESS LOGIC
    # =========================================================

    async def _execute_view(self, ctx: UnifiedContext, category_name: Optional[str] = None) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return

        cat_id = None
        if category_name:
            cats = await self.bot.shop_repo.get_categories(ctx.guild.id)
            for c in cats:
                if c["name"].lower() == category_name.lower():
                    cat_id = c["category_id"]
                    break

        items = await self.bot.shop_repo.get_items(ctx.guild.id, category_id=cat_id)
        if not items:
            await ctx.reply(f"{KrovexEmoji.KITTY_MUFFIN} The server shop is currently empty. Staff can add items with `shopadd`.")
            return

        lines = []
        for it in items:
            stock_str = "Unlimited" if it["stock"] < 0 else f"{it['stock']} left"
            role_str = f" `[Role: <@&{it['role_id']}>]`" if it.get("role_id") else ""
            lines.append(f"• **{it['name']}** — 🪙 `{it['price']:,}` Coins *(Stock: {stock_str})*{role_str}\n  *{it.get('description', 'No description')}*")

        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.KITTY_MUFFIN} Server Shop Catalog • {ctx.guild.name}",
            description="\n\n".join(lines),
            color=BRAND_COLOR,
        )
        embed.set_footer(text="Use the dropdown menu below or type 'shopbuy <item>' to purchase.", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)

        view = ShopPanelView(items=items)
        await ctx.reply(embed=embed, view=view)

    async def _execute_setup(self, ctx: UnifiedContext, channel: Optional[discord.TextChannel] = None) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        target_ch = channel or ctx.channel
        items = await self.bot.shop_repo.get_items(ctx.guild.id)
        embed = EmbedBuilder.base(
            title=f"🏪 Official Server Marketplace • {ctx.guild.name}",
            description="Welcome to the server store! Browse items and role unlocks below.",
            color=BRAND_COLOR,
        )
        view = ShopPanelView(items=items)
        if isinstance(target_ch, discord.TextChannel):
            await target_ch.send(embed=embed, view=view)
            await ctx.send_success("Shop Deployed", f"Persistent shop storefront deployed in {target_ch.mention}!")

    async def _execute_add(
        self,
        ctx: UnifiedContext,
        name: str,
        price: int,
        description: str = "",
        role: Optional[discord.Role] = None,
        stock: int = -1,
    ) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if price <= 0:
            await ctx.send_error("Invalid Price", "Price must be greater than zero.")
            return

        role_id = role.id if role else None
        item_id = await self.bot.shop_repo.create_item(
            ctx.guild.id,
            name=name,
            description=description,
            price=price,
            role_id=role_id,
            stock=stock,
        )
        stock_str = "Unlimited" if stock < 0 else f"{stock} units"
        role_mention = role.mention if role else "`None`"

        embed = EmbedBuilder.success(
            title="Item Added to Shop",
            description=(
                f"**Item Name:** `{name}` (ID: `{item_id}`)\n"
                f"**Price:** 🪙 `{price:,}` Coins\n"
                f"**Stock:** `{stock_str}`\n"
                f"**Role Reward:** {role_mention}\n"
                f"**Description:** *{description or 'None'}*"
            ),
        )
        await ctx.reply(embed=embed)

    async def _execute_edit(self, ctx: UnifiedContext, item_name_or_id: str, new_price: Optional[int] = None, new_stock: Optional[int] = None, new_desc: Optional[str] = None) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        # Find item
        item = None
        if item_name_or_id.isdigit():
            item = await self.bot.shop_repo.get_item(int(item_name_or_id))
        if not item:
            items = await self.bot.shop_repo.get_items(ctx.guild.id)
            for it in items:
                if it["name"].lower() == item_name_or_id.lower():
                    item = it
                    break

        if not item or item["guild_id"] != ctx.guild.id:
            await ctx.send_error("Not Found", f"Item **{item_name_or_id}** not found in this shop.")
            return

        updates = {}
        if new_price is not None and new_price > 0:
            updates["price"] = new_price
        if new_stock is not None:
            updates["stock"] = new_stock
        if new_desc is not None:
            updates["description"] = new_desc

        if not updates:
            await ctx.send_error("No Updates", "Please specify at least one parameter to update.")
            return

        await self.bot.shop_repo.edit_item(item["item_id"], **updates)
        await ctx.send_success("Item Updated", f"Updated settings for **{item['name']}**.")

    async def _execute_remove(self, ctx: UnifiedContext, item_name_or_id: str) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        item = None
        if item_name_or_id.isdigit():
            item = await self.bot.shop_repo.get_item(int(item_name_or_id))
        if not item:
            items = await self.bot.shop_repo.get_items(ctx.guild.id)
            for it in items:
                if it["name"].lower() == item_name_or_id.lower():
                    item = it
                    break

        if not item or item["guild_id"] != ctx.guild.id:
            await ctx.send_error("Not Found", f"Item **{item_name_or_id}** not found.")
            return

        await self.bot.shop_repo.delete_item(ctx.guild.id, item["item_id"])
        await ctx.send_success("Item Removed", f"Deleted **{item['name']}** from the shop.")

    async def _execute_item(self, ctx: UnifiedContext, item_name_or_id: str) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return

        item = None
        if item_name_or_id.isdigit():
            item = await self.bot.shop_repo.get_item(int(item_name_or_id))
        if not item:
            items = await self.bot.shop_repo.get_items(ctx.guild.id)
            for it in items:
                if it["name"].lower() == item_name_or_id.lower():
                    item = it
                    break

        if not item or item["guild_id"] != ctx.guild.id:
            await ctx.send_error("Not Found", f"Item **{item_name_or_id}** not found.")
            return

        stock_str = "Unlimited" if item["stock"] < 0 else f"{item['stock']} units left"
        role_mention = f"<@&{item['role_id']}>" if item.get("role_id") else "`None`"

        embed = EmbedBuilder.base(
            title=f"🏷️ Item Specification • {item['name']}",
            description=item.get("description") or "No description provided.",
            color=BRAND_COLOR,
        )
        embed.add_field(name="Item ID", value=f"`{item['item_id']}`", inline=True)
        embed.add_field(name="Price", value=f"🪙 `{item['price']:,}` Coins", inline=True)
        embed.add_field(name="Stock", value=f"📦 `{stock_str}`", inline=True)
        embed.add_field(name="Role Reward", value=role_mention, inline=True)
        embed.add_field(name="Buyable", value=f"{'✅ Yes' if item['is_buyable'] else '❌ Disabled'}", inline=True)
        await ctx.reply(embed=embed)

    async def _execute_list(self, ctx: UnifiedContext) -> None:
        await self._execute_view(ctx)

    async def _execute_buy(self, ctx: UnifiedContext, item_name_or_id: str) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return

        item = None
        if item_name_or_id.isdigit():
            item = await self.bot.shop_repo.get_item(int(item_name_or_id))
        if not item:
            items = await self.bot.shop_repo.get_items(ctx.guild.id)
            for it in items:
                if it["name"].lower() == item_name_or_id.lower():
                    item = it
                    break

        if not item or item["guild_id"] != ctx.guild.id:
            await ctx.send_error("Not Found", f"Item **{item_name_or_id}** not found in shop.")
            return

        ok, msg, pdata = await self.bot.shop_repo.buy_item(ctx.guild.id, ctx.author.id, item["item_id"])
        if not ok:
            await ctx.send_error("Purchase Failed", msg)
            return

        # Grant role if applicable
        role_msg = ""
        if item.get("role_id") and isinstance(ctx.author, discord.Member):
            role = ctx.guild.get_role(item["role_id"])
            if role:
                if ctx.guild.me.guild_permissions.manage_roles and ctx.guild.me.top_role.position > role.position:
                    try:
                        await ctx.author.add_roles(role, reason=f"Purchased shop item {item['name']}")
                        role_msg = f"\n{KrovexEmoji.TADA} You unlocked the {role.mention} role!"
                    except Exception as e:
                        logger.error("Could not grant role: %s", e)

        embed = EmbedBuilder.success(
            title="Purchase Confirmed!",
            description=f"{msg}{role_msg}\n\n*Check your inventory with `inventory`.*",
        )
        await ctx.reply(embed=embed)

    async def _execute_sell(self, ctx: UnifiedContext, item_name: str) -> None:
        if not ctx.guild or not self.bot.economy_repo or not self.bot.shop_repo:
            return

        inv = await self.bot.economy_repo.get_inventory(ctx.guild.id, ctx.author.id)
        target = None
        for it in inv:
            if it["name"].lower() == item_name.lower():
                target = it
                break

        if not target:
            await ctx.send_error("Not in Inventory", f"You do not own **{item_name}**.")
            return

        ok, msg, refund_coins = await self.bot.shop_repo.sell_item(ctx.guild.id, ctx.author.id, target["item_id"])
        if ok:
            embed = EmbedBuilder.success(title="Item Sold", description=msg)
            await ctx.reply(embed=embed)
        else:
            await ctx.send_error("Sale Failed", msg)

    async def _execute_stock(self, ctx: UnifiedContext, item_name_or_id: str, new_stock: int) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        item = None
        if item_name_or_id.isdigit():
            item = await self.bot.shop_repo.get_item(int(item_name_or_id))
        if not item:
            items = await self.bot.shop_repo.get_items(ctx.guild.id)
            for it in items:
                if it["name"].lower() == item_name_or_id.lower():
                    item = it
                    break

        if not item or item["guild_id"] != ctx.guild.id:
            await ctx.send_error("Not Found", f"Item **{item_name_or_id}** not found.")
            return

        await self.bot.shop_repo.edit_item(item["item_id"], stock=new_stock)
        stock_str = "Unlimited" if new_stock < 0 else f"{new_stock} units"
        await ctx.send_success("Stock Updated", f"Set stock for **{item['name']}** to `{stock_str}`.")

    async def _execute_category(self, ctx: UnifiedContext, action: str, name: str, description: str = "") -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        if action.lower() == "add":
            cid = await self.bot.shop_repo.create_category(ctx.guild.id, name, description)
            await ctx.send_success("Category Created", f"Created shop category `{name}` (ID: {cid}).")
        elif action.lower() in ("delete", "remove"):
            cats = await self.bot.shop_repo.get_categories(ctx.guild.id)
            target_id = None
            for c in cats:
                if c["name"].lower() == name.lower() or str(c["category_id"]) == name:
                    target_id = c["category_id"]
                    break
            if target_id:
                await self.bot.shop_repo.delete_category(ctx.guild.id, target_id)
                await ctx.send_success("Category Deleted", f"Removed shop category `{name}`.")
            else:
                await ctx.send_error("Not Found", f"Category `{name}` not found.")
        else:
            await self._execute_categories(ctx)

    async def _execute_categories(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return
        cats = await self.bot.shop_repo.get_categories(ctx.guild.id)
        if not cats:
            await ctx.reply("ℹ️ No custom shop categories created yet.")
            return

        lines = [f"• **{c['name']}** (ID: `{c['category_id']}`) — *{c.get('description', '')}*" for c in cats]
        embed = EmbedBuilder.base(
            title=f"📁 Shop Categories • {ctx.guild.name}",
            description="\n".join(lines),
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    async def _execute_history(self, ctx: UnifiedContext, member: Optional[discord.Member] = None) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return
        user_id = member.id if member else None
        orders = await self.bot.shop_repo.get_purchases(ctx.guild.id, user_id=user_id, limit=15)
        if not orders:
            await ctx.reply("🧾 No shop purchases recorded.")
            return

        lines = []
        for o in orders:
            status_emoji = "✅" if o["status"] == "completed" else "↩️"
            lines.append(f"{status_emoji} Order `#{o['purchase_id']}`: **{o['item_name']}** — 🪙 `{o['price_paid']:,}` Coins (<@{o['user_id']}>) at `{o['purchased_at']}`")

        embed = EmbedBuilder.base(
            title=f"🧾 Purchase History • {member.display_name if member else ctx.guild.name}",
            description="\n".join(lines),
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    async def _execute_refund(self, ctx: UnifiedContext, purchase_id: int) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return
        if not ctx.author.guild_permissions.administrator and not ctx.author.guild_permissions.manage_guild:
            await ctx.send_error("Permission Denied", "Administrator or Manage Server required.")
            return

        ok, msg = await self.bot.shop_repo.refund_purchase(ctx.guild.id, purchase_id)
        if ok:
            await ctx.send_success("Refund Processed", msg)
        else:
            await ctx.send_error("Refund Failed", msg)

    async def _execute_toggle(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        await ctx.send_success("Shop Toggled", "Shop active status toggled.")

    async def _execute_stats(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return
        stats = await self.bot.shop_repo.get_shop_stats(ctx.guild.id)
        embed = EmbedBuilder.base(
            title=f"🏪 Marketplace Analytics • {ctx.guild.name}",
            color=BRAND_COLOR,
        )
        embed.add_field(name="Catalog Items", value=f"`{stats['total_items']}` items", inline=True)
        embed.add_field(name="Completed Purchases", value=f"`{stats['total_purchases']:,}` orders", inline=True)
        embed.add_field(name="Total Shop Revenue", value=f"🪙 `{stats['total_revenue']:,}` Coins", inline=True)
        await ctx.reply(embed=embed)

    # =========================================================
    # SLASH COMMAND GROUP: /shop <subcommand>
    # =========================================================

    @app_commands.command(name="view", description="Browse items and roles available in the server shop.")
    @app_commands.describe(category="Filter items by category name")
    async def slash_view(self, interaction: discord.Interaction, category: Optional[str] = None) -> None:
        await self._execute_view(UnifiedContext.from_interaction(interaction), category)

    @app_commands.command(name="setup", description="Deploy the interactive shop catalog panel.")
    @app_commands.describe(channel="Channel where shop panel should be deployed")
    async def slash_setup(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_setup(UnifiedContext.from_interaction(interaction), channel)

    @app_commands.command(name="add", description="Add an item or role reward to the server shop.")
    @app_commands.describe(name="Item name", price="Price in coins", description="Item description", role="Optional role reward", stock="Stock (-1 for unlimited)")
    async def slash_add(self, interaction: discord.Interaction, name: str, price: int, description: str = "", role: Optional[discord.Role] = None, stock: int = -1) -> None:
        await self._execute_add(UnifiedContext.from_interaction(interaction), name, price, description, role, stock)

    @app_commands.command(name="edit", description="Update an existing shop item.")
    @app_commands.describe(item_name="Item name or ID", new_price="Updated price", new_stock="Updated stock", new_description="Updated description")
    async def slash_edit(self, interaction: discord.Interaction, item_name: str, new_price: Optional[int] = None, new_stock: Optional[int] = None, new_description: Optional[str] = None) -> None:
        await self._execute_edit(UnifiedContext.from_interaction(interaction), item_name, new_price, new_stock, new_description)

    @app_commands.command(name="remove", description="Remove an item from the server shop.")
    @app_commands.describe(item_name="Item name or ID to remove")
    async def slash_remove(self, interaction: discord.Interaction, item_name: str) -> None:
        await self._execute_remove(UnifiedContext.from_interaction(interaction), item_name)

    @app_commands.command(name="item", description="Inspect detailed item specifications and stock.")
    @app_commands.describe(item_name="Item name or ID")
    async def slash_item(self, interaction: discord.Interaction, item_name: str) -> None:
        await self._execute_item(UnifiedContext.from_interaction(interaction), item_name)

    @app_commands.command(name="list", description="List all items available in the shop.")
    async def slash_list(self, interaction: discord.Interaction) -> None:
        await self._execute_list(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="buy", description="Purchase an item from the shop.")
    @app_commands.describe(item_name="Name or ID of item to buy")
    async def slash_buy(self, interaction: discord.Interaction, item_name: str) -> None:
        await self._execute_buy(UnifiedContext.from_interaction(interaction), item_name)

    @app_commands.command(name="sell", description="Sell an owned item back to the market.")
    @app_commands.describe(item_name="Item name to sell")
    async def slash_sell(self, interaction: discord.Interaction, item_name: str) -> None:
        await self._execute_sell(UnifiedContext.from_interaction(interaction), item_name)

    @app_commands.command(name="stock", description="Update available stock for an item.")
    @app_commands.describe(item_name="Item name or ID", new_stock="Units in stock (-1 for unlimited)")
    async def slash_stock(self, interaction: discord.Interaction, item_name: str, new_stock: int) -> None:
        await self._execute_stock(UnifiedContext.from_interaction(interaction), item_name, new_stock)

    @app_commands.command(name="category", description="Manage shop categories (add/delete).")
    @app_commands.describe(action="add or delete", name="Category name", description="Category description")
    async def slash_category(self, interaction: discord.Interaction, action: str, name: str, description: str = "") -> None:
        await self._execute_category(UnifiedContext.from_interaction(interaction), action, name, description)

    @app_commands.command(name="categories", description="List all shop categories.")
    async def slash_categories(self, interaction: discord.Interaction) -> None:
        await self._execute_categories(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="history", description="View recent shop purchases and orders.")
    @app_commands.describe(member="Optional member to filter")
    async def slash_history(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        await self._execute_history(UnifiedContext.from_interaction(interaction), member)

    @app_commands.command(name="refund", description="Refund a purchase order and restore coins.")
    @app_commands.describe(purchase_id="Order purchase ID")
    async def slash_refund(self, interaction: discord.Interaction, purchase_id: int) -> None:
        await self._execute_refund(UnifiedContext.from_interaction(interaction), purchase_id)

    @app_commands.command(name="toggle", description="Toggle shop system availability.")
    async def slash_toggle(self, interaction: discord.Interaction) -> None:
        await self._execute_toggle(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="stats", description="View shop sales statistics and revenue.")
    async def slash_stats(self, interaction: discord.Interaction) -> None:
        await self._execute_stats(UnifiedContext.from_interaction(interaction))

    # =========================================================
    # PREFIX COMMANDS (16 commands)
    # =========================================================

    @commands.command(name="shop", help="Browse items and roles available in the server shop.")
    async def prefix_shop(self, ctx: commands.Context, *, category: Optional[str] = None) -> None:
        await self._execute_view(UnifiedContext.from_prefix(ctx), category)

    @commands.command(name="shopsetup", help="Deploy the interactive shop panel.")
    @commands.has_permissions(administrator=True)
    async def prefix_shopsetup(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_setup(UnifiedContext.from_prefix(ctx), channel)

    @commands.command(name="shopadd", help="Add an item to the server shop.")
    @commands.has_permissions(administrator=True)
    async def prefix_shopadd(self, ctx: commands.Context, name: str, price: int, *, description: str = "") -> None:
        await self._execute_add(UnifiedContext.from_prefix(ctx), name, price, description=description)

    @commands.command(name="shopedit", help="Update item price or stock.")
    @commands.has_permissions(administrator=True)
    async def prefix_shopedit(self, ctx: commands.Context, item_name: str, new_price: Optional[int] = None, new_stock: Optional[int] = None) -> None:
        await self._execute_edit(UnifiedContext.from_prefix(ctx), item_name, new_price=new_price, new_stock=new_stock)

    @commands.command(name="shopremove", help="Remove an item from the shop.")
    @commands.has_permissions(administrator=True)
    async def prefix_shopremove(self, ctx: commands.Context, *, item_name: str) -> None:
        await self._execute_remove(UnifiedContext.from_prefix(ctx), item_name)

    @commands.command(name="shopitem", help="Inspect item details.")
    async def prefix_shopitem(self, ctx: commands.Context, *, item_name: str) -> None:
        await self._execute_item(UnifiedContext.from_prefix(ctx), item_name)

    @commands.command(name="shopitems", help="List all items in the shop.")
    async def prefix_shopitems(self, ctx: commands.Context) -> None:
        await self._execute_list(UnifiedContext.from_prefix(ctx))

    @commands.command(name="shopbuy", help="Purchase an item using wallet currency.")
    async def prefix_shopbuy(self, ctx: commands.Context, *, item_name: str) -> None:
        await self._execute_buy(UnifiedContext.from_prefix(ctx), item_name)

    @commands.command(name="shopsell", help="Sell an item back to the market.")
    async def prefix_shopsell(self, ctx: commands.Context, *, item_name: str) -> None:
        await self._execute_sell(UnifiedContext.from_prefix(ctx), item_name)

    @commands.command(name="shopstock", help="Set stock for an item.")
    @commands.has_permissions(administrator=True)
    async def prefix_shopstock(self, ctx: commands.Context, item_name: str, new_stock: int) -> None:
        await self._execute_stock(UnifiedContext.from_prefix(ctx), item_name, new_stock)

    @commands.command(name="shopcategory", help="Manage shop categories (add/delete).")
    @commands.has_permissions(administrator=True)
    async def prefix_shopcategory(self, ctx: commands.Context, action: str, name: str, *, description: str = "") -> None:
        await self._execute_category(UnifiedContext.from_prefix(ctx), action, name, description)

    @commands.command(name="shopcategories", help="List all shop categories.")
    async def prefix_shopcategories(self, ctx: commands.Context) -> None:
        await self._execute_categories(UnifiedContext.from_prefix(ctx))

    @commands.command(name="shophistory", help="View recent purchases.")
    async def prefix_shophistory(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_history(UnifiedContext.from_prefix(ctx), member)

    @commands.command(name="shoprefund", help="Refund a purchase order.")
    @commands.has_permissions(manage_guild=True)
    async def prefix_shoprefund(self, ctx: commands.Context, purchase_id: int) -> None:
        await self._execute_refund(UnifiedContext.from_prefix(ctx), purchase_id)

    @commands.command(name="shoptoggle", help="Toggle shop availability.")
    @commands.has_permissions(administrator=True)
    async def prefix_shoptoggle(self, ctx: commands.Context) -> None:
        await self._execute_toggle(UnifiedContext.from_prefix(ctx))

    @commands.command(name="shopstats", help="View shop performance statistics.")
    async def prefix_shopstats(self, ctx: commands.Context) -> None:
        await self._execute_stats(UnifiedContext.from_prefix(ctx))


async def setup(bot: DeathBot) -> None:
    """Setup hook to register ShopCog."""
    await bot.add_cog(ShopCog(bot))

