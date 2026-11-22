"""Moderation and channel governance cog for KROVEX."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Optional, Union

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.database.models import ModerationLog
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.moderation")
BRAND_COLOR = 0x9D4EDD


class Moderation(commands.Cog, name="Moderation"):
    """Server moderation, sanctions, case logging, and channel governance."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    def _check_hierarchy(self, mod: discord.Member, bot_member: discord.Member, target: discord.Member) -> Optional[str]:
        """Validate role hierarchy and sovereign protections."""
        if target.id == mod.guild.owner_id:
            return "Cannot execute moderation actions on the Server Sovereign."
        if target.id == mod.id:
            return "You cannot moderate yourself."
        if target.id == bot_member.id:
            return "I cannot moderate myself."

        raw_owners = getattr(getattr(self.bot, "config", None), "owner_ids", []) or []
        bot_owners = getattr(self.bot, "owner_ids", None) or []
        if target.id in raw_owners or str(target.id) in [str(x) for x in raw_owners] or target.id in bot_owners:
            return "Cannot execute moderation actions on a KROVEX Bot Owner."

        target_pos = getattr(getattr(target, "top_role", None), "position", 0)
        mod_pos = getattr(getattr(mod, "top_role", None), "position", 0)
        bot_pos = getattr(getattr(bot_member, "top_role", None), "position", 0)

        # Mod hierarchy (unless guild owner)
        if mod.id != mod.guild.owner_id and target_pos >= mod_pos:
            return f"Cannot moderate {target.mention}: their highest role is equal to or higher than yours."

        # Bot hierarchy
        if target_pos >= bot_pos:
            return f"Cannot moderate {target.mention}: my role is not high enough to act on them."

        return None

    # ═══════════════════════════════════════════════════════════════════════════
    #  1. BAN & UNBAN
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_ban(self, ctx: UnifiedContext, target: discord.Member, reason: str, delete_days: int = 0) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        bot_member = ctx.guild.me
        if not bot_member.guild_permissions.ban_members:
            await ctx.send_error("Missing Permission", "I need the **Ban Members** permission.")
            return

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        if not author or (not author.guild_permissions.ban_members and author.id != ctx.guild.owner_id):
            await ctx.send_error("Access Denied", "You need the **Ban Members** permission.")
            return

        err = self._check_hierarchy(author, bot_member, target)
        if err:
            await ctx.send_error("Hierarchy Error", err)
            return

        try:
            delete_sec = max(0, min(7, delete_days)) * 86400
            await ctx.guild.ban(target, reason=f"{reason} (Executor: {author})", delete_message_seconds=delete_sec)

            if self.bot.moderation_repo:
                await self.bot.moderation_repo.add_case(ModerationLog(
                    guild_id=ctx.guild.id,
                    case_id=0,
                    user_id=target.id,
                    moderator_id=author.id,
                    action="BAN",
                    reason=reason,
                ))

            embed = EmbedBuilder.success(
                title=f"{KrovexEmoji.MODERATION} Member Banned",
                description=f"**{target}** (`{target.id}`) has been permanently banned from **{ctx.guild.name}**.\n\n"
                            f"• **Reason:** {reason}\n"
                            f"• **Moderator:** {author.mention}",
            )
            await ctx.reply(embed=embed)
        except Exception as e:
            await ctx.send_error("Ban Failed", str(e))

    @commands.command(name="ban", help="Ban a member from the server.")
    @commands.has_permissions(ban_members=True)
    async def ban_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided") -> None:
        await self._execute_ban(UnifiedContext.from_prefix(ctx), member, reason)

    @app_commands.command(name="ban", description="Ban a member from the server.")
    @app_commands.describe(member="The member to ban", reason="Reason for the ban", delete_days="Days of messages to delete (0-7)")
    @app_commands.default_permissions(ban_members=True)
    async def ban_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided", delete_days: int = 0) -> None:
        await self._execute_ban(UnifiedContext.from_interaction(interaction), member, reason, delete_days)

    async def _execute_unban(self, ctx: UnifiedContext, user_id_str: str, reason: str) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        bot_member = ctx.guild.me
        if not bot_member.guild_permissions.ban_members:
            await ctx.send_error("Missing Permission", "I need the **Ban Members** permission.")
            return

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        if not author or (not author.guild_permissions.ban_members and author.id != ctx.guild.owner_id):
            await ctx.send_error("Access Denied", "You need the **Ban Members** permission.")
            return

        try:
            user_id = int(user_id_str.strip("<@!>"))
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=f"{reason} (Executor: {author})")

            if self.bot.moderation_repo:
                await self.bot.moderation_repo.add_case(ModerationLog(
                    guild_id=ctx.guild.id,
                    case_id=0,
                    user_id=user.id,
                    moderator_id=author.id,
                    action="UNBAN",
                    reason=reason,
                ))

            embed = EmbedBuilder.success(
                title=f"{KrovexEmoji.SUCCESS} Member Unbanned",
                description=f"**{user}** (`{user.id}`) was unbanned from **{ctx.guild.name}**.\n\n"
                            f"• **Reason:** {reason}\n"
                            f"• **Moderator:** {author.mention}",
            )
            await ctx.reply(embed=embed)
        except ValueError:
            await ctx.send_error("Invalid ID", "Please specify a valid numeric User ID.")
        except discord.NotFound:
            await ctx.send_error("Not Found", "This user is not currently banned in this server.")
        except Exception as e:
            await ctx.send_error("Unban Failed", str(e))

    @commands.command(name="unban", help="Unban a user by their User ID.")
    @commands.has_permissions(ban_members=True)
    async def unban_prefix(self, ctx: commands.Context, user_id: str, *, reason: str = "No reason provided") -> None:
        await self._execute_unban(UnifiedContext.from_prefix(ctx), user_id, reason)

    @app_commands.command(name="unban", description="Unban a user by User ID.")
    @app_commands.describe(user_id="The Discord User ID to unban", reason="Reason for unbanning")
    @app_commands.default_permissions(ban_members=True)
    async def unban_slash(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided") -> None:
        await self._execute_unban(UnifiedContext.from_interaction(interaction), user_id, reason)

    # ═══════════════════════════════════════════════════════════════════════════
    #  2. KICK
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_kick(self, ctx: UnifiedContext, target: discord.Member, reason: str) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        bot_member = ctx.guild.me
        if not bot_member.guild_permissions.kick_members:
            await ctx.send_error("Missing Permission", "I need the **Kick Members** permission.")
            return

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        if not author or (not author.guild_permissions.kick_members and author.id != ctx.guild.owner_id):
            await ctx.send_error("Access Denied", "You need the **Kick Members** permission.")
            return

        err = self._check_hierarchy(author, bot_member, target)
        if err:
            await ctx.send_error("Hierarchy Error", err)
            return

        try:
            await target.kick(reason=f"{reason} (Executor: {author})")

            if self.bot.moderation_repo:
                await self.bot.moderation_repo.add_case(ModerationLog(
                    guild_id=ctx.guild.id,
                    case_id=0,
                    user_id=target.id,
                    moderator_id=author.id,
                    action="KICK",
                    reason=reason,
                ))

            embed = EmbedBuilder.success(
                title=f"{KrovexEmoji.MODERATION} Member Kicked",
                description=f"**{target}** (`{target.id}`) has been kicked from **{ctx.guild.name}**.\n\n"
                            f"• **Reason:** {reason}\n"
                            f"• **Moderator:** {author.mention}",
            )
            await ctx.reply(embed=embed)
        except Exception as e:
            await ctx.send_error("Kick Failed", str(e))

    @commands.command(name="kick", help="Kick a member from the server.")
    @commands.has_permissions(kick_members=True)
    async def kick_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided") -> None:
        await self._execute_kick(UnifiedContext.from_prefix(ctx), member, reason)

    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.describe(member="The member to kick", reason="Reason for the kick")
    @app_commands.default_permissions(kick_members=True)
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        await self._execute_kick(UnifiedContext.from_interaction(interaction), member, reason)

    # ═══════════════════════════════════════════════════════════════════════════
    #  3. TIMEOUT & UNTIMEOUT
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_timeout(self, ctx: UnifiedContext, target: discord.Member, minutes: int, reason: str) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        bot_member = ctx.guild.me
        if not bot_member.guild_permissions.moderate_members:
            await ctx.send_error("Missing Permission", "I need the **Timeout Members** permission.")
            return

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        if not author or (not author.guild_permissions.moderate_members and author.id != ctx.guild.owner_id):
            await ctx.send_error("Access Denied", "You need the **Timeout Members** permission.")
            return

        err = self._check_hierarchy(author, bot_member, target)
        if err:
            await ctx.send_error("Hierarchy Error", err)
            return

        if not (1 <= minutes <= 40320):
            await ctx.send_error("Invalid Duration", "Timeout duration must be between 1 minute and 28 days (40,320 mins).")
            return

        try:
            until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            await target.timeout(until, reason=f"{reason} (Executor: {author})")

            if self.bot.moderation_repo:
                await self.bot.moderation_repo.add_case(ModerationLog(
                    guild_id=ctx.guild.id,
                    case_id=0,
                    user_id=target.id,
                    moderator_id=author.id,
                    action="TIMEOUT",
                    reason=reason,
                    duration_seconds=minutes * 60,
                ))

            embed = EmbedBuilder.success(
                title=f"{KrovexEmoji.MODERATION} Member Timed Out",
                description=f"**{target}** was placed in timeout for **{minutes}m**.\n\n"
                            f"• **Expires:** <t:{int(until.timestamp())}:R>\n"
                            f"• **Reason:** {reason}\n"
                            f"• **Moderator:** {author.mention}",
            )
            await ctx.reply(embed=embed)
        except Exception as e:
            await ctx.send_error("Timeout Failed", str(e))

    @commands.command(name="timeout", aliases=["mute"], help="Place a member in timeout for a set number of minutes.")
    @commands.has_permissions(moderate_members=True)
    async def timeout_prefix(self, ctx: commands.Context, member: discord.Member, minutes: int = 10, *, reason: str = "No reason provided") -> None:
        await self._execute_timeout(UnifiedContext.from_prefix(ctx), member, minutes, reason)

    @app_commands.command(name="timeout", description="Place a member in timeout for minutes.")
    @app_commands.describe(member="Target member", minutes="Duration in minutes (1 to 40,320)", reason="Reason for timeout")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout_slash(self, interaction: discord.Interaction, member: discord.Member, minutes: int = 10, reason: str = "No reason provided") -> None:
        await self._execute_timeout(UnifiedContext.from_interaction(interaction), member, minutes, reason)

    async def _execute_untimeout(self, ctx: UnifiedContext, target: discord.Member, reason: str) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        bot_member = ctx.guild.me
        if not bot_member.guild_permissions.moderate_members:
            await ctx.send_error("Missing Permission", "I need the **Timeout Members** permission.")
            return

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        if not author or (not author.guild_permissions.moderate_members and author.id != ctx.guild.owner_id):
            await ctx.send_error("Access Denied", "You need the **Timeout Members** permission.")
            return

        try:
            await target.timeout(None, reason=f"Untimeout: {reason} (Executor: {author})")

            if self.bot.moderation_repo:
                await self.bot.moderation_repo.add_case(ModerationLog(
                    guild_id=ctx.guild.id,
                    case_id=0,
                    user_id=target.id,
                    moderator_id=author.id,
                    action="UNTIMEOUT",
                    reason=reason,
                ))

            embed = EmbedBuilder.success(
                title=f"{KrovexEmoji.SUCCESS} Timeout Removed",
                description=f"Timeout for **{target}** was revoked.\n\n"
                            f"• **Reason:** {reason}\n"
                            f"• **Moderator:** {author.mention}",
            )
            await ctx.reply(embed=embed)
        except Exception as e:
            await ctx.send_error("Untimeout Failed", str(e))

    @commands.command(name="untimeout", aliases=["unmute"], help="Remove timeout from a member.")
    @commands.has_permissions(moderate_members=True)
    async def untimeout_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided") -> None:
        await self._execute_untimeout(UnifiedContext.from_prefix(ctx), member, reason)

    @app_commands.command(name="untimeout", description="Remove timeout from a member.")
    @app_commands.describe(member="Target member", reason="Reason for removing timeout")
    @app_commands.default_permissions(moderate_members=True)
    async def untimeout_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        await self._execute_untimeout(UnifiedContext.from_interaction(interaction), member, reason)

    # ═══════════════════════════════════════════════════════════════════════════
    #  4. WARN & WARNING HISTORY
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_warn(self, ctx: UnifiedContext, target: discord.Member, reason: str) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        if not author or (not author.guild_permissions.manage_messages and author.id != ctx.guild.owner_id):
            await ctx.send_error("Access Denied", "You need the **Manage Messages** permission.")
            return

        bot_member = ctx.guild.me
        err = self._check_hierarchy(author, bot_member, target)
        if err:
            await ctx.send_error("Hierarchy Error", err)
            return

        if not self.bot.moderation_repo:
            await ctx.send_error("Unavailable", "Moderation database service is offline.")
            return

        try:
            warn_id = await self.bot.moderation_repo.add_warning(ctx.guild.id, target.id, author.id, reason)
            all_warns = await self.bot.moderation_repo.get_warnings(ctx.guild.id, target.id)

            embed = EmbedBuilder.success(
                title=f"{KrovexEmoji.WARN} Formal Warning Issued",
                description=f"**{target}** was formally warned in **{ctx.guild.name}**.\n\n"
                            f"• **Warning ID:** `#{warn_id}`\n"
                            f"• **Reason:** {reason}\n"
                            f"• **Total Active Warnings:** `{len(all_warns)}`\n"
                            f"• **Moderator:** {author.mention}",
            )
            await ctx.reply(embed=embed)
        except Exception as e:
            await ctx.send_error("Warning Failed", str(e))

    @commands.command(name="warn", help="Issue a formal warning to a server member.")
    @commands.has_permissions(manage_messages=True)
    async def warn_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided") -> None:
        await self._execute_warn(UnifiedContext.from_prefix(ctx), member, reason)

    @app_commands.command(name="warn", description="Issue a formal warning to a member.")
    @app_commands.describe(member="Member to warn", reason="Reason for the warning")
    @app_commands.default_permissions(manage_messages=True)
    async def warn_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        await self._execute_warn(UnifiedContext.from_interaction(interaction), member, reason)

    async def _execute_warnings(self, ctx: UnifiedContext, target: discord.Member) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        if not self.bot.moderation_repo:
            await ctx.send_error("Unavailable", "Moderation database service is offline.")
            return

        warns = await self.bot.moderation_repo.get_warnings(ctx.guild.id, target.id)
        if not warns:
            embed = EmbedBuilder.base(
                title=f"📜 Moderation History • {target}",
                description=f"{target.mention} has a clean record with **0** active warnings.",
                color=0x2ECC71,
                thumbnail=target.display_avatar.url,
            )
            await ctx.reply(embed=embed)
            return

        lines = []
        for w in warns[:15]:
            mod = ctx.guild.get_member(w["moderator_id"])
            mod_name = mod.display_name if mod else f"ID {w['moderator_id']}"
            lines.append(f"• **Warn #{w['warn_id']}** by {mod_name}: *{w['reason']}* ({w['created_at'][:10]})")

        embed = EmbedBuilder.base(
            title=f"📜 Warning Records • {target} [{len(warns)}]",
            description="\n".join(lines),
            color=BRAND_COLOR,
            thumbnail=target.display_avatar.url,
        )
        embed.set_footer(text=f"User ID: {target.id} • KROVEX Moderation Archive")
        await ctx.reply(embed=embed)

    @commands.command(name="warnings", aliases=["warns", "modlogs"], help="View a member's warning history.")
    @commands.has_permissions(manage_messages=True)
    async def warnings_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        target = member or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if target:
            await self._execute_warnings(UnifiedContext.from_prefix(ctx), target)

    @app_commands.command(name="warnings", description="View a member's warning history.")
    @app_commands.describe(member="Target member to inspect")
    @app_commands.default_permissions(manage_messages=True)
    async def warnings_slash(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        target = member or (interaction.user if isinstance(interaction.user, discord.Member) else None)
        if target:
            await self._execute_warnings(UnifiedContext.from_interaction(interaction), target)

    async def _execute_clearwarns(self, ctx: UnifiedContext, target: discord.Member) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        if not author or (not author.guild_permissions.manage_guild and author.id != ctx.guild.owner_id):
            await ctx.send_error("Access Denied", "You need the **Manage Server** permission to clear warnings.")
            return

        if not self.bot.moderation_repo:
            await ctx.send_error("Unavailable", "Moderation database service is offline.")
            return

        count = await self.bot.moderation_repo.clear_warnings(ctx.guild.id, target.id)
        embed = EmbedBuilder.success(
            title=f"{KrovexEmoji.SUCCESS} Warnings Cleared",
            description=f"Cleared **{count}** warning records for {target.mention}.",
        )
        await ctx.reply(embed=embed)

    @commands.command(name="clearwarns", aliases=["clearwarnings"], help="Clear all warnings for a member.")
    @commands.has_permissions(manage_guild=True)
    async def clearwarns_prefix(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._execute_clearwarns(UnifiedContext.from_prefix(ctx), member)

    @app_commands.command(name="clearwarns", description="Clear all warnings for a member.")
    @app_commands.describe(member="Member whose warnings to clear")
    @app_commands.default_permissions(manage_guild=True)
    async def clearwarns_slash(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await self._execute_clearwarns(UnifiedContext.from_interaction(interaction), member)

    # ═══════════════════════════════════════════════════════════════════════════
    #  5. PURGE & BULK DELETE
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_purge(self, ctx: UnifiedContext, amount: int) -> None:
        if not ctx.guild or not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send_error("Invalid Context", "Purge can only be run in server text channels.")
            return

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        if not author or (not author.guild_permissions.manage_messages and author.id != ctx.guild.owner_id):
            await ctx.send_error("Access Denied", "You need the **Manage Messages** permission.")
            return

        bot_member = ctx.guild.me
        if not bot_member.guild_permissions.manage_messages:
            await ctx.send_error("Missing Permission", "I need the **Manage Messages** permission.")
            return

        if not (1 <= amount <= 100):
            await ctx.send_error("Invalid Range", "Purge amount must be between 1 and 100.")
            return

        try:
            deleted = await ctx.channel.purge(limit=amount)
            msg = await ctx.reply(f"{KrovexEmoji.SUCCESS} Successfully purged **{len(deleted)}** message(s).")
            # Auto-delete notification after 5s if prefix
            if isinstance(ctx._source, commands.Context):
                try:
                    await msg.delete(delay=5.0)
                except Exception:
                    pass
        except Exception as e:
            await ctx.send_error("Purge Failed", str(e))

    @commands.command(name="purge", aliases=["clean", "prune"], help="Bulk delete recent messages in the channel (1-100).")
    @commands.has_permissions(manage_messages=True)
    async def purge_prefix(self, ctx: commands.Context, amount: int = 10) -> None:
        await self._execute_purge(UnifiedContext.from_prefix(ctx), amount)

    @app_commands.command(name="purge", description="Bulk delete messages in the channel (1-100).")
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    @app_commands.default_permissions(manage_messages=True)
    async def purge_slash(self, interaction: discord.Interaction, amount: int = 10) -> None:
        await self._execute_purge(UnifiedContext.from_interaction(interaction), amount)

    # ═══════════════════════════════════════════════════════════════════════════
    #  6. TEXT CHANNEL LOCK & UNLOCK
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_lock(self, ctx: UnifiedContext, channel: Optional[discord.TextChannel] = None) -> None:
        target_ch = channel or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if not ctx.guild or not target_ch:
            await ctx.send_error("Error", "Must be run in a text channel.")
            return

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        if not author or (not author.guild_permissions.manage_channels and author.id != ctx.guild.owner_id):
            await ctx.send_error("Access Denied", "You need the **Manage Channels** permission.")
            return

        bot_member = ctx.guild.me
        if not bot_member.guild_permissions.manage_channels:
            await ctx.send_error("Missing Permission", "I need the **Manage Channels** permission.")
            return

        try:
            await target_ch.set_permissions(ctx.guild.default_role, send_messages=False, reason=f"Channel Lock by {author}")
            embed = EmbedBuilder.success(
                title="🔒 Channel Locked",
                description=f"{target_ch.mention} has been locked for `@everyone`.\nMembers cannot send messages until unlocked.",
            )
            await ctx.reply(embed=embed)
        except Exception as e:
            await ctx.send_error("Lock Failed", str(e))

    @commands.command(name="lock", help="Lock the current or target text channel.")
    @commands.has_permissions(manage_channels=True)
    async def lock_prefix(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_lock(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="lock", description="Lock text channel from member messages.")
    @app_commands.describe(channel="Target channel to lock")
    @app_commands.default_permissions(manage_channels=True)
    async def lock_slash(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_lock(UnifiedContext.from_interaction(interaction), channel)

    async def _execute_unlock(self, ctx: UnifiedContext, channel: Optional[discord.TextChannel] = None) -> None:
        target_ch = channel or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if not ctx.guild or not target_ch:
            await ctx.send_error("Error", "Must be run in a text channel.")
            return

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        if not author or (not author.guild_permissions.manage_channels and author.id != ctx.guild.owner_id):
            await ctx.send_error("Access Denied", "You need the **Manage Channels** permission.")
            return

        bot_member = ctx.guild.me
        if not bot_member.guild_permissions.manage_channels:
            await ctx.send_error("Missing Permission", "I need the **Manage Channels** permission.")
            return

        try:
            await target_ch.set_permissions(ctx.guild.default_role, send_messages=None, reason=f"Channel Unlock by {author}")
            embed = EmbedBuilder.success(
                title="🔓 Channel Unlocked",
                description=f"{target_ch.mention} has been unlocked for `@everyone`.",
            )
            await ctx.reply(embed=embed)
        except Exception as e:
            await ctx.send_error("Unlock Failed", str(e))

    @commands.command(name="unlock", help="Unlock a previously locked text channel.")
    @commands.has_permissions(manage_channels=True)
    async def unlock_prefix(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_unlock(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="unlock", description="Unlock a previously locked text channel.")
    @app_commands.describe(channel="Target channel to unlock")
    @app_commands.default_permissions(manage_channels=True)
    async def unlock_slash(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_unlock(UnifiedContext.from_interaction(interaction), channel)

    # ═══════════════════════════════════════════════════════════════════════════
    #  7. SLOWMODE (PRESERVED)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_slowmode(self, ctx: UnifiedContext, seconds: int) -> None:
        """Shared logic for setting channel slowmode."""
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send_error("Error", "Slowmode can only be configured in text channels.")
            return

        if not (0 <= seconds <= 21600):
            await ctx.send_error("Invalid Range", "Slowmode duration must be between 0 and 21,600 seconds (6 hours).")
            return

        try:
            await ctx.channel.edit(slowmode_delay=seconds, reason=f"Slowmode updated by {ctx.author}")
            if seconds == 0:
                await ctx.send_success("Slowmode Disabled", f"Slowmode has been removed from {ctx.channel.mention}.")
            else:
                await ctx.send_success("Slowmode Configured", f"Slowmode in {ctx.channel.mention} is now set to **{seconds}s**.")
        except discord.Forbidden:
            await ctx.send_error("Permission Missing", "I do not have `Manage Channels` permission.")
        except Exception as err:
            await ctx.send_error("Operation Failed", str(err))

    @commands.command(name="slowmode", aliases=["sm"], help="Set the current channel's message slowmode in seconds.")
    @commands.has_permissions(manage_channels=True)
    async def slowmode_prefix(self, ctx: commands.Context, seconds: int) -> None:
        await self._execute_slowmode(UnifiedContext.from_prefix(ctx), seconds)

    @app_commands.command(name="slowmode", description="Set text channel slowmode in seconds.")
    @app_commands.describe(seconds="Slowmode duration in seconds (0 to 21,600)")
    @app_commands.default_permissions(manage_channels=True)
    async def slowmode_slash(self, interaction: discord.Interaction, seconds: int) -> None:
        await self._execute_slowmode(UnifiedContext.from_interaction(interaction), seconds)


async def setup(bot: DeathBot) -> None:
    """Setup hook to register cog."""
    await bot.add_cog(Moderation(bot))
