"""Social, user profiles, and economy cog."""

from __future__ import annotations

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


class Social(commands.Cog, name="Social & Economy"):
    """User profiles, level progression, and economy system."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    async def _execute_profile(self, ctx: UnifiedContext, target: Optional[discord.Member] = None) -> None:
        """Shared logic for viewing user profile."""
        member = target or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if not member:
            await ctx.send_error("Error", "Could not resolve user instance.")
            return

        profile = None
        if self.bot.user_repo:
            profile = await self.bot.user_repo.get_or_create(member.id)

        xp = profile.xp if profile else 0
        lvl = profile.level if profile else 1
        balance = profile.balance if profile else 0
        bio = profile.bio if profile else "A mysterious user."

        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.AESTHETIC} User Profile • {member.display_name}",
            description=bio,
            color=0x9D4EDD,
            thumbnail=member.display_avatar.url,
        )
        embed.add_field(name="Level", value=f"⭐ `{lvl}`", inline=True)
        embed.add_field(name="Experience", value=f"✨ `{xp}` XP", inline=True)
        embed.add_field(name="Balance", value=f"🪙 `{balance}` Coins", inline=True)
        embed.add_field(name="Discord Joined", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        if member.joined_at:
            embed.add_field(name="Server Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)

        await ctx.reply(embed=embed)

    @commands.command(name="profile", help="View user profile, level, and stats.")
    async def profile_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_profile(UnifiedContext.from_prefix(ctx), member)

    async def _execute_daily(self, ctx: UnifiedContext) -> None:
        """Shared logic for claiming daily reward."""
        if not self.bot.user_repo:
            await ctx.send_error("Database Offline", "Database is unavailable. Cannot claim daily coins.")
            return

        reward = random.randint(100, 300)
        new_balance = await self.bot.user_repo.update_balance(ctx.author.id, reward)
        await self.bot.user_repo.add_xp(ctx.author.id, 25)

        embed = EmbedBuilder.success(
            title="Daily Reward Claimed!",
            description=(
                f"You claimed your daily allowance of **+{reward}** 🪙 Coins!\n"
                f"Earned **+25** XP!\n\n"
                f"**New Balance:** `{new_balance}` Coins"
            ),
        )
        await ctx.reply(embed=embed)

    @commands.command(name="daily", help="Claim your daily coin reward.")
    @commands.cooldown(1, 86400, commands.BucketType.user)
    async def daily_prefix(self, ctx: commands.Context) -> None:
        await self._execute_daily(UnifiedContext.from_prefix(ctx))


async def setup(bot: DeathBot) -> None:
    """Setup hook to register cog."""
    await bot.add_cog(Social(bot))

