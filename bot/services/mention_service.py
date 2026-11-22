"""Real-Time Mention Notification Service for Death Bot.

Monitors gateway messages across all mutual servers, detects user mentions,
and delivers instant, high-fidelity notification DMs with direct message jump links.
Matches the UGINEX reference specification while strictly respecting channel view
permissions, user opt-out preferences, and rate limits.
"""
from __future__ import annotations

import collections
import re
from typing import TYPE_CHECKING, Deque, Optional, Set

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import EmbedBuilder
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.services.mentions")
BRAND_COLOR = 0x9D4EDD
TOKEN_REGEX = re.compile(r"[a-zA-Z0-9_-]{23,28}\.[a-zA-Z0-9_-]{6,7}\.[a-zA-Z0-9_-]{27,}")


def _sanitize(text: str) -> str:
    """Mask potential bot tokens or credentials from message preview."""
    if not text:
        return ""
    return TOKEN_REGEX.sub("[REDACTED_TOKEN]", text)


class MentionService(commands.Cog, name="Mention Notifications"):
    """Event listener and management cog for real-time user mention notifications."""

    def __init__(self, bot: "DeathBot") -> None:
        self.bot = bot
        # Bounded cache of recently processed message IDs to prevent loops and duplicate triggers
        self._processed_messages: Deque[int] = collections.deque(maxlen=2000)

    def _build_mention_embed(
        self,
        message: discord.Message,
        target: discord.abc.User,
    ) -> discord.Embed:
        """Construct the standardized UGINEX-style real-time mention notification embed."""
        guild = message.guild
        guild_name = guild.name if guild else "Unknown Server"

        embed = discord.Embed(
            title=f"🔔 You were mentioned in {guild_name}",
            color=BRAND_COLOR,
            timestamp=message.created_at,
        )

        # 1. Mentioned User
        embed.add_field(
            name="Mentioned User",
            value=f"{target.mention} (`{target.name}`)",
            inline=True,
        )
        # 2. Server Name
        embed.add_field(
            name="Server",
            value=f"**{guild_name}**",
            inline=True,
        )
        # 3. Channel Name
        channel_str = message.channel.mention if hasattr(message.channel, "mention") else f"#{message.channel.name}"
        embed.add_field(
            name="Channel",
            value=channel_str,
            inline=True,
        )
        # 4. Message Author
        embed.add_field(
            name="Message Author",
            value=f"{message.author.mention} (`{message.author.name}`)",
            inline=True,
        )

        # 5. Message Content Preview (sanitized and bounded)
        if message.content:
            clean_text = _sanitize(message.content)
            if len(clean_text) > 400:
                clean_text = clean_text[:397] + "..."
            embed.add_field(
                name="Message Content",
                value=clean_text,
                inline=False,
            )

        # 6. Direct Jump Link
        jump_link = message.jump_url if hasattr(message, "jump_url") else f"https://discord.com/channels/{guild.id if guild else '@me'}/{message.channel.id}/{message.id}"
        embed.add_field(
            name="Direct Link",
            value=f"[Jump to Message]({jump_link})",
            inline=False,
        )

        if guild and guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        bot_icon = self.bot.user.display_avatar.url if self.bot.user else None
        bot_name = getattr(getattr(self.bot, "config", None), "bot_name", "DEATH BOT")
        embed.set_footer(text=f"{bot_name.upper()} • REAL-TIME MENTIONS", icon_url=bot_icon)
        return embed

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Inspect inbound messages for user mentions and deliver real-time DM notifications."""
        # 1. Ignore DMs, bot authors, and empty mentions
        if not message.guild or message.author.bot:
            return

        # 2. Duplicate & loop prevention
        if message.id in self._processed_messages:
            return
        self._processed_messages.append(message.id)

        # If there are no mentions in the message, exit early
        if not message.mentions:
            return

        # 3. Deduplicate targets and exclude:
        #    - Bot mentions
        #    - Self mentions (author mentioning themselves)
        seen_ids: Set[int] = set()
        targets: list[discord.Member | discord.User] = []

        for m in message.mentions:
            if m.id in seen_ids:
                continue
            seen_ids.add(m.id)

            # Ignore bots and author themselves
            if m.bot or m.id == message.author.id:
                continue

            targets.append(m)

        if not targets:
            return

        # 4. Process each target individually
        for target in targets:
            # A. Permission check: Ensure target has view/read permissions for the channel
            # We must never leak mentions from private channels to users who cannot access them!
            if isinstance(message.channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
                perms = message.channel.permissions_for(target) if isinstance(target, discord.Member) else None
                if perms is not None:
                    # Check read_messages (or view_channel)
                    can_read = getattr(perms, "read_messages", None)
                    if can_read is None:
                        can_read = getattr(perms, "view_channel", True)
                    if not can_read:
                        logger.debug("Skipping mention DM for %s: channel %s is not readable", target.id, message.channel.id)
                        continue

            # B. Opt-out check: Check if user disabled mention notifications in SQLite
            if hasattr(self.bot, "mention_repo") and self.bot.mention_repo:
                try:
                    is_enabled = await self.bot.mention_repo.is_enabled(target.id)
                    if not is_enabled:
                        logger.debug("Skipping mention DM for %s: notifications disabled in settings", target.id)
                        continue
                except Exception as err:
                    logger.warning("Error checking mention notification status for %s: %s", target.id, err)

            # C. Build notification embed
            embed = self._build_mention_embed(message, target)

            # D. Send DM via centralized global rate-limited DM Queue (with direct fallback)
            queue_service = getattr(self.bot, "dm_queue_service", None)
            if queue_service:
                await queue_service.enqueue(
                    recipient_id=target.id,
                    guild_id=message.guild.id,
                    message_type="mention",
                    embed=embed,
                    idempotency_key=f"mention:{message.guild.id}:{message.id}:{target.id}",
                )
                logger.info("Enqueued mention notification for %s (%s) for message %s in guild %s", target.name, target.id, message.id, message.guild.id)
            else:
                try:
                    await target.send(embed=embed)
                    logger.info("Sent direct mention DM to %s (%s) for message %s in guild %s", target.name, target.id, message.id, message.guild.id)
                except discord.Forbidden:
                    logger.debug("Cannot send mention DM to %s (%s): DMs are disabled/blocked", target.id, target.name)
                except discord.HTTPException as err:
                    logger.warning("HTTP error sending mention DM to %s (%s): %s", target.id, target.name, err)
                except Exception as err:
                    logger.error("Unexpected error delivering mention DM to %s: %s", target.id, err)

    # ========================================================
    # COMMANDS: PREFERENCES & TOGGLE
    # ========================================================

    @commands.command(name="mentionnotifs", aliases=["mentions", "mentionnotify"])
    async def mentionnotifs_prefix(self, ctx: commands.Context, state: Optional[str] = None) -> None:
        """Toggle or check real-time mention DM notifications.

        Usage:
            ,mentionnotifs
            ,mentionnotifs enable
            ,mentionnotifs disable
            ,mentionnotifs status
        """
        if not hasattr(self.bot, "mention_repo") or not self.bot.mention_repo:
            await ctx.send("❌ Mention notification database service is currently unavailable.")
            return

        user_id = ctx.author.id
        current = await self.bot.mention_repo.is_enabled(user_id)

        if state is None:
            # Toggle
            new_state = await self.bot.mention_repo.toggle(user_id)
            if new_state:
                embed = EmbedBuilder.success(
                    "Mention Notifications Enabled",
                    "You will now receive a direct message whenever you are mentioned in any server where Death Bot is active.",
                )
            else:
                embed = EmbedBuilder.warning(
                    "Mention Notifications Disabled",
                    "You will no longer receive direct messages when you are mentioned.",
                )
            await ctx.send(embed=embed)
            return

        state_lower = state.lower().strip()
        if state_lower in ("enable", "on", "yes", "true", "1"):
            await self.bot.mention_repo.set_enabled(user_id, True)
            embed = EmbedBuilder.success(
                "Mention Notifications Enabled",
                "You will now receive a direct message whenever you are mentioned in any server where Death Bot is active.",
            )
            await ctx.send(embed=embed)
        elif state_lower in ("disable", "off", "no", "false", "0"):
            await self.bot.mention_repo.set_enabled(user_id, False)
            embed = EmbedBuilder.warning(
                "Mention Notifications Disabled",
                "You will no longer receive direct messages when you are mentioned.",
            )
            await ctx.send(embed=embed)
        elif state_lower in ("status", "check", "info"):
            status_text = "**Enabled** 🔔 (You will receive DMs)" if current else "**Disabled** 🔕 (DMs paused)"
            embed = EmbedBuilder.info(
                "Mention Notification Status",
                f"Your real-time mention notifications are currently: {status_text}\n\n"
                f"Use `{ctx.prefix}mentionnotifs` to toggle or `{ctx.prefix}mentionnotifs [enable|disable]` to change.",
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ Unknown option `{state}`. Usage: `{ctx.prefix}mentionnotifs [enable|disable|status]`")


async def setup(bot: "DeathBot") -> None:
    """Extension entry point for MentionService."""
    await bot.add_cog(MentionService(bot))

