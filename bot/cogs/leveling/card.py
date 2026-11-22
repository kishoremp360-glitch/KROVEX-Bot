"""Rank card generator and progress visualizer for the leveling system."""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

import discord

from bot.utils.embeds import EmbedBuilder

BRAND_COLOR = 0x9D4EDD


def build_progress_bar(current: int, total: int, length: int = 16) -> str:
    """Render a text-based Unicode progress bar."""
    if total <= 0:
        pct = 1.0
    else:
        pct = max(0.0, min(1.0, current / total))

    filled = int(round(length * pct))
    unfilled = length - filled
    bar = "█" * filled + "░" * unfilled
    percentage_str = f"{int(pct * 100)}%"
    return f"`[{bar}]` **{percentage_str}**"


def render_rank_card(
    member: discord.Member,
    member_data: Dict[str, Any],
    rank: int,
    next_reward_role: Optional[discord.Role] = None,
) -> discord.Embed:
    """Render a rich, polished Discord embed card for member XP and rank."""
    level = member_data.get("level") or 0
    total_xp = member_data.get("xp") or 0
    messages = member_data.get("messages_count") or 0

    # Curve calculation: level N requires (N * 150) XP from previous level
    current_level_base = sum(i * 150 for i in range(1, level + 1))
    next_level_cost = (level + 1) * 150
    current_progress_xp = max(0, total_xp - current_level_base)

    progress_bar = build_progress_bar(current_progress_xp, next_level_cost)

    embed = EmbedBuilder.base(
        title=f"⭐ Rank Profile • {member.display_name}",
        color=BRAND_COLOR,
        thumbnail=member.display_avatar.url,
    )

    embed.add_field(name="Server Rank", value=f"🏆 **#{rank}**", inline=True)
    embed.add_field(name="Level", value=f"⭐ **Level {level}**", inline=True)
    embed.add_field(name="Total XP", value=f"✨ **{total_xp:,}** XP", inline=True)

    embed.add_field(
        name="Level Progress",
        value=(
            f"{progress_bar}\n"
            f"**{current_progress_xp:,}** / **{next_level_cost:,}** XP to Level **{level + 1}**\n"
            f"*(Total Messages: `{messages:,}`)*"
        ),
        inline=False,
    )

    if next_reward_role:
        embed.add_field(
            name="Next Role Reward",
            value=f"🎁 {next_reward_role.mention}",
            inline=True,
        )

    embed.set_footer(
        text=f"{member.guild.name} • Leveling Engine",
        icon_url=member.guild.icon.url if member.guild.icon else None,
    )
    return embed


async def setup(bot: Any) -> None:
    """Extension dummy setup."""
    pass

