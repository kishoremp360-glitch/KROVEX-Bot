"""Mimic Per-Server Bot Identity System for Death Bot.

Allows Death Bot to project a unique persona per Discord server:
- Custom bot server nickname
- Custom server-specific avatar (with format & size validation and API entitlement handling)
- Profile preview and reset
- Isolated SQLite persistence per guild
"""
from __future__ import annotations

import base64
import urllib.parse
from typing import TYPE_CHECKING, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.mimic")
BRAND_COLOR = 0x9D4EDD
MAX_AVATAR_SIZE = 8 * 1024 * 1024  # 8 MB
VALID_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


class Mimic(commands.Cog, name="Mimic"):
    """Per-server bot identity, nickname, and custom avatar persona management."""

    def __init__(self, bot: "DeathBot") -> None:
        self.bot = bot

    # ── 1. mimic nick ───────────────────────────────────────────────────────

    async def _execute_nick(self, ctx: UnifiedContext, nickname: str) -> None:
        guild = ctx.guild
        if not guild:
            await ctx.send_error("Unavailable", "This command can only be used inside a Discord server.")
            return

        nick_clean = nickname.strip()
        if not nick_clean:
            await ctx.send_error("Invalid Name", "Nickname cannot be empty.")
            return

        if len(nick_clean) > 32:
            await ctx.send_error("Too Long", "Discord nicknames cannot exceed 32 characters.")
            return

        # Check bot permissions
        if not guild.me.guild_permissions.change_nickname and not guild.me.guild_permissions.manage_nicknames:
            await ctx.send_error(
                "Missing Permission",
                "I require the **Change Nickname** or **Manage Nicknames** permission to update my identity in this server."
            )
            return

        old_nick = guild.me.display_name
        try:
            await guild.me.edit(nick=nick_clean, reason=f"Death Bot Mimic Persona updated by {ctx.author.name}")
        except discord.Forbidden:
            await ctx.send_error("Forbidden", "Discord denied permission to change my nickname (my role may be below the server owner or another bot).")
            return
        except discord.HTTPException as err:
            await ctx.send_error("Discord API Error", f"Failed to update nickname: {err}")
            return

        if self.bot.mimic_repo:
            await self.bot.mimic_repo.set_nickname(guild.id, nick_clean, original_name=guild.me.name)

        embed = EmbedBuilder.success(
            title="Mimic Identity Updated",
            description=(
                f"**Bot Nickname for {guild.name} has been set to:**\n"
                f"🎭 `{nick_clean}`\n\n"
                f"*Previous Name: {old_nick}*"
            ),
        )
        await ctx.reply(embed=embed)

    @commands.group(name="mimic", invoke_without_command=True, help="Manage Death Bot's per-server persona and identity.")
    @commands.has_permissions(administrator=True)
    async def mimic_group(self, ctx: commands.Context) -> None:
        await self._execute_preview(UnifiedContext.from_prefix(ctx))

    @mimic_group.command(name="nick", aliases=["name", "botnick"], help="Set the bot's custom nickname for this server.")
    @commands.has_permissions(administrator=True)
    async def mimic_nick(self, ctx: commands.Context, *, nickname: str) -> None:
        await self._execute_nick(UnifiedContext.from_prefix(ctx), nickname)

    # ── 2. mimic avatar ─────────────────────────────────────────────────────

    async def _execute_avatar(self, ctx: UnifiedContext, avatar_url: Optional[str] = None) -> None:
        guild = ctx.guild
        if not guild:
            await ctx.send_error("Unavailable", "This command can only be used inside a Discord server.")
            return

        # Check attachment if URL was not directly provided
        target_url = avatar_url
        if not target_url and ctx.prefix_context and ctx.prefix_context.message.attachments:
            target_url = ctx.prefix_context.message.attachments[0].url

        if not target_url:
            await ctx.send_error("Missing Image", "Please provide an image URL or attach an image file (`.png`, `.jpg`, `.jpeg`, `.webp`).")
            return

        # Validate URL extension
        parsed = urllib.parse.urlparse(target_url)
        clean_path = parsed.path.lower()
        if not any(clean_path.endswith(ext) for ext in VALID_IMAGE_EXTS):
            await ctx.send_error("Invalid Image Format", f"Avatar must be one of: {', '.join(VALID_IMAGE_EXTS)}")
            return

        # Fetch and validate file size
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(target_url, timeout=10) as resp:
                    if resp.status != 200:
                        await ctx.send_error("Download Error", f"Could not fetch image (HTTP {resp.status}).")
                        return
                    data = await resp.read()
                    if len(data) > MAX_AVATAR_SIZE:
                        await ctx.send_error("File Too Large", f"Image size exceeds Discord limit (Max 8 MB, received {len(data) // 1024} KB).")
                        return
                    content_type = resp.headers.get("Content-Type", "image/png").split(";")[0]
            except Exception as e:
                await ctx.send_error("Fetch Error", f"Failed to download image: {e}")
                return

        # 1. Call Discord's API first to apply the avatar
        try:
            # Under discord.py: guild.me.edit(avatar=...) issues the member PATCH to Discord API
            await guild.me.edit(avatar=data, reason=f"Death Bot Mimic Avatar updated by {ctx.author.name}")
        except (discord.HTTPException, discord.Forbidden, AttributeError) as err:
            logger.warning("Discord API per-server avatar rejected for guild %s: %s", guild.id, err)
            await ctx.send_error(
                "Discord API Restriction",
                (
                    f"Discord rejected the server avatar update: {err}\n\n"
                    "ℹ️ **Note:** Under the Discord Bot API, applying a custom per-server avatar directly in Discord's member list requires "
                    "server avatar entitlements for the bot application. The avatar was **not** applied or saved."
                )
            )
            return

        # 2. Discord confirmed API success -> persist configuration in SQLite
        db_saved = True
        if self.bot.mimic_repo:
            try:
                await self.bot.mimic_repo.set_avatar(guild.id, target_url)
            except Exception as db_err:
                logger.error("Failed to persist confirmed avatar to SQLite for guild %s: %s", guild.id, db_err)
                db_saved = False

        if not db_saved:
            embed = EmbedBuilder.warning(
                title="Avatar Applied (Storage Warning)",
                description=(
                    f"✅ **Discord confirmed avatar update for {guild.name}!**\n\n"
                    f"⚠️ **Database Warning:** Failed to persist the avatar URL to local database storage. "
                    f"The avatar is active in Discord, but local profile caching may be out of sync."
                ),
            )
            if target_url:
                embed.set_thumbnail(url=target_url)
            await ctx.reply(embed=embed)
            return

        embed = EmbedBuilder.success(
            title="Mimic Avatar Updated",
            description=f"✅ Discord API confirmed and saved custom avatar for **{guild.name}**.",
        )
        if target_url:
            embed.set_thumbnail(url=target_url)
        await ctx.reply(embed=embed)

    @mimic_group.command(name="avatar", aliases=["icon", "pic"], help="Set the bot's custom server avatar.")
    @commands.has_permissions(administrator=True)
    async def mimic_avatar(self, ctx: commands.Context, avatar_url: Optional[str] = None) -> None:
        await self._execute_avatar(UnifiedContext.from_prefix(ctx), avatar_url)

    # ── 3. mimic preview ────────────────────────────────────────────────────

    async def _execute_preview(self, ctx: UnifiedContext) -> None:
        guild = ctx.guild
        if not guild:
            return

        profile = await self.bot.mimic_repo.get_profile(guild.id) if self.bot.mimic_repo else {}
        custom_nick = profile.get("nickname") or guild.me.nick or "*Default (Not Set)*"
        custom_avatar = profile.get("avatar_url") or guild.me.display_avatar.url
        global_name = self.bot.user.name if self.bot.user else "Death Bot"

        embed = discord.Embed(
            title=f"🎭 Mimic Identity Profile • {guild.name}",
            description=(
                f"Overview of Death Bot's configured persona in this server:\n\n"
                f"• **Current Nickname:** `{custom_nick}`\n"
                f"• **Global Bot Name:** `{global_name}`\n"
                f"• **Server Context:** {guild.name} (`{guild.id}`)\n"
                f"• **Nick Management:** {'🟢 Permitted' if guild.me.guild_permissions.change_nickname else '🔴 Missing Permission'}\n"
                f"• **Banner Support:** ℹ️ *Server-specific banners are not supported by the Discord Bot API.*"
            ),
            color=BRAND_COLOR,
        )
        embed.set_thumbnail(url=custom_avatar)
        embed.set_footer(text="Use ',mimic nick <name>' or ',mimic reset' to configure.")
        await ctx.reply(embed=embed)

    @mimic_group.command(name="preview", help="Preview the bot's configured identity profile for this server.")
    @commands.has_permissions(administrator=True)
    async def mimic_preview(self, ctx: commands.Context) -> None:
        await self._execute_preview(UnifiedContext.from_prefix(ctx))

    # ── 4. mimic reset ──────────────────────────────────────────────────────

    async def _execute_reset(self, ctx: UnifiedContext) -> None:
        guild = ctx.guild
        if not guild:
            return

        if guild.me.guild_permissions.change_nickname:
            try:
                await guild.me.edit(nick=None, reason=f"Death Bot Mimic Persona reset by {ctx.author.name}")
            except Exception:
                pass

        if self.bot.mimic_repo:
            await self.bot.mimic_repo.reset_profile(guild.id)

        global_name = self.bot.user.name if self.bot.user else "Death Bot"
        embed = EmbedBuilder.success(
            title="Mimic Persona Reset",
            description=(
                f"The bot's identity for **{guild.name}** has been restored to default:\n\n"
                f"• **Name:** `{global_name}`\n"
                f"• **Avatar:** Restored to default bot branding.\n"
                f"• **Guild Configuration:** Cleared from SQLite database."
            ),
        )
        await ctx.reply(embed=embed)

    @mimic_group.command(name="reset", help="Reset the bot's identity in this server back to default branding.")
    @commands.has_permissions(administrator=True)
    async def mimic_reset(self, ctx: commands.Context) -> None:
        await self._execute_reset(UnifiedContext.from_prefix(ctx))

    # ── Slash Command Group (/mimic) ────────────────────────────────────────

    mimic_slash = app_commands.Group(
        name="mimic",
        description="Manage KROVEX's per-server persona and identity",
        default_permissions=discord.Permissions(administrator=True),
    )

    @mimic_slash.command(name="nick", description="Set the bot's custom nickname for this server")
    @app_commands.describe(nickname="The custom nickname for the bot (max 32 characters)")
    async def mimic_slash_nick(self, interaction: discord.Interaction, nickname: str) -> None:
        await interaction.response.defer()
        await self._execute_nick(UnifiedContext.from_interaction(interaction), nickname)

    @mimic_slash.command(name="avatar", description="Set the bot's custom avatar for this server")
    @app_commands.describe(avatar_url="Direct URL of the image (.png, .jpg, .webp)")
    async def mimic_slash_avatar(self, interaction: discord.Interaction, avatar_url: Optional[str] = None) -> None:
        await interaction.response.defer()
        await self._execute_avatar(UnifiedContext.from_interaction(interaction), avatar_url)

    @mimic_slash.command(name="preview", description="Preview the bot's configured identity profile for this server")
    async def mimic_slash_preview(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self._execute_preview(UnifiedContext.from_interaction(interaction))

    @mimic_slash.command(name="reset", description="Reset the bot's identity in this server back to default branding")
    async def mimic_slash_reset(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self._execute_reset(UnifiedContext.from_interaction(interaction))


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(Mimic(bot))

