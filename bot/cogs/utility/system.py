"""System diagnostics, health checks, and bot management commands."""

from __future__ import annotations

import platform
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands
import psutil

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji

if TYPE_CHECKING:
    from bot.core.bot import DeathBot


class System(commands.Cog, name="System & Utility"):
    """Core system telemetry, bot statistics, and guild management."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    # --------------------------------------------------------------------------
    # Health Command
    # --------------------------------------------------------------------------
    async def _execute_health(self, ctx: UnifiedContext) -> None:
        """Shared logic for subsystem health check."""
        # Check DB
        db_healthy = False
        if self.bot.db_manager:
            db_healthy = self.bot.db_manager.is_connected

        # Check Gateway
        gw_healthy = self.bot.is_ready() and not self.bot.is_closed()

        overall = "Healthy" if db_healthy and gw_healthy else "Degraded"
        color = 0x00F5A0 if overall == "Healthy" else 0xF59E0B

        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.LIGHTNING} Subsystem Diagnostics • {overall}",
            description="Live health verification of all integrated subsystems.",
            color=color,
        )
        embed.add_field(
            name="Discord Gateway",
            value="🟢 Connected" if gw_healthy else "🔴 Disconnected",
            inline=True,
        )
        embed.add_field(
            name="SQLite Database",
            value="🟢 Operational (WAL)" if db_healthy else "🟡 Unreachable / Offline",
            inline=True,
        )
        embed.add_field(
            name="Voice Engine",
            value="🟢 PyNaCl Loaded" if discord.voice_client.has_nacl else "🔴 PyNaCl Missing",
            inline=True,
        )
        embed.add_field(
            name="HTTP Session",
            value="🟢 Active" if self.bot.session and not self.bot.session.closed else "🔴 Closed",
            inline=True,
        )

        await ctx.reply(embed=embed)

    @commands.command(name="health", help="Check subsystem health and connectivity.")
    async def health_prefix(self, ctx: commands.Context) -> None:
        await self._execute_health(UnifiedContext.from_prefix(ctx))

    # --------------------------------------------------------------------------
    # Prefix Command
    # --------------------------------------------------------------------------
    async def _execute_prefix(self, ctx: UnifiedContext, new_prefix: Optional[str] = None) -> None:
        """Shared logic for viewing or changing guild prefix."""
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used within a server.")
            return

        current_prefix = await self.bot.guild_repo.get_prefix(ctx.guild.id, self.bot.config.default_prefix) if self.bot.guild_repo else self.bot.config.default_prefix

        # If no new prefix supplied, show current prefix
        if new_prefix is None:
            await ctx.send_info(
                title="Server Prefix",
                description=f"The current prefix for **{ctx.guild.name}** is: `{current_prefix}`\n"
                            f"To change it, use: `{current_prefix}prefix <new_prefix>`",
            )
            return

        # Check permissions
        if isinstance(ctx.author, discord.Member) and not ctx.author.guild_permissions.manage_guild:
            await ctx.send_error(
                title="Permission Denied",
                description="You require the `Manage Server` permission to modify the prefix.",
            )
            return

        clean_prefix = new_prefix.strip()
        if len(clean_prefix) > 5:
            await ctx.send_error("Invalid Prefix", "Prefix length cannot exceed 5 characters.")
            return

        if not self.bot.guild_repo:
            await ctx.send_error("Database Offline", "Database is unavailable. Cannot save custom prefix.")
            return

        await self.bot.guild_repo.set_prefix(ctx.guild.id, clean_prefix)
        await ctx.send_success(
            title="Prefix Updated",
            description=f"Prefix for **{ctx.guild.name}** has been updated to: `{clean_prefix}`",
        )

    @commands.command(name="prefix", help="View or update the server command prefix.")
    async def prefix_prefix(self, ctx: commands.Context, new_prefix: Optional[str] = None) -> None:
        await self._execute_prefix(UnifiedContext.from_prefix(ctx), new_prefix)


async def setup(bot: DeathBot) -> None:
    """Setup hook to register cog."""
    await bot.add_cog(System(bot))

