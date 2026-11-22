"""Comprehensive Server-Specific Virtual Economy System Cog."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.economy.views import TransferConfirmView
from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.economy")
BRAND_COLOR = 0x9D4EDD


class EconomyCog(commands.GroupCog, group_name="eco"):
    """Server-specific virtual economy, wallets, bank vaults, career jobs, and transactions."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot
        super().__init__()

    # =========================================================
    # CORE SHARED BUSINESS LOGIC
    # =========================================================

    async def _execute_balance(self, ctx: UnifiedContext, member: Optional[discord.Member] = None) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        target = member or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if not target:
            await ctx.send_error("Error", "Could not resolve user instance.")
            return

        settings = await self.bot.economy_repo.get_settings(ctx.guild.id)
        bal = await self.bot.economy_repo.get_balance(ctx.guild.id, target.id)
        sym = settings.get("currency_symbol") or KrovexEmoji.CRYSTALS.discord_format
        cname = settings.get("currency_name") or "Coins"

        wallet = bal.get("wallet", 0)
        bank = bal.get("bank", 0)
        net_worth = wallet + bank
        streak = bal.get("daily_streak", 0)

        embed = EmbedBuilder.base(
            title=f"{sym} Financial Profile • {target.display_name}",
            color=BRAND_COLOR,
            thumbnail=target.display_avatar.url,
        )
        embed.add_field(name="Wallet Cash", value=f"{sym} **{wallet:,}** {cname}", inline=True)
        embed.add_field(name="Bank Vault", value=f"🏦 **{bank:,}** {cname}", inline=True)
        embed.add_field(name="Total Net Worth", value=f"💎 **{net_worth:,}** {cname}", inline=True)
        embed.add_field(name="Daily Streak", value=f"🔥 **{streak}** days", inline=True)
        embed.set_footer(text=f"{ctx.guild.name} • Virtual Economy", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        await ctx.reply(embed=embed)

    async def _execute_bank(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        settings = await self.bot.economy_repo.get_settings(ctx.guild.id)
        bal = await self.bot.economy_repo.get_balance(ctx.guild.id, ctx.author.id)
        sym = settings.get("currency_symbol") or KrovexEmoji.CRYSTALS.discord_format
        cap = settings.get("bank_cap") or 50000

        bank = bal.get("bank", 0)
        pct = min(100.0, (bank / cap) * 100.0) if cap > 0 else 0.0

        embed = EmbedBuilder.base(
            title="🏦 Server Vault & Bank Overview",
            description=(
                f"Your Secure Savings: {sym} **{bank:,}** / **{cap:,}**\n"
                f"Vault Capacity Used: **{pct:.1f}%**\n\n"
                "• Deposit cash from your wallet to protect it from thieves (`deposit <amount>`).\n"
                "• Withdraw cash whenever you need to spend it at the shop (`withdraw <amount>`)."
            ),
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    async def _execute_deposit(self, ctx: UnifiedContext, amount_str: str) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        bal = await self.bot.economy_repo.get_balance(ctx.guild.id, ctx.author.id)
        wallet = bal.get("wallet", 0)

        if amount_str.lower() in ("all", "max"):
            amt = wallet
        else:
            try:
                amt = int(amount_str)
            except ValueError:
                await ctx.send_error("Invalid Amount", "Provide a valid number or `all`.")
                return

        ok, msg, new_w, new_b = await self.bot.economy_repo.deposit(ctx.guild.id, ctx.author.id, amt)
        if ok:
            embed = EmbedBuilder.success(
                title="Bank Deposit Successful",
                description=f"{msg}\n\n**Wallet:** `{new_w:,}` | **Bank:** `{new_b:,}`",
            )
            await ctx.reply(embed=embed)
        else:
            await ctx.send_error("Deposit Failed", msg)

    async def _execute_withdraw(self, ctx: UnifiedContext, amount_str: str) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        bal = await self.bot.economy_repo.get_balance(ctx.guild.id, ctx.author.id)
        bank = bal.get("bank", 0)

        if amount_str.lower() in ("all", "max"):
            amt = bank
        else:
            try:
                amt = int(amount_str)
            except ValueError:
                await ctx.send_error("Invalid Amount", "Provide a valid number or `all`.")
                return

        ok, msg, new_w, new_b = await self.bot.economy_repo.withdraw(ctx.guild.id, ctx.author.id, amt)
        if ok:
            embed = EmbedBuilder.success(
                title="Bank Withdrawal Successful",
                description=f"{msg}\n\n**Wallet:** `{new_w:,}` | **Bank:** `{new_b:,}`",
            )
            await ctx.reply(embed=embed)
        else:
            await ctx.send_error("Withdrawal Failed", msg)

    async def _execute_daily(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        ok, msg, reward, streak = await self.bot.economy_repo.claim_daily(ctx.guild.id, ctx.author.id)
        if ok:
            embed = EmbedBuilder.success(
                title=f"{KrovexEmoji.STARBUCKS} Daily Reward Claimed!",
                description=f"{msg}\n\n🔥 **Current Streak:** `{streak}` day(s)! {KrovexEmoji.KITTY_MUFFIN}",
            )
            await ctx.reply(embed=embed)
        else:
            await ctx.send_error("Daily Cooldown Active", msg)

    async def _execute_weekly(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        ok, msg, reward = await self.bot.economy_repo.claim_weekly(ctx.guild.id, ctx.author.id)
        if ok:
            embed = EmbedBuilder.success(title=f"{KrovexEmoji.SCORE_100} Weekly Allowance Claimed!", description=msg)
            await ctx.reply(embed=embed)
        else:
            await ctx.send_error("Weekly Cooldown Active", msg)

    async def _execute_work(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        ok, msg, payout, job = await self.bot.economy_repo.work(ctx.guild.id, ctx.author.id)
        if ok:
            embed = EmbedBuilder.success(title=f"Shift Finished • {job}", description=msg)
            await ctx.reply(embed=embed)
        else:
            await ctx.send_error("Work Cooldown Active", msg)

    async def _execute_crime(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        ok, msg, amount, status = await self.bot.economy_repo.crime(ctx.guild.id, ctx.author.id)
        if status == "success":
            embed = EmbedBuilder.success(title="🕶️ Heist Executed!", description=msg)
            await ctx.reply(embed=embed)
        elif status == "failed":
            embed = EmbedBuilder.danger(title="🚨 Busted by Authorities!", description=msg)
            await ctx.reply(embed=embed)
        else:
            await ctx.send_error("Cooldown Active", msg)

    async def _execute_rob(self, ctx: UnifiedContext, target: discord.Member) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        if target.bot:
            await ctx.send_error("Invalid Target", "You cannot rob bots.")
            return

        ok, msg, amount = await self.bot.economy_repo.rob(ctx.guild.id, ctx.author.id, target.id)
        if ok:
            embed = EmbedBuilder.success(title="💰 Successful Robbery!", description=msg)
            await ctx.reply(embed=embed)
        else:
            embed = EmbedBuilder.warning(title="Robbery Failed", description=msg)
            await ctx.reply(embed=embed)

    async def _execute_pay(self, ctx: UnifiedContext, member: discord.Member, amount: int) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        if member.bot:
            await ctx.send_error("Invalid Member", "You cannot transfer funds to a bot.")
            return
        if amount <= 0:
            await ctx.send_error("Invalid Amount", "Transfer amount must be positive.")
            return

        # Check balance
        bal = await self.bot.economy_repo.get_balance(ctx.guild.id, ctx.author.id)
        if bal["wallet"] < amount:
            await ctx.send_error("Insufficient Funds", f"You only have `{bal['wallet']:,}` coins in your wallet.")
            return

        # For large transfers (>1000), require confirmation button
        if amount >= 1000:
            view = TransferConfirmView(ctx.author.id, member.id, amount)
            embed = EmbedBuilder.warning(
                title="Confirm Currency Transfer",
                description=f"Are you sure you want to transfer **{amount:,}** coins to {member.mention}?",
            )
            msg = await ctx.reply(embed=embed, view=view)
            await view.wait()
            if not view.confirmed:
                return

        ok, text = await self.bot.economy_repo.transfer(ctx.guild.id, ctx.author.id, member.id, amount)
        if ok:
            embed = EmbedBuilder.success(
                title="Transfer Complete",
                description=f"Sent **{amount:,}** coins to {member.mention}!\n*Transaction recorded in ledger.*",
            )
            await ctx.reply(embed=embed)
        else:
            await ctx.send_error("Transfer Failed", text)

    async def _execute_top(self, ctx: UnifiedContext, limit: int = 10) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        limit = max(5, min(25, limit))
        rows = await self.bot.economy_repo.get_leaderboard(ctx.guild.id, limit)
        settings = await self.bot.economy_repo.get_settings(ctx.guild.id)
        sym = settings.get("currency_symbol") or KrovexEmoji.CRYSTALS.discord_format

        lines = []
        for i, r in enumerate(rows, start=1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`#{i}`"
            lines.append(f"{medal} <@{r['user_id']}> — **{r['net_worth']:,}** {sym} *(Wallet: `{r['wallet']:,}` | Bank: `{r['bank']:,}`)*")

        embed = EmbedBuilder.base(
            title=f"{sym} Server Wealth Leaderboard",
            description="\n".join(lines) if lines else "No wealth recorded yet.",
            color=BRAND_COLOR,
        )
        embed.set_footer(text=f"{ctx.guild.name} • Top Net Worth", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        await ctx.reply(embed=embed)

    async def _execute_inventory(self, ctx: UnifiedContext, member: Optional[discord.Member] = None) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        target = member or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if not target:
            return

        inv = await self.bot.economy_repo.get_inventory(ctx.guild.id, target.id)
        if not inv:
            await ctx.reply(f"🎒 **{target.display_name}** has an empty inventory.")
            return

        lines = []
        for item in inv:
            role_tag = f" `[Role: <@&{item['role_id']}>]`" if item.get("role_id") else ""
            lines.append(f"• **{item['name']}** x`{item['quantity']}` — {item.get('description', '')}{role_tag}")

        embed = EmbedBuilder.base(
            title=f"🎒 Member Inventory • {target.display_name}",
            description="\n".join(lines),
            color=BRAND_COLOR,
            thumbnail=target.display_avatar.url,
        )
        await ctx.reply(embed=embed)

    async def _execute_useitem(self, ctx: UnifiedContext, item_name: str) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        inv = await self.bot.economy_repo.get_inventory(ctx.guild.id, ctx.author.id)
        target_item = None
        for it in inv:
            if it["name"].lower() == item_name.lower():
                target_item = it
                break

        if not target_item:
            await ctx.send_error("Item Not Found", f"You don't have **{item_name}** in your inventory.")
            return

        ok = await self.bot.economy_repo.remove_from_inventory(ctx.guild.id, ctx.author.id, target_item["item_id"], 1)
        if ok:
            embed = EmbedBuilder.success(
                title="Item Consumed",
                description=f"You used **{target_item['name']}**! Effect activated.",
            )
            await ctx.reply(embed=embed)
        else:
            await ctx.send_error("Error", "Could not consume item.")

    async def _execute_sellitem(self, ctx: UnifiedContext, item_name: str) -> None:
        if not ctx.guild or not self.bot.shop_repo:
            return
        inv = await self.bot.economy_repo.get_inventory(ctx.guild.id, ctx.author.id)
        target_item = None
        for it in inv:
            if it["name"].lower() == item_name.lower():
                target_item = it
                break

        if not target_item:
            await ctx.send_error("Item Not Found", f"You don't own **{item_name}**.")
            return

        ok, msg, coins = await self.bot.shop_repo.sell_item(ctx.guild.id, ctx.author.id, target_item["item_id"])
        if ok:
            embed = EmbedBuilder.success(title="Item Sold", description=msg)
            await ctx.reply(embed=embed)
        else:
            await ctx.send_error("Sale Failed", msg)

    async def _execute_stats(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        stats = await self.bot.economy_repo.get_economy_stats(ctx.guild.id)
        settings = await self.bot.economy_repo.get_settings(ctx.guild.id)
        sym = settings.get("currency_symbol") or KrovexEmoji.CRYSTALS.discord_format

        embed = EmbedBuilder.base(
            title=f"📊 Server Financial Health • {ctx.guild.name}",
            color=BRAND_COLOR,
        )
        embed.add_field(name="Total Accounts", value=f"`{stats['total_accounts']:,}`", inline=True)
        embed.add_field(name="Wallet Circulation", value=f"{sym} `{stats['total_wallet']:,}`", inline=True)
        embed.add_field(name="Bank Reserves", value=f"🏦 `{stats['total_bank']:,}`", inline=True)
        embed.add_field(name="Highest Net Worth", value=f"💎 `{stats['highest_net_worth']:,}`", inline=True)
        embed.add_field(name="Recorded Transactions", value=f"🧾 `{stats['total_transactions']:,}`", inline=True)
        await ctx.reply(embed=embed)

    async def _execute_setup(self, ctx: UnifiedContext, symbol: str = "🪙", name: str = "Coins", daily_min: int = 100, daily_max: int = 300) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        await self.bot.economy_repo.update_settings(
            ctx.guild.id,
            currency_symbol=symbol,
            currency_name=name,
            daily_min=daily_min,
            daily_max=daily_max,
            enabled=True,
        )
        embed = EmbedBuilder.success(
            title="🪙 Economy System Configured",
            description=(
                f"**Currency Symbol:** `{symbol}`\n"
                f"**Currency Name:** `{name}`\n"
                f"**Daily Range:** `{daily_min} – {daily_max}` {symbol}"
            ),
        )
        await ctx.reply(embed=embed)

    async def _execute_toggle(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        s = await self.bot.economy_repo.get_settings(ctx.guild.id)
        new_state = not s.get("enabled", True)
        await self.bot.economy_repo.update_settings(ctx.guild.id, enabled=new_state)
        await ctx.send_success("Economy Toggled", f"Server economy is now **{'Enabled' if new_state else 'Disabled'}**.")

    async def _execute_log(self, ctx: UnifiedContext, member: Optional[discord.Member] = None) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        user_id = member.id if member else None
        logs = await self.bot.economy_repo.get_transaction_logs(ctx.guild.id, user_id=user_id, limit=10)

        lines = []
        for l in logs:
            target_str = f" ➔ <@{l['target_id']}>" if l.get("target_id") else ""
            sign = "+" if l["amount"] >= 0 else ""
            lines.append(f"• `{l['timestamp']}` | **{l['action']}** | `{sign}{l['amount']:,}` coins | <@{l['user_id']}>{target_str}")

        embed = EmbedBuilder.base(
            title=f"🧾 Transaction Ledger • {member.display_name if member else ctx.guild.name}",
            description="\n".join(lines) if lines else "No transactions recorded in ledger.",
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    async def _execute_cooldown(self, ctx: UnifiedContext, cooldown_type: str, seconds: int) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        await ctx.send_success("Cooldown Updated", f"Economy cooldown for `{cooldown_type}` set to `{seconds}`s.")

    async def _execute_add(self, ctx: UnifiedContext, member: discord.Member, amount: int, destination: str = "wallet") -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if amount <= 0:
            await ctx.send_error("Invalid Amount", "Amount must be positive.")
            return

        new_val = await self.bot.economy_repo.add_money(ctx.guild.id, member.id, amount, destination)
        await ctx.send_success("Funds Added", f"Added **+{amount:,}** coins to {member.mention}'s {destination}. (New Balance: `{new_val:,}`)")

    async def _execute_set(self, ctx: UnifiedContext, member: discord.Member, amount: int, destination: str = "wallet") -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if amount < 0:
            await ctx.send_error("Invalid Amount", "Balance cannot be negative.")
            return

        if destination == "bank":
            await self.bot.economy_repo.set_money(ctx.guild.id, member.id, wallet=0, bank=amount)
        else:
            await self.bot.economy_repo.set_money(ctx.guild.id, member.id, wallet=amount)
        await ctx.send_success("Balance Set", f"Set {member.mention}'s {destination} balance to **{amount:,}** coins.")

    async def _execute_minus(self, ctx: UnifiedContext, member: discord.Member, amount: int, destination: str = "wallet") -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if amount <= 0:
            await ctx.send_error("Invalid Amount", "Amount must be positive.")
            return

        new_val = await self.bot.economy_repo.remove_money(ctx.guild.id, member.id, amount, destination)
        await ctx.send_success("Funds Deducted", f"Deducted **-{amount:,}** coins from {member.mention}'s {destination}. (Remaining: `{new_val:,}`)")

    async def _execute_reset(self, ctx: UnifiedContext, member: Optional[discord.Member] = None) -> None:
        if not ctx.guild or not self.bot.economy_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        if member:
            await self.bot.economy_repo.reset_economy(ctx.guild.id, member.id)
            await ctx.send_success("Account Reset", f"Wiped virtual balance and inventory for {member.mention}.")
        else:
            c = await self.bot.economy_repo.reset_economy(ctx.guild.id)
            await ctx.send_success("Economy Wiped", f"Reset economy balances for `{c}` accounts in this server.")

    # =========================================================
    # SLASH COMMAND GROUP: /eco <subcommand>
    # =========================================================

    @app_commands.command(name="balance", description="Check member wallet and bank balance.")
    @app_commands.describe(member="Member to view (defaults to yourself)")
    async def slash_balance(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        await self._execute_balance(UnifiedContext.from_interaction(interaction), member)

    @app_commands.command(name="bank", description="View bank vault capacity and savings.")
    async def slash_bank(self, interaction: discord.Interaction) -> None:
        await self._execute_bank(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="deposit", description="Deposit coins from wallet into bank vault.")
    @app_commands.describe(amount="Amount to deposit, or 'all'")
    async def slash_deposit(self, interaction: discord.Interaction, amount: str) -> None:
        await self._execute_deposit(UnifiedContext.from_interaction(interaction), amount)

    @app_commands.command(name="withdraw", description="Withdraw coins from bank vault into wallet.")
    @app_commands.describe(amount="Amount to withdraw, or 'all'")
    async def slash_withdraw(self, interaction: discord.Interaction, amount: str) -> None:
        await self._execute_withdraw(UnifiedContext.from_interaction(interaction), amount)

    @app_commands.command(name="daily", description="Claim daily currency allowance and increase your streak.")
    async def slash_daily(self, interaction: discord.Interaction) -> None:
        await self._execute_daily(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="weekly", description="Claim your weekly currency allowance.")
    async def slash_weekly(self, interaction: discord.Interaction) -> None:
        await self._execute_weekly(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="work", description="Work a job to earn currency.")
    async def slash_work(self, interaction: discord.Interaction) -> None:
        await self._execute_work(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="crime", description="Commit a high-risk crime for big payouts or police fines.")
    async def slash_crime(self, interaction: discord.Interaction) -> None:
        await self._execute_crime(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="rob", description="Attempt to rob wallet cash from another member.")
    @app_commands.describe(target="Member to rob")
    async def slash_rob(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self._execute_rob(UnifiedContext.from_interaction(interaction), target)

    @app_commands.command(name="pay", description="Transfer coins to another member.")
    @app_commands.describe(member="Recipient member", amount="Amount to send")
    async def slash_pay(self, interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        await self._execute_pay(UnifiedContext.from_interaction(interaction), member, amount)

    @app_commands.command(name="top", description="View server net worth leaderboard.")
    @app_commands.describe(limit="Number of members to display (default 10)")
    async def slash_top(self, interaction: discord.Interaction, limit: int = 10) -> None:
        await self._execute_top(UnifiedContext.from_interaction(interaction), limit)

    @app_commands.command(name="inventory", description="View member purchased items inventory.")
    @app_commands.describe(member="Member to view (defaults to yourself)")
    async def slash_inventory(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        await self._execute_inventory(UnifiedContext.from_interaction(interaction), member)

    @app_commands.command(name="use", description="Use/consume an inventory item.")
    @app_commands.describe(item_name="Name of item to use")
    async def slash_use(self, interaction: discord.Interaction, item_name: str) -> None:
        await self._execute_useitem(UnifiedContext.from_interaction(interaction), item_name)

    @app_commands.command(name="sell", description="Sell an item back to the market for a refund.")
    @app_commands.describe(item_name="Name of item to sell")
    async def slash_sell(self, interaction: discord.Interaction, item_name: str) -> None:
        await self._execute_sellitem(UnifiedContext.from_interaction(interaction), item_name)

    @app_commands.command(name="stats", description="View server economic statistics and circulation.")
    async def slash_stats(self, interaction: discord.Interaction) -> None:
        await self._execute_stats(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="setup", description="Configure server currency symbol and rewards.")
    @app_commands.describe(symbol="Currency symbol (e.g. 🪙)", name="Currency name", daily_min="Min daily", daily_max="Max daily")
    async def slash_setup(self, interaction: discord.Interaction, symbol: str = "🪙", name: str = "Coins", daily_min: int = 100, daily_max: int = 300) -> None:
        await self._execute_setup(UnifiedContext.from_interaction(interaction), symbol, name, daily_min, daily_max)

    @app_commands.command(name="toggle", description="Enable or disable economy features in this server.")
    async def slash_toggle(self, interaction: discord.Interaction) -> None:
        await self._execute_toggle(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="log", description="Inspect transaction audit logs.")
    @app_commands.describe(member="Filter by member")
    async def slash_log(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        await self._execute_log(UnifiedContext.from_interaction(interaction), member)

    @app_commands.command(name="add", description="Admin command to add currency to a user.")
    @app_commands.describe(member="Target member", amount="Amount to add", destination="wallet or bank")
    async def slash_add(self, interaction: discord.Interaction, member: discord.Member, amount: int, destination: str = "wallet") -> None:
        await self._execute_add(UnifiedContext.from_interaction(interaction), member, amount, destination)

    @app_commands.command(name="set", description="Admin command to set user balance.")
    @app_commands.describe(member="Target member", amount="New balance", destination="wallet or bank")
    async def slash_set(self, interaction: discord.Interaction, member: discord.Member, amount: int, destination: str = "wallet") -> None:
        await self._execute_set(UnifiedContext.from_interaction(interaction), member, amount, destination)

    @app_commands.command(name="minus", description="Admin command to deduct currency from a user.")
    @app_commands.describe(member="Target member", amount="Amount to deduct", destination="wallet or bank")
    async def slash_minus(self, interaction: discord.Interaction, member: discord.Member, amount: int, destination: str = "wallet") -> None:
        await self._execute_minus(UnifiedContext.from_interaction(interaction), member, amount, destination)

    @app_commands.command(name="reset", description="Admin command to wipe economy progress.")
    @app_commands.describe(member="Optional member to reset (leave blank to reset whole server)")
    async def slash_reset(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        await self._execute_reset(UnifiedContext.from_interaction(interaction), member)

    # =========================================================
    # PREFIX COMMANDS (22 commands)
    # =========================================================

    @commands.command(name="balance", aliases=["bal", "wallet"], help="Check member wallet and bank balance.")
    async def prefix_balance(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_balance(UnifiedContext.from_prefix(ctx), member)

    @commands.command(name="bank", help="View bank vault capacity and savings.")
    async def prefix_bank(self, ctx: commands.Context) -> None:
        await self._execute_bank(UnifiedContext.from_prefix(ctx))

    @commands.command(name="deposit", aliases=["dep"], help="Deposit coins into your bank vault.")
    async def prefix_deposit(self, ctx: commands.Context, amount: str) -> None:
        await self._execute_deposit(UnifiedContext.from_prefix(ctx), amount)

    @commands.command(name="withdraw", aliases=["with"], help="Withdraw coins from your bank vault.")
    async def prefix_withdraw(self, ctx: commands.Context, amount: str) -> None:
        await self._execute_withdraw(UnifiedContext.from_prefix(ctx), amount)

    @commands.command(name="weekly", aliases=["weeklyreward"], help="Claim your weekly currency allowance.")
    async def prefix_weekly(self, ctx: commands.Context) -> None:
        await self._execute_weekly(UnifiedContext.from_prefix(ctx))

    @commands.command(name="work", help="Work a job for virtual currency.")
    async def prefix_work(self, ctx: commands.Context) -> None:
        await self._execute_work(UnifiedContext.from_prefix(ctx))

    @commands.command(name="crime", help="Attempt a high-risk crime.")
    async def prefix_crime(self, ctx: commands.Context) -> None:
        await self._execute_crime(UnifiedContext.from_prefix(ctx))

    @commands.command(name="rob", help="Attempt to steal wallet cash from another member.")
    async def prefix_rob(self, ctx: commands.Context, target: discord.Member) -> None:
        await self._execute_rob(UnifiedContext.from_prefix(ctx), target)

    @commands.command(name="pay", aliases=["transfer"], help="Transfer coins to another member.")
    async def prefix_pay(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        await self._execute_pay(UnifiedContext.from_prefix(ctx), member, amount)

    @commands.command(name="economytop", aliases=["richest"], help="View server richest members leaderboard.")
    async def prefix_economytop(self, ctx: commands.Context, limit: int = 10) -> None:
        await self._execute_top(UnifiedContext.from_prefix(ctx), limit)

    @commands.command(name="inventory", aliases=["inv"], help="View your or another member's inventory.")
    async def prefix_inventory(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_inventory(UnifiedContext.from_prefix(ctx), member)

    @commands.command(name="useitem", help="Use an item from your inventory.")
    async def prefix_useitem(self, ctx: commands.Context, *, item_name: str) -> None:
        await self._execute_useitem(UnifiedContext.from_prefix(ctx), item_name)

    @commands.command(name="sellitem", help="Sell an item back to the market.")
    async def prefix_sellitem(self, ctx: commands.Context, *, item_name: str) -> None:
        await self._execute_sellitem(UnifiedContext.from_prefix(ctx), item_name)

    @commands.command(name="economystats", help="View server financial and currency statistics.")
    async def prefix_economystats(self, ctx: commands.Context) -> None:
        await self._execute_stats(UnifiedContext.from_prefix(ctx))

    @commands.command(name="economysetup", help="Configure server currency settings.")
    @commands.has_permissions(administrator=True)
    async def prefix_economysetup(self, ctx: commands.Context, symbol: str = "🪙", name: str = "Coins", daily_min: int = 100, daily_max: int = 300) -> None:
        await self._execute_setup(UnifiedContext.from_prefix(ctx), symbol, name, daily_min, daily_max)

    @commands.command(name="economytoggle", help="Toggle economy features on/off.")
    @commands.has_permissions(administrator=True)
    async def prefix_economytoggle(self, ctx: commands.Context) -> None:
        await self._execute_toggle(UnifiedContext.from_prefix(ctx))

    @commands.command(name="economylog", help="Inspect transaction audit logs.")
    async def prefix_economylog(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_log(UnifiedContext.from_prefix(ctx), member)

    @commands.command(name="economycooldown", help="Configure cooldowns for economy actions.")
    @commands.has_permissions(administrator=True)
    async def prefix_economycooldown(self, ctx: commands.Context, action: str, seconds: int) -> None:
        await self._execute_cooldown(UnifiedContext.from_prefix(ctx), action, seconds)

    @commands.command(name="ecoadd", help="Admin command to add currency to a user.")
    @commands.has_permissions(administrator=True)
    async def prefix_ecoadd(self, ctx: commands.Context, member: discord.Member, amount: int, destination: str = "wallet") -> None:
        await self._execute_add(UnifiedContext.from_prefix(ctx), member, amount, destination)

    @commands.command(name="ecoset", help="Admin command to set user balance.")
    @commands.has_permissions(administrator=True)
    async def prefix_ecoset(self, ctx: commands.Context, member: discord.Member, amount: int, destination: str = "wallet") -> None:
        await self._execute_set(UnifiedContext.from_prefix(ctx), member, amount, destination)

    @commands.command(name="ecominus", help="Admin command to deduct currency from a user.")
    @commands.has_permissions(administrator=True)
    async def prefix_ecominus(self, ctx: commands.Context, member: discord.Member, amount: int, destination: str = "wallet") -> None:
        await self._execute_minus(UnifiedContext.from_prefix(ctx), member, amount, destination)

    @commands.command(name="ecoreset", help="Admin command to reset economy progress.")
    @commands.has_permissions(administrator=True)
    async def prefix_ecoreset(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_reset(UnifiedContext.from_prefix(ctx), member)


async def setup(bot: DeathBot) -> None:
    """Setup hook to register EconomyCog."""
    await bot.add_cog(EconomyCog(bot))

