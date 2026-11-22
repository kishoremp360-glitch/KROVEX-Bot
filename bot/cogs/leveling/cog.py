"""Comprehensive Leveling and XP Progression Cog with full Prefix and Slash parity."""
from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.leveling.card import render_rank_card
from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.leveling")
BRAND_COLOR = 0x9D4EDD


class LevelingCog(commands.GroupCog, group_name="level"):
    """Server leveling, message XP progression, rank cards, and role reward distribution."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot
        self._cooldowns: Dict[tuple[int, int], float] = {}  # (guild_id, user_id) -> timestamp
        super().__init__()

    # =========================================================
    # MESSAGE LISTENER FOR XP EARNING
    # =========================================================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listen to incoming messages to award XP based on guild settings."""
        if message.author.bot or not message.guild or not self.bot.level_repo:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        settings = await self.bot.level_repo.get_settings(guild_id)
        if not settings.get("enabled", True):
            return

        # Check exemptions
        member_role_ids = [r.id for r in message.author.roles] if isinstance(message.author, discord.Member) else []
        if await self.bot.level_repo.is_exempt(guild_id, message.channel.id, member_role_ids):
            return

        # Check cooldown
        cooldown_sec = settings.get("cooldown_seconds") or 60
        now = time.time()
        last_time = self._cooldowns.get((guild_id, user_id), 0.0)
        if now - last_time < cooldown_sec:
            return

        self._cooldowns[(guild_id, user_id)] = now

        # Calculate XP
        min_xp = settings.get("min_xp") or 15
        max_xp = settings.get("max_xp") or 25
        mult = settings.get("multiplier") or 1.0
        earned_xp = max(1, int(random.randint(min_xp, max_xp) * mult))

        new_xp, new_lvl, leveled_up = await self.bot.level_repo.add_xp(guild_id, user_id, earned_xp)

        if leveled_up:
            await self._handle_level_up(message, new_lvl, new_xp, settings)

    async def _handle_level_up(self, message: discord.Message, new_lvl: int, new_xp: int, settings: Dict[str, Any]) -> None:
        """Dispatch announcement and award configured role rewards."""
        guild = message.guild
        author = message.author
        if not guild or not isinstance(author, discord.Member):
            return

        # Determine target announcement channel
        target_ch = message.channel
        ann_ch_id = settings.get("channel_id")
        if ann_ch_id:
            custom_ch = guild.get_channel(ann_ch_id)
            if isinstance(custom_ch, discord.TextChannel):
                target_ch = custom_ch

        tmpl = settings.get("message_template") or f"{KrovexEmoji.TADA} Congratulations {{user}}, you leveled up to **Level {{level}}**!"
        content = tmpl.replace("{user}", author.mention).replace("{level}", str(new_lvl)).replace("{xp}", str(new_xp))

        try:
            lvl_badge = KrovexEmoji.SCORE_100 if new_lvl >= 100 else (KrovexEmoji.RAINBOW_STAR if new_lvl >= 50 else KrovexEmoji.LIGHTNING)
            embed = EmbedBuilder.success(title=f"{lvl_badge} Level Up!", description=content)
            await target_ch.send(embed=embed)
        except Exception as e:
            logger.warning("Could not send level up message: %s", e)

        # Award role rewards
        rewards = await self.bot.level_repo.get_rewards(guild.id)
        for r in rewards:
            if r["level"] == new_lvl:
                reward_role = guild.get_role(r["role_id"])
                if reward_role and guild.me.guild_permissions.manage_roles:
                    if guild.me.top_role.position > reward_role.position:
                        try:
                            await author.add_roles(reward_role, reason=f"Level {new_lvl} reward unlocked")
                            await target_ch.send(f"🎁 **{author.display_name}** unlocked the {reward_role.mention} role!")
                        except Exception as e:
                            logger.error("Failed to assign level reward role: %s", e)

    # =========================================================
    # CORE SHARED BUSINESS LOGIC
    # =========================================================

    async def _is_level_manager(self, ctx: UnifiedContext) -> bool:
        """Allow configured bot owners and server administrators to manage leveling."""
        if not ctx.guild:
            return False

        if ctx.author.id in self.bot.config.owner_ids:
            return True

        if await self.bot.is_owner(ctx.author):
            return True

        return bool(ctx.author.guild_permissions.administrator)

    async def _execute_rank(self, ctx: UnifiedContext, member: Optional[discord.Member] = None) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        target = member or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if not target:
            await ctx.send_error("Error", "Could not resolve member instance.")
            return

        data = await self.bot.level_repo.get_member(ctx.guild.id, target.id)
        rank = await self.bot.level_repo.get_rank(ctx.guild.id, target.id)

        # Look for next role reward
        rewards = await self.bot.level_repo.get_rewards(ctx.guild.id)
        next_role = None
        for r in rewards:
            if r["level"] > (data.get("level") or 0):
                next_role = ctx.guild.get_role(r["role_id"])
                break

        embed = render_rank_card(target, data, rank, next_role)
        await ctx.reply(embed=embed)

    async def _execute_leaderboard(self, ctx: UnifiedContext, page: int = 1) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if page < 1:
            page = 1

        limit = 10
        offset = (page - 1) * limit
        entries = await self.bot.level_repo.get_leaderboard(ctx.guild.id, limit=limit, offset=offset)

        if not entries and page > 1:
            await ctx.send_error("No Entries", f"No members found on page {page}.")
            return

        lines = []
        for i, row in enumerate(entries, start=offset + 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`#{i}`"
            user_mention = f"<@{row['user_id']}>"
            lines.append(f"{medal} {user_mention} — **Level {row['level']}** (`{row['xp']:,}` XP) • `{row['messages_count']:,}` msgs")

        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.LEADERBOARD} Server XP Leaderboard • Page {page}",
            description="\n".join(lines) if lines else "No XP recorded in this server yet! Start chatting to earn XP.",
            color=BRAND_COLOR,
        )
        embed.set_footer(text=f"{ctx.guild.name} • Leveling Leaderboard", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        await ctx.reply(embed=embed)

    async def _execute_setup(self, ctx: UnifiedContext, channel: Optional[discord.TextChannel] = None, min_xp: int = 15, max_xp: int = 25, cooldown: int = 60) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        ch_id = channel.id if channel else None
        await self.bot.level_repo.update_settings(
            ctx.guild.id,
            channel_id=ch_id,
            min_xp=min_xp,
            max_xp=max_xp,
            cooldown_seconds=cooldown,
            enabled=True,
        )
        embed = EmbedBuilder.success(
            title=f"{KrovexEmoji.RAINBOW_STAR} Leveling System Configured",
            description=(
                f"**Status:** `Enabled`\n"
                f"**Announcement Channel:** {channel.mention if channel else '`Current Message Channel`'}\n"
                f"**XP Range:** `{min_xp} – {max_xp}` XP per message\n"
                f"**Cooldown:** `{cooldown}s` between messages"
            ),
        )
        await ctx.reply(embed=embed)

    async def _execute_toggle(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        s = await self.bot.level_repo.get_settings(ctx.guild.id)
        new_state = not s.get("enabled", True)
        await self.bot.level_repo.update_settings(ctx.guild.id, enabled=new_state)
        status_text = "Enabled" if new_state else "Disabled"
        await ctx.send_success("Leveling Toggled", f"Leveling system is now **{status_text}** for this server.")

    async def _execute_channel(self, ctx: UnifiedContext, channel: Optional[discord.TextChannel] = None) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        ch_id = channel.id if channel else None
        await self.bot.level_repo.update_settings(ctx.guild.id, channel_id=ch_id)
        if channel:
            await ctx.send_success("Announcement Channel Set", f"Level up notices will now be sent to {channel.mention}.")
        else:
            await ctx.send_success("Announcement Channel Reset", "Level up notices will now be sent in the active conversation channel.")

    async def _execute_message(self, ctx: UnifiedContext, template: str) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        await self.bot.level_repo.update_settings(ctx.guild.id, message_template=template)
        await ctx.send_success("Level Message Template Saved", f"Template updated to:\n> {template}")

    async def _execute_reward(self, ctx: UnifiedContext, level: int, role: discord.Role) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if level < 1:
            await ctx.send_error("Invalid Level", "Level must be 1 or higher.")
            return

        await self.bot.level_repo.add_reward(ctx.guild.id, level, role.id)
        await ctx.send_success("Role Reward Added", f"Members reaching **Level {level}** will now unlock {role.mention}!")

    async def _execute_rewards(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        rewards = await self.bot.level_repo.get_rewards(ctx.guild.id)
        if not rewards:
            await ctx.reply("ℹ️ No role rewards configured for this server. Use `levelreward <level> <@role>` to add one.")
            return

        lines = []
        for r in rewards:
            role = ctx.guild.get_role(r["role_id"])
            role_str = role.mention if role else f"`[Deleted Role: {r['role_id']}]`"
            lines.append(f"• **Level {r['level']}:** {role_str}")

        embed = EmbedBuilder.base(
            title=f"🎁 Level Role Rewards • {ctx.guild.name}",
            description="\n".join(lines),
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    async def _execute_remove_reward(self, ctx: UnifiedContext, level: int) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        ok = await self.bot.level_repo.remove_reward(ctx.guild.id, level)
        if ok:
            await ctx.send_success("Reward Removed", f"Removed reward for Level {level}.")
        else:
            await ctx.send_error("Not Found", f"No reward was configured for Level {level}.")

    async def _execute_xpadd(self, ctx: UnifiedContext, member: discord.Member, amount: int) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if amount <= 0:
            await ctx.send_error("Invalid Amount", "Amount must be greater than zero.")
            return

        new_xp, new_lvl, _ = await self.bot.level_repo.add_xp(ctx.guild.id, member.id, amount)
        await ctx.send_success("XP Added", f"Added **+{amount:,}** XP to {member.mention}. (New Total: `{new_xp:,}` XP | Level `{new_lvl}`)")

    async def _execute_xpset(self, ctx: UnifiedContext, member: discord.Member, xp: int) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if xp < 0:
            await ctx.send_error("Invalid XP", "XP cannot be negative.")
            return

        await self.bot.level_repo.set_xp(ctx.guild.id, member.id, xp)
        await ctx.send_success("XP Set", f"Set XP for {member.mention} to **{xp:,}** XP.")

    async def _execute_xpremove(self, ctx: UnifiedContext, member: discord.Member, amount: int) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if amount <= 0:
            await ctx.send_error("Invalid Amount", "Amount must be greater than zero.")
            return

        new_xp, new_lvl = await self.bot.level_repo.remove_xp(ctx.guild.id, member.id, amount)
        await ctx.send_success("XP Removed", f"Deducted **-{amount:,}** XP from {member.mention}. (Remaining: `{new_xp:,}` XP | Level `{new_lvl}`)")

    async def _execute_xpreset(self, ctx: UnifiedContext, member: discord.Member) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        await self.bot.level_repo.reset_member(ctx.guild.id, member.id)
        await ctx.send_success("Member Reset", f"Reset all leveling progress and XP for {member.mention}.")

    async def _execute_levelreset(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        count = await self.bot.level_repo.reset_guild(ctx.guild.id)
        await ctx.send_success("Server XP Reset", f"Wiped all XP records for `{count}` members in this server.")

    async def _execute_cooldown(self, ctx: UnifiedContext, seconds: int) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if seconds < 5 or seconds > 600:
            await ctx.send_error("Invalid Cooldown", "Cooldown must be between 5 and 600 seconds.")
            return

        await self.bot.level_repo.update_settings(ctx.guild.id, cooldown_seconds=seconds)
        await ctx.send_success("Cooldown Updated", f"XP cooldown set to `{seconds}s` per message.")

    async def _execute_range(self, ctx: UnifiedContext, min_xp: int, max_xp: int) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if min_xp < 1 or max_xp < min_xp or max_xp > 1000:
            await ctx.send_error("Invalid Range", "Provide valid min/max XP (1 to 1000).")
            return

        await self.bot.level_repo.update_settings(ctx.guild.id, min_xp=min_xp, max_xp=max_xp)
        await ctx.send_success("XP Range Saved", f"XP per message set to `{min_xp} – {max_xp}` XP.")

    async def _execute_multiplier(self, ctx: UnifiedContext, multiplier: float) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if multiplier < 0.1 or multiplier > 10.0:
            await ctx.send_error("Invalid Multiplier", "Multiplier must be between 0.1 and 10.0.")
            return

        await self.bot.level_repo.update_settings(ctx.guild.id, multiplier=multiplier)
        await ctx.send_success("Multiplier Updated", f"Global XP multiplier set to `{multiplier}x`.")

    async def _execute_exclude(self, ctx: UnifiedContext, action: str, target: discord.abc.GuildChannel | discord.Role) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        if not await self._is_level_manager(ctx):
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        target_type = "channel" if isinstance(target, discord.abc.GuildChannel) else "role"
        if action.lower() == "add":
            await self.bot.level_repo.add_exemption(ctx.guild.id, target.id, target_type)
            await ctx.send_success("Exclusion Added", f"Excluded {target.mention} from gaining message XP.")
        else:
            await self.bot.level_repo.remove_exemption(ctx.guild.id, target.id, target_type)
            await ctx.send_success("Exclusion Removed", f"Removed exclusion on {target.mention}.")

    async def _execute_stats(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.level_repo:
            return
        stats = await self.bot.level_repo.get_guild_stats(ctx.guild.id)
        embed = EmbedBuilder.base(
            title=f"📈 Leveling Overview • {ctx.guild.name}",
            color=BRAND_COLOR,
        )
        embed.add_field(name="Active Members", value=f"`{stats['total_users']:,}`", inline=True)
        embed.add_field(name="Highest Level", value=f"⭐ `{stats['highest_level']}`", inline=True)
        embed.add_field(name="Total Messages Tracked", value=f"`{stats['total_msgs'] or 0:,}`", inline=True)
        embed.add_field(name="Circulating XP", value=f"✨ `{stats['total_xp'] or 0:,}` XP", inline=True)
        await ctx.reply(embed=embed)

    # =========================================================
    # SLASH COMMAND GROUP: /level <subcommand> (19 subcommands)
    # =========================================================

    @app_commands.command(name="rank", description="Check member XP, current level, and rank card.")
    @app_commands.describe(member="Member to view (defaults to yourself)")
    async def slash_rank(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        await self._execute_rank(UnifiedContext.from_interaction(interaction), member)

    @app_commands.command(name="leaderboard", description="View the server top XP leaderboard.")
    @app_commands.describe(page="Leaderboard page number (default 1)")
    async def slash_leaderboard(self, interaction: discord.Interaction, page: int = 1) -> None:
        await self._execute_leaderboard(UnifiedContext.from_interaction(interaction), page)

    @app_commands.command(name="setup", description="Configure leveling announcement channel, XP rate, and cooldown.")
    @app_commands.describe(channel="Level up announcement channel", min_xp="Minimum XP", max_xp="Maximum XP", cooldown="Cooldown in seconds")
    async def slash_setup(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None, min_xp: int = 15, max_xp: int = 25, cooldown: int = 60) -> None:
        await self._execute_setup(UnifiedContext.from_interaction(interaction), channel, min_xp, max_xp, cooldown)

    @app_commands.command(name="toggle", description="Enable or disable the leveling engine in this server.")
    async def slash_toggle(self, interaction: discord.Interaction) -> None:
        await self._execute_toggle(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="channel", description="Set or reset the level up announcement channel.")
    @app_commands.describe(channel="Target channel (leave blank to announce in current channel)")
    async def slash_channel(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_channel(UnifiedContext.from_interaction(interaction), channel)

    @app_commands.command(name="message", description="Customize the level up congratulatory template.")
    @app_commands.describe(template="Message template using {user}, {level}, {xp}")
    async def slash_message(self, interaction: discord.Interaction, template: str) -> None:
        await self._execute_message(UnifiedContext.from_interaction(interaction), template)

    @app_commands.command(name="reward", description="Add a role reward unlocked at a specific level.")
    @app_commands.describe(level="Level required", role="Role to reward")
    async def slash_reward(self, interaction: discord.Interaction, level: int, role: discord.Role) -> None:
        await self._execute_reward(UnifiedContext.from_interaction(interaction), level, role)

    @app_commands.command(name="rewards", description="List all configured level role rewards.")
    async def slash_rewards(self, interaction: discord.Interaction) -> None:
        await self._execute_rewards(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="removereward", description="Remove a level role reward.")
    @app_commands.describe(level="Level of reward to remove")
    async def slash_removereward(self, interaction: discord.Interaction, level: int) -> None:
        await self._execute_remove_reward(UnifiedContext.from_interaction(interaction), level)

    @app_commands.command(name="xpadd", description="Add XP to a member.")
    @app_commands.describe(member="Member receiving XP", amount="Amount of XP to add")
    async def slash_xpadd(self, interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        await self._execute_xpadd(UnifiedContext.from_interaction(interaction), member, amount)

    @app_commands.command(name="xpset", description="Set exact XP for a member.")
    @app_commands.describe(member="Target member", xp="XP amount")
    async def slash_xpset(self, interaction: discord.Interaction, member: discord.Member, xp: int) -> None:
        await self._execute_xpset(UnifiedContext.from_interaction(interaction), member, xp)

    @app_commands.command(name="xpremove", description="Deduct XP from a member.")
    @app_commands.describe(member="Target member", amount="Amount to deduct")
    async def slash_xpremove(self, interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        await self._execute_xpremove(UnifiedContext.from_interaction(interaction), member, amount)

    @app_commands.command(name="xpreset", description="Reset a member's XP and level back to zero.")
    @app_commands.describe(member="Target member")
    async def slash_xpreset(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await self._execute_xpreset(UnifiedContext.from_interaction(interaction), member)

    @app_commands.command(name="reset", description="Wipe all leveling progress for the entire server.")
    async def slash_levelreset(self, interaction: discord.Interaction) -> None:
        await self._execute_levelreset(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="cooldown", description="Configure message XP cooldown duration.")
    @app_commands.describe(seconds="Cooldown in seconds (5-600)")
    async def slash_cooldown(self, interaction: discord.Interaction, seconds: int) -> None:
        await self._execute_cooldown(UnifiedContext.from_interaction(interaction), seconds)

    @app_commands.command(name="range", description="Configure randomized XP earned per message.")
    @app_commands.describe(min_xp="Minimum XP", max_xp="Maximum XP")
    async def slash_range(self, interaction: discord.Interaction, min_xp: int, max_xp: int) -> None:
        await self._execute_range(UnifiedContext.from_interaction(interaction), min_xp, max_xp)

    @app_commands.command(name="multiplier", description="Configure global XP multiplier.")
    @app_commands.describe(multiplier="Multiplier (e.g. 1.5, 2.0)")
    async def slash_multiplier(self, interaction: discord.Interaction, multiplier: float) -> None:
        await self._execute_multiplier(UnifiedContext.from_interaction(interaction), multiplier)

    @app_commands.command(name="exclude", description="Exclude a channel or role from earning XP.")
    @app_commands.describe(action="add or remove", target_role="Optional role to exclude", target_channel="Optional channel to exclude")
    async def slash_exclude(self, interaction: discord.Interaction, action: str, target_role: Optional[discord.Role] = None, target_channel: Optional[discord.TextChannel] = None) -> None:
        target = target_role or target_channel
        if not target:
            await interaction.response.send_message("❌ Specify a role or channel to exclude.", ephemeral=True)
            return
        await self._execute_exclude(UnifiedContext.from_interaction(interaction), action, target)

    @app_commands.command(name="stats", description="View server-wide leveling statistics and message counts.")
    async def slash_stats(self, interaction: discord.Interaction) -> None:
        await self._execute_stats(UnifiedContext.from_interaction(interaction))

    # =========================================================
    # PREFIX COMMANDS (19 commands)
    # =========================================================

    @commands.command(name="rank", aliases=["level"], help="View rank card and XP progress.")
    async def prefix_rank(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_rank(UnifiedContext.from_prefix(ctx), member)

    @commands.command(name="leaderboard", aliases=["levels", "topxp"], help="View server XP leaderboard.")
    async def prefix_leaderboard(self, ctx: commands.Context, page: int = 1) -> None:
        await self._execute_leaderboard(UnifiedContext.from_prefix(ctx), page)

    @commands.command(name="levelsetup", help="Configure server leveling system.")
    @commands.has_permissions(administrator=True)
    async def prefix_levelsetup(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None, min_xp: int = 15, max_xp: int = 25, cooldown: int = 60) -> None:
        await self._execute_setup(UnifiedContext.from_prefix(ctx), channel, min_xp, max_xp, cooldown)

    @commands.command(name="leveltoggle", help="Toggle leveling system on or off.")
    @commands.has_permissions(administrator=True)
    async def prefix_leveltoggle(self, ctx: commands.Context) -> None:
        await self._execute_toggle(UnifiedContext.from_prefix(ctx))

    @commands.command(name="levelchannel", help="Set level up notice channel.")
    @commands.has_permissions(administrator=True)
    async def prefix_levelchannel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_channel(UnifiedContext.from_prefix(ctx), channel)

    @commands.command(name="levelmessage", help="Set level up template message.")
    @commands.has_permissions(administrator=True)
    async def prefix_levelmessage(self, ctx: commands.Context, *, template: str) -> None:
        await self._execute_message(UnifiedContext.from_prefix(ctx), template)

    @commands.command(name="levelreward", help="Add a role reward unlocked at a specific level.")
    @commands.has_permissions(administrator=True)
    async def prefix_levelreward(self, ctx: commands.Context, level: int, role: discord.Role) -> None:
        await self._execute_reward(UnifiedContext.from_prefix(ctx), level, role)

    @commands.command(name="levelrewards", help="List all configured level role rewards.")
    async def prefix_levelrewards(self, ctx: commands.Context) -> None:
        await self._execute_rewards(UnifiedContext.from_prefix(ctx))

    @commands.command(name="levelremovereward", help="Remove a role reward for a level.")
    @commands.has_permissions(administrator=True)
    async def prefix_levelremovereward(self, ctx: commands.Context, level: int) -> None:
        await self._execute_remove_reward(UnifiedContext.from_prefix(ctx), level)

    @commands.command(name="xpadd", help="Add XP to a member.")
    @commands.has_permissions(administrator=True)
    async def prefix_xpadd(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        await self._execute_xpadd(UnifiedContext.from_prefix(ctx), member, amount)

    @commands.command(name="xpset", help="Set member's XP directly.")
    @commands.has_permissions(administrator=True)
    async def prefix_xpset(self, ctx: commands.Context, member: discord.Member, xp: int) -> None:
        await self._execute_xpset(UnifiedContext.from_prefix(ctx), member, xp)

    @commands.command(name="xpremove", help="Deduct XP from a member.")
    @commands.has_permissions(administrator=True)
    async def prefix_xpremove(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        await self._execute_xpremove(UnifiedContext.from_prefix(ctx), member, amount)

    @commands.command(name="xpreset", help="Reset a member's XP back to zero.")
    @commands.has_permissions(administrator=True)
    async def prefix_xpreset(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._execute_xpreset(UnifiedContext.from_prefix(ctx), member)

    @commands.command(name="levelreset", help="Reset all XP in the server.")
    @commands.has_permissions(administrator=True)
    async def prefix_levelreset(self, ctx: commands.Context) -> None:
        await self._execute_levelreset(UnifiedContext.from_prefix(ctx))

    @commands.command(name="xpcooldown", help="Set cooldown between XP gains.")
    @commands.has_permissions(administrator=True)
    async def prefix_xpcooldown(self, ctx: commands.Context, seconds: int) -> None:
        await self._execute_cooldown(UnifiedContext.from_prefix(ctx), seconds)

    @commands.command(name="xprange", help="Set min and max XP earned per message.")
    @commands.has_permissions(administrator=True)
    async def prefix_xprange(self, ctx: commands.Context, min_xp: int, max_xp: int) -> None:
        await self._execute_range(UnifiedContext.from_prefix(ctx), min_xp, max_xp)

    @commands.command(name="xpmultiplier", help="Set server-wide XP multiplier.")
    @commands.has_permissions(administrator=True)
    async def prefix_xpmultiplier(self, ctx: commands.Context, multiplier: float) -> None:
        await self._execute_multiplier(UnifiedContext.from_prefix(ctx), multiplier)

    @commands.command(name="xpexclude", help="Exclude a role or channel from XP gains.")
    @commands.has_permissions(administrator=True)
    async def prefix_xpexclude(self, ctx: commands.Context, action: str, target: discord.abc.GuildChannel | discord.Role) -> None:
        await self._execute_exclude(UnifiedContext.from_prefix(ctx), action, target)

    @commands.command(name="levelstats", help="View server leveling stats.")
    async def prefix_levelstats(self, ctx: commands.Context) -> None:
        await self._execute_stats(UnifiedContext.from_prefix(ctx))


async def setup(bot: DeathBot) -> None:
    """Setup hook to register LevelingCog."""
    await bot.add_cog(LevelingCog(bot))

