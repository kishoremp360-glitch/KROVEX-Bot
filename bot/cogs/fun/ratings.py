"""Ratings, Meters & Fun Humor Module for Death Bot (Batch 2B).

Provides 20 playful, PG-13, strictly SFW entertainment commands:
- Ratings & meters: gay, howgay, gaymeter, love, lovemeter, lesbian, cute,
  intelligence, iq, genius, brainrate, horny, tharki, dumb, simprate, toxic, howhot
- Fun & humor: chutiya, autorelationship, roast
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.fun import _ratings_data
from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.ratings_fun")
BRAND_COLOR = 0x9D4EDD
PINK_COLOR = 0xFF69B4
GOLD_COLOR = 0xF59E0B
CYAN_COLOR = 0x00F5A0

DISCLAIMER_TEXT = "⚠️ Fictional rating for entertainment purposes only • Harmless fun"


class RatingsFun(commands.Cog, name="Ratings & Fun"):
    """Playful ratings, compatibility meters, and entertainment commands."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    # ── SHARED METER DISPATCHER ──────────────────────────────────────────────

    async def _execute_meter(
        self,
        ctx: UnifiedContext,
        meter_type: str,
        target: Optional[discord.Member] = None,
    ) -> None:
        """Generic meter rating engine with progress bars and tiered commentary."""
        member = target or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if not member:
            member = ctx.author

        mtype = meter_type.lower()
        score = _ratings_data.get_user_metric(member.id, mtype)
        bar = _ratings_data.generate_bar(score, 0, 100, 10)

        # Config per meter type
        meta = {
            "gay": (f"{KrovexEmoji.RAINBOW_STAR} Rainbow Pride Affinity", _ratings_data.GAY_TIERS, PINK_COLOR),
            "lesbian": (f"{KrovexEmoji.ANIMATED_HEART} Lesbian Affinity Meter", _ratings_data.LESBIAN_TIERS, PINK_COLOR),
            "cute": (f"{KrovexEmoji.CUTE_STAR} Cuteness Rating", _ratings_data.CUTE_TIERS, PINK_COLOR),
            "howhot": (f"{KrovexEmoji.LIGHTNING} Hotness / Spicy Rating", _ratings_data.HOT_TIERS, 0xFF3366),
            "horny": (f"{KrovexEmoji.WARNING} Horny / Mischief Rating", _ratings_data.HORNY_TIERS, GOLD_COLOR),
            "tharki": ("🕶️ Tharki / Flirty Meter", _ratings_data.THARKI_TIERS, GOLD_COLOR),
            "dumb": ("🤪 Goofiness Rating", _ratings_data.DUMB_TIERS, GOLD_COLOR),
            "simprate": (f"{KrovexEmoji.WHITE_CROWN} Simp Percentage", _ratings_data.SIMP_TIERS, BRAND_COLOR),
            "toxic": ("☢️ Toxicity Meter", _ratings_data.TOXIC_TIERS, 0x00F5A0),
            "brainrate": ("🧠 Brain Cell Activity", _ratings_data.IQ_TIERS, CYAN_COLOR),
            "chutiya": ("🤦 Desi Silliness Meter", _ratings_data.CHUTIYA_TIERS, GOLD_COLOR),
        }

        title, tiers, color = meta.get(mtype, ("🎯 Fun Rating", _ratings_data.CUTE_TIERS, BRAND_COLOR))
        commentary = _ratings_data.get_tier_commentary(score, tiers)

        embed = discord.Embed(
            title=f"{title} • {score}%",
            description=(
                f"**Target:** {member.mention}\n\n"
                f"**Rating:** `{score}%`\n"
                f"`[{bar}]`\n\n"
                f"{commentary}"
            ),
            color=color,
        )
        if hasattr(member, "display_avatar"):
            embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"{DISCLAIMER_TEXT} • Requested by {ctx.author.name}")

        await ctx.reply(embed=embed)

    # ── IQ & INTELLIGENCE DISPATCHER ─────────────────────────────────────────

    async def _execute_iq(
        self,
        ctx: UnifiedContext,
        target: Optional[discord.Member] = None,
    ) -> None:
        """Playful fictional IQ rating (50–220)."""
        member = target or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if not member:
            member = ctx.author

        iq_score = _ratings_data.get_user_metric(member.id, "iq_score", min_val=50, max_val=220)
        bar = _ratings_data.generate_bar(iq_score, min_val=50, max_val=220, length=10)
        commentary = _ratings_data.get_tier_commentary(iq_score, _ratings_data.IQ_TIERS)

        embed = discord.Embed(
            title=f"🧠 Big Brain / IQ Assessment • {iq_score} IQ",
            description=(
                f"**Tested Member:** {member.mention}\n\n"
                f"**Fictional IQ:** `{iq_score}`\n"
                f"`[{bar}]`\n\n"
                f"{commentary}"
            ),
            color=CYAN_COLOR,
        )
        if hasattr(member, "display_avatar"):
            embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"{DISCLAIMER_TEXT} • Not a real clinical test")

        await ctx.reply(embed=embed)

    # ── LOVE & LOVEMETER ─────────────────────────────────────────────────────

    async def _execute_love(
        self,
        ctx: UnifiedContext,
        user1: Optional[discord.Member] = None,
        user2: Optional[discord.Member] = None,
    ) -> None:
        """Two-user love compatibility meter."""
        if user1 is None and user2 is None:
            target1 = ctx.author
            target2 = ctx.author
        elif user2 is None:
            target1 = ctx.author
            target2 = user1
        else:
            target1 = user1
            target2 = user2

        if target1.id == target2.id:
            embed = discord.Embed(
                title="💖 Self-Love Affinity • 100%",
                description=(
                    f"**{target1.display_name}** is radiating 100% pure self-love!\n"
                    f"`[██████████]` **100%**\n\n"
                    f"👑 **Self-Care Icon:** Prioritizing your own happiness is peak emotional intelligence."
                ),
                color=PINK_COLOR,
            )
            if hasattr(target1, "display_avatar"):
                embed.set_thumbnail(url=target1.display_avatar.url)
            embed.set_footer(text=f"{DISCLAIMER_TEXT}")
            await ctx.reply(embed=embed)
            return

        score = _ratings_data.get_pair_metric(target1.id, target2.id, "love")
        bar = _ratings_data.generate_bar(score, 0, 100, 10)

        if score >= 90:
            verdict = "💍 **Undying Soulmates** — True love transcends time and server channels!"
        elif score >= 70:
            verdict = "💖 **Electric Romance** — Sparks flying everywhere! Grab some dessert together."
        elif score >= 50:
            verdict = "🌸 **Warm Chemistry** — Great compatibility with romantic potential."
        elif score >= 30:
            verdict = "☕ **Casual Besties** — Better off sharing memes and playing video games."
        else:
            verdict = "💔 **Opposites Collide** — Might want to keep some distance in the group chat!"

        embed = discord.Embed(
            title=f"💘 Love Meter • {score}%",
            description=(
                f"**Matchup:** {target1.mention} + {target2.mention}\n\n"
                f"**Love Affinity:** `{score}%`\n"
                f"`[{bar}]`\n\n"
                f"{verdict}"
            ),
            color=PINK_COLOR,
        )
        if hasattr(target2, "display_avatar"):
            embed.set_thumbnail(url=target2.display_avatar.url)
        embed.set_footer(text=f"{DISCLAIMER_TEXT} • Requested by {ctx.author.name}")

        await ctx.reply(embed=embed)

    # ── AUTORELATIONSHIP ─────────────────────────────────────────────────────

    async def _execute_autorelationship(
        self,
        ctx: UnifiedContext,
        user1: Optional[discord.Member] = None,
        user2: Optional[discord.Member] = None,
    ) -> None:
        """Generate a creative, funny fictional relationship status between members."""
        guild = ctx.guild
        if user1 and user2:
            partner1, partner2 = user1, user2
        elif user1 and not user2:
            partner1, partner2 = ctx.author, user1
        else:
            if not guild:
                await ctx.send_error("Server Only", "The autorelationship command can only be used in a Discord server.")
                return
            members = [m for m in guild.members if not m.bot]
            if len(members) < 2:
                await ctx.send_error("Not Enough Members", "At least 2 non-bot members are required for autorelationship!")
                return
            partner1, partner2 = random.sample(members, 2)

        status_msg = random.choice(_ratings_data.RELATIONSHIP_STATUSES)

        embed = discord.Embed(
            title="✨ Auto-Relationship Generator ✨",
            description=(
                f"**Matchup:** {partner1.mention} & {partner2.mention}\n\n"
                f"**Official Fictional Status:**\n"
                f"> **{status_msg}**\n\n"
                f"ℹ️ *This is a playful generator for fun. No server roles or permissions were altered.*"
            ),
            color=BRAND_COLOR,
        )
        if hasattr(partner1, "display_avatar"):
            embed.set_thumbnail(url=partner1.display_avatar.url)
        embed.set_footer(text=f"{DISCLAIMER_TEXT}")

        await ctx.reply(embed=embed)

    # ── ROAST ────────────────────────────────────────────────────────────────

    async def _execute_roast(
        self,
        ctx: UnifiedContext,
        target: Optional[discord.Member] = None,
    ) -> None:
        """Deliver a witty, PG-13, non-abusive comedy roast."""
        member = target or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if not member or member.id == ctx.author.id:
            await ctx.reply(
                embed=discord.Embed(
                    title="🔥 Self-Roast Denied",
                    description=(
                        f"**{ctx.author.display_name}**, roasting yourself? I respect the self-awareness,\n"
                        f"but Death Bot doesn't punch down on people who are already hurting! Stay awesome. ✨"
                    ),
                    color=BRAND_COLOR,
                )
            )
            return

        roast_line = random.choice(_ratings_data.ROAST_POOL)
        roast_gifs = [
            "https://media.tenor.com/v_gG3Jc24aYAAAAC/anime-angry.gif",
            "https://media.tenor.com/tO3aL9v3f9wAAAAC/anime-rage.gif",
            "https://media.tenor.com/5V3A4GZ24rYAAAAC/anime-tableflip.gif",
            "https://media.tenor.com/X4Xo1E3lPZcAAAAC/anime-knockout.gif",
            "https://media.tenor.com/bCq8vK8z9w4AAAAC/anime-bonk.gif",
        ]

        embed = discord.Embed(
            title="🔥 Roasted!",
            description=(
                f"{member.mention},\n\n"
                f"> *\"{roast_line}\"*\n\n"
                f"🧊 *Better grab some aloe vera for that burn!*"
            ),
            color=0xFF3366,
        )
        embed.set_image(url=random.choice(roast_gifs))
        if hasattr(member, "display_avatar"):
            embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="🎭 Playful comedy roast • Anime GIF reaction")

        await ctx.reply(embed=embed)

    # ── PREFIX COMMANDS (ALL 20 COMMANDS) ────────────────────────────────────

    @commands.command(name="gay", help="Measure rainbow pride affinity (fictional entertainment).")
    async def gay_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "gay", member)

    @commands.command(name="howgay", help="Measure rainbow pride affinity (fictional entertainment).")
    async def howgay_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "gay", member)

    @commands.command(name="gaymeter", help="Measure rainbow pride affinity (fictional entertainment).")
    async def gaymeter_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "gay", member)

    @commands.command(name="lesbian", help="Measure celebratory lesbian affinity (fictional entertainment).")
    async def lesbian_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "lesbian", member)

    @commands.command(name="cute", help="Calculate cuteness rating for a member.")
    async def cute_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "cute", member)

    @commands.command(name="howhot", help="Calculate hotness / spice rating for a member.")
    async def howhot_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "howhot", member)

    @commands.command(name="horny", help="Calculate playful mischief / horny meter (SFW cartoon humor).")
    async def horny_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "horny", member)

    @commands.command(name="tharki", help="Calculate Desi flirty rating (SFW meme humor).")
    async def tharki_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "tharki", member)

    @commands.command(name="dumb", help="Calculate fictional goofiness score.")
    async def dumb_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "dumb", member)

    @commands.command(name="simprate", help="Calculate simp percentage for a member.")
    async def simprate_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "simprate", member)

    @commands.command(name="toxic", help="Calculate playful gamer toxicity score.")
    async def toxic_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "toxic", member)

    @commands.command(name="brainrate", help="Calculate brain cell activity score.")
    async def brainrate_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "brainrate", member)

    @commands.command(name="chutiya", help="Calculate Desi silliness score (harmless comedy).")
    async def chutiya_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_meter(UnifiedContext.from_prefix(ctx), "chutiya", member)

    @commands.command(name="intelligence", help="Calculate playful Big Brain / IQ score.")
    async def intelligence_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_iq(UnifiedContext.from_prefix(ctx), member)

    @commands.command(name="iq", help="Calculate playful Big Brain / IQ score.")
    async def iq_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_iq(UnifiedContext.from_prefix(ctx), member)

    @commands.command(name="genius", help="Calculate playful Big Brain / IQ score.")
    async def genius_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_iq(UnifiedContext.from_prefix(ctx), member)

    @commands.command(name="autorelationship", help="Generate a funny fictional relationship status.")
    async def autorelationship_prefix(self, ctx: commands.Context, user1: Optional[discord.Member] = None, user2: Optional[discord.Member] = None) -> None:
        await self._execute_autorelationship(UnifiedContext.from_prefix(ctx), user1, user2)

    @commands.command(name="roast", help="Deliver a witty, PG-13, non-abusive comedy roast.")
    async def roast_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_roast(UnifiedContext.from_prefix(ctx), member)


