"""Unified Discord interactive dashboard for Batch 03 subsystems."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import discord

from bot.utils.embeds import EmbedBuilder
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.dashboard.panels")
BRAND_COLOR = 0x9D4EDD


class DashboardSelect(discord.ui.Select):
    """Dropdown menu to switch between dashboard sections."""

    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Tickets Configuration", value="tickets", emoji="🎫", description="Staff roles, categories, and limits"),
            discord.SelectOption(label="Leveling & XP Engine", value="leveling", emoji="⭐", description="XP multipliers, rewards, and announcements"),
            discord.SelectOption(label="Server Economy Vault", value="economy", emoji="🪙", description="Currency symbol, daily rewards, and bank cap"),
            discord.SelectOption(label="Marketplace & Shop", value="shop", emoji="🏪", description="Item stock, prices, and role rewards"),
            discord.SelectOption(label="Minigames & Betting", value="minigames", emoji="🎮", description="Bet limits, cooldowns, and challenges"),
        ]
        super().__init__(
            placeholder="Choose a subsystem to configure...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="unified_dashboard:section_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        view: UnifiedDashboardView = self.view  # type: ignore
        section = self.values[0]
        view.current_section = section

        embed = await view.build_section_embed(interaction.guild, section)
        await interaction.response.edit_message(embed=embed, view=view)


class UnifiedDashboardView(discord.ui.View):
    """Interactive control view for server administrators."""

    def __init__(self, bot: "DeathBot", author_id: int, initial_section: str = "tickets") -> None:
        super().__init__(timeout=300.0)
        self.bot = bot
        self.author_id = author_id
        self.current_section = initial_section
        self.add_item(DashboardSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This dashboard session is restricted to the administrator who opened it.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.administrator and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Administrator or Manage Server permissions required.", ephemeral=True)
            return False
        return True

    async def build_section_embed(self, guild: discord.Guild, section: str) -> discord.Embed:
        """Dynamically render dark black/neon-purple dashboard status cards."""
        if section == "tickets":
            t_repo = self.bot.ticket_repo
            settings = await t_repo.get_settings(guild.id) if t_repo else {}
            stats = await t_repo.get_ticket_stats(guild.id) if t_repo else {}
            cats = await t_repo.get_categories(guild.id) if t_repo else []

            staff_role = guild.get_role(settings.get("staff_role_id")) if settings.get("staff_role_id") else None
            tr_ch = guild.get_channel(settings.get("transcript_channel_id")) if settings.get("transcript_channel_id") else None

            embed = EmbedBuilder.base(
                title=f"🎫 Support Ticket Dashboard • {guild.name}",
                description="Manage support ticket routing, staff roles, and member creation limits.",
                color=BRAND_COLOR,
                thumbnail=guild.icon.url if guild.icon else None,
            )
            embed.add_field(name="Support Staff Role", value=staff_role.mention if staff_role else "`None (Admins only)`", inline=True)
            embed.add_field(name="Transcripts Channel", value=tr_ch.mention if tr_ch else "`Disabled`", inline=True)
            embed.add_field(name="Max Open Tickets", value=f"`{settings.get('max_tickets_per_user', 1)}` per user", inline=True)
            embed.add_field(name="Active Categories", value=f"`{len(cats)}` configured", inline=True)
            embed.add_field(name="Open Tickets", value=f"🟢 `{stats.get('open', 0)}`", inline=True)
            embed.add_field(name="Resolved Tickets", value=f"📁 `{stats.get('closed', 0)}`", inline=True)
            embed.set_footer(text="Death Bot Security & Ticket Administration")
            return embed

        elif section == "leveling":
            l_repo = self.bot.level_repo
            s = await l_repo.get_settings(guild.id) if l_repo else {}
            stats = await l_repo.get_guild_stats(guild.id) if l_repo else {}
            rewards = await l_repo.get_rewards(guild.id) if l_repo else []

            ch = guild.get_channel(s.get("channel_id")) if s.get("channel_id") else None

            embed = EmbedBuilder.base(
                title=f"⭐ Leveling & XP Dashboard • {guild.name}",
                description="Configure server XP accumulation rate, level-up broadcasts, and role rewards.",
                color=BRAND_COLOR,
                thumbnail=guild.icon.url if guild.icon else None,
            )
            embed.add_field(name="System Status", value=f"{'🟢 Enabled' if s.get('enabled', True) else '🔴 Disabled'}", inline=True)
            embed.add_field(name="XP per Message", value=f"`{s.get('min_xp', 15)} – {s.get('max_xp', 25)}` XP", inline=True)
            embed.add_field(name="Cooldown Duration", value=f"`{s.get('cooldown_seconds', 60)}s`", inline=True)
            embed.add_field(name="Announcement Channel", value=ch.mention if ch else "`Current Channel`", inline=True)
            embed.add_field(name="Configured Role Rewards", value=f"`{len(rewards)}` roles", inline=True)
            embed.add_field(name="Active Ranked Members", value=f"`{stats.get('total_users', 0):,}` members", inline=True)
            embed.set_footer(text="Death Bot Engagement & Progression Engine")
            return embed

        elif section == "economy":
            e_repo = self.bot.economy_repo
            s = await e_repo.get_settings(guild.id) if e_repo else {}
            stats = await e_repo.get_economy_stats(guild.id) if e_repo else {}

            sym = s.get("currency_symbol") or "🪙"
            cname = s.get("currency_name") or "Coins"

            embed = EmbedBuilder.base(
                title=f"🪙 Economy & Financial Dashboard • {guild.name}",
                description="Configure currency rules, starter allowances, and bank limits.",
                color=BRAND_COLOR,
                thumbnail=guild.icon.url if guild.icon else None,
            )
            embed.add_field(name="Currency Symbol", value=f"`{sym}` ({cname})", inline=True)
            embed.add_field(name="Daily Allowance", value=f"`{s.get('daily_min', 100)} – {s.get('daily_max', 300)}` {sym}", inline=True)
            embed.add_field(name="Bank Vault Cap", value=f"🏦 `{s.get('bank_cap', 50000):,}` {sym}", inline=True)
            embed.add_field(name="Total Circulation", value=f"{sym} `{stats.get('total_wallet', 0):,}`", inline=True)
            embed.add_field(name="Bank Reserves", value=f"🏦 `{stats.get('total_bank', 0):,}`", inline=True)
            embed.add_field(name="Ledger Transactions", value=f"🧾 `{stats.get('total_transactions', 0):,}`", inline=True)
            embed.set_footer(text="Death Bot Banking & Virtual Economy")
            return embed

        elif section == "shop":
            s_repo = self.bot.shop_repo
            items = await s_repo.get_items(guild.id) if s_repo else []
            stats = await s_repo.get_shop_stats(guild.id) if s_repo else {}
            cats = await s_repo.get_categories(guild.id) if s_repo else []

            embed = EmbedBuilder.base(
                title=f"🏪 Server Shop & Catalog Dashboard • {guild.name}",
                description="Inspect merchandise, role unlocks, and sales volume.",
                color=BRAND_COLOR,
                thumbnail=guild.icon.url if guild.icon else None,
            )
            embed.add_field(name="Catalog Items", value=f"`{stats.get('total_items', len(items))}` items", inline=True)
            embed.add_field(name="Shop Categories", value=f"`{len(cats)}` categories", inline=True)
            embed.add_field(name="Total Sales", value=f"📦 `{stats.get('total_purchases', 0):,}` orders", inline=True)
            embed.add_field(name="Gross Revenue", value=f"🪙 `{stats.get('total_revenue', 0):,}` Coins", inline=True)
            embed.set_footer(text="Death Bot Marketplace Administration")
            return embed

        else:  # minigames
            m_repo = self.bot.minigame_repo
            s = await m_repo.get_settings(guild.id) if m_repo else {}

            embed = EmbedBuilder.base(
                title=f"🎮 Minigames & Betting Dashboard • {guild.name}",
                description="Manage allowed betting amounts, cooldowns, and server daily challenges.",
                color=BRAND_COLOR,
                thumbnail=guild.icon.url if guild.icon else None,
            )
            embed.add_field(name="Minigames Status", value=f"{'🟢 Enabled' if s.get('enabled', True) else '🔴 Disabled'}", inline=True)
            embed.add_field(name="Min Bet Allowed", value=f"🪙 `{s.get('min_bet', 10):,}` Coins", inline=True)
            embed.add_field(name="Max Bet Allowed", value=f"🪙 `{s.get('max_bet', 5000):,}` Coins", inline=True)
            embed.add_field(name="Game Cooldown", value=f"`{s.get('cooldown_seconds', 15)}s` between matches", inline=True)
            embed.set_footer(text="Death Bot Arcade & Fair Randomization Engine")
            return embed

    @discord.ui.button(label="Refresh Panel", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = await self.build_section_embed(interaction.guild, self.current_section)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Dismiss", style=discord.ButtonStyle.danger, emoji="✖️", row=1)
    async def dismiss_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.message.delete()
        self.stop()