# ── /rate SLASH COMMAND GROUP (CONSERVING ROOT SLOTS) ─────────────────────────

rate_group = app_commands.Group(name="rate", description="Playful ratings and meters module")


def _register_rate_subcommands() -> None:
    """Register subcommands under /rate Slash Group."""
    meter_actions = [
        ("rainbow", "Measure vibrant rainbow vibe score (fictional)"),
        ("harmony", "Measure celebratory harmony affinity (fictional)"),
        ("cute", "Calculate cuteness rating"),
        ("howhot", "Calculate hotness/spiciness rating"),
        ("mischief", "Calculate playful mischief rating (harmless cartoon humor)"),
        ("flirt", "Calculate playful charm and flirty rating (harmless comedy)"),
        ("dumb", "Calculate fictional goofiness score"),
        ("simp", "Calculate simp percentage"),
        ("toxic", "Calculate playful gamer toxicity score"),
        ("brain", "Calculate brain cell activity score"),
        ("goofy", "Calculate playful goofiness and silliness score (harmless comedy)"),
    ]

    action_to_metric = {
        "rainbow": "gay",
        "harmony": "lesbian",
        "mischief": "horny",
        "flirt": "tharki",
        "goofy": "chutiya",
        "simp": "simprate",
        "brain": "brainrate",
    }

    for mtype, desc in meter_actions:
        metric_key = action_to_metric.get(mtype, mtype)

        def make_cmd(cmd_name: str, description: str, key: str):
            @app_commands.command(name=cmd_name, description=description)
            @app_commands.describe(member="Member to rate (optional, defaults to you)")
            async def cmd(interaction: discord.Interaction, member: Optional[discord.Member] = None):
                cog: RatingsFun = interaction.client.cogs["Ratings & Fun"]
                await cog._execute_meter(UnifiedContext.from_interaction(interaction), key, member)
            return cmd

        rate_group.add_command(make_cmd(mtype, desc, metric_key))

    # Add iq subcommand
    @app_commands.command(name="iq", description="Calculate playful Big Brain / IQ score (fictional)")
    @app_commands.describe(member="Member to test (optional, defaults to you)")
    async def iq_cmd(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        cog: RatingsFun = interaction.client.cogs["Ratings & Fun"]
        await cog._execute_iq(UnifiedContext.from_interaction(interaction), member)

    rate_group.add_command(iq_cmd)

    # Add autorelationship subcommand
    @app_commands.command(name="autorelationship", description="Generate a funny fictional relationship status")
    @app_commands.describe(user1="First member (optional)", user2="Second member (optional)")
    async def rel_cmd(interaction: discord.Interaction, user1: Optional[discord.Member] = None, user2: Optional[discord.Member] = None):
        cog: RatingsFun = interaction.client.cogs["Ratings & Fun"]
        await cog._execute_autorelationship(UnifiedContext.from_interaction(interaction), user1, user2)

    rate_group.add_command(rel_cmd)


_register_rate_subcommands()


async def setup(bot: DeathBot) -> None:
    """Setup hook to register cog and slash command group."""
    cog = RatingsFun(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(rate_group)
    logger.info("Loaded Ratings & Fun module with 20 commands.")

