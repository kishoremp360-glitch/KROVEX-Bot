"""Advanced Event Logging Service for Death Bot.

Monitors gateway events and emits structured audit cards to designated log channels.
Never logs bot tokens, passwords, or credentials.
Supports Voice, Status/Presence, Invites, Messages, Members, Roles, Channels, and Server logs.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union

import discord
from discord.ext import commands

from bot.utils.embeds import EmbedBuilder
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.services.logging")
BRAND_COLOR = 0x9D4EDD

TOKEN_REGEX = re.compile(r"[a-zA-Z0-9_-]{23,28}\.[a-zA-Z0-9_-]{6,7}\.[a-zA-Z0-9_-]{27,}")


def _sanitize(text: str) -> str:
    """Mask potential bot tokens or credentials from message logs."""
    if not text:
        return ""
    return TOKEN_REGEX.sub("[REDACTED_TOKEN]", text)


def _format_time_ago(dt: Optional[datetime]) -> str:
    """Format duration into natural phrases like '5 days, 1 hour and 39 minutes'."""
    if dt is None:
        return "Unknown"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    total_seconds = max(0, int(diff.total_seconds()))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)

    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if not parts or (len(parts) < 2 and seconds > 0):
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")

    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    else:
        return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _get_ordinal(n: int) -> str:
    """Convert number to ordinal string (1st, 2nd, 3rd, 5th, etc.)."""
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


class LoggingService(commands.Cog):
    """Event listener service dispatching audit logs to configured channels."""

    def __init__(self, bot: "DeathBot") -> None:
        self.bot = bot
        self._status_cooldowns: Dict[int, float] = {}  # user_id -> last_log_timestamp
        self._invite_cache: Dict[int, Dict[str, int]] = {}  # guild_id -> {invite_code: uses}
        self._recent_events: Dict[str, float] = {}  # event_dedup_key -> timestamp

    def _is_duplicate_event(self, key: str, window: float = 3.0) -> bool:
        """Check and record event key in sliding deduplication window to suppress spam."""
        now = time.time()
        if len(self._recent_events) > 1000:
            self._recent_events = {k: ts for k, ts in self._recent_events.items() if now - ts < 60.0}

        last_ts = self._recent_events.get(key, 0.0)
        if now - last_ts < window:
            return True
        self._recent_events[key] = now
        return False

    async def _format_user(
        self,
        user_or_id: Any,
        guild: Optional[discord.Guild] = None,
    ) -> Tuple[str, str]:
        """
        Resolve user display name according to priority:
        1. Server nickname (member.display_name)
        2. Global display name (user.global_name)
        3. Username (user.name)
        Fallback: ('Unknown User', '@unknown')
        Returns: (display_name, handle)
        """
        member: Optional[discord.Member] = None
        user: Optional[Union[discord.User, discord.Member]] = None

        if isinstance(user_or_id, discord.Member):
            member = user_or_id
            user = user_or_id
        elif isinstance(user_or_id, discord.User):
            user = user_or_id
            if guild:
                member = guild.get_member(user.id)
        elif isinstance(user_or_id, int):
            if guild:
                member = guild.get_member(user_or_id)
            if not member and hasattr(self.bot, "get_user"):
                user = self.bot.get_user(user_or_id)
                if not user and hasattr(self.bot, "fetch_user"):
                    try:
                        user = await self.bot.fetch_user(user_or_id)
                    except Exception:
                        user = None
        else:
            return "Unknown User", "@unknown"

        display_name: str = "Unknown User"
        handle: str = "@unknown"

        if member:
            display_name = member.display_name
            handle = f"@{member.name}"
        elif user:
            display_name = getattr(user, "global_name", None) or user.name
            handle = f"@{user.name}"

        return display_name, handle

    async def _is_channel_ignored(self, guild: discord.Guild, channel: Optional[discord.abc.GuildChannel]) -> bool:
        """Check if channel is an active audit log channel or matches an ignore filter."""
        if not channel or not hasattr(self.bot, "logging_repo") or not self.bot.logging_repo:
            return False

        # 1. Protect all active log channels from self-logging loops
        try:
            settings = await self.bot.logging_repo.get_settings(guild.id)
            log_channels = {
                settings.get("mod_log_channel"),
                settings.get("message_log_channel"),
                settings.get("member_log_channel"),
                settings.get("server_log_channel"),
                settings.get("voice_log_channel"),
                settings.get("status_log_channel"),
                settings.get("invite_log_channel"),
            }
            if channel.id in log_channels:
                return True
        except Exception:
            pass

        # 2. Check explicit database filters
        try:
            filters = await self.bot.logging_repo.get_filters(guild.id)
            ignored_ids = {int(f["target"]) for f in filters if f.get("filter_type") == "channel" and str(f.get("target", "")).isdigit()}
            if channel.id in ignored_ids:
                return True
        except Exception:
            pass

        return False

    async def _get_channel(self, guild: discord.Guild, category: str) -> Optional[discord.TextChannel]:
        """Resolve destination text channel for an event category."""
        if not hasattr(self.bot, "logging_repo") or not self.bot.logging_repo:
            return None
        settings = await self.bot.logging_repo.get_settings(guild.id)
        field_map = {
            "messages": "message_log_channel",
            "members": "member_log_channel",
            "voice": "voice_log_channel",
            "server": "server_log_channel",
            "mod": "mod_log_channel",
            "status": "status_log_channel",
            "invites": "invite_log_channel",
        }
        col = field_map.get(category, "server_log_channel")
        ch_id = (
            settings.get(col)
            or settings.get("server_log_channel")
            or settings.get("mod_log_channel")
        )
        if ch_id:
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                return ch
        return None

    async def _is_event_enabled(self, guild_id: int, event_name: str) -> bool:
        if hasattr(self.bot, "logging_repo") and self.bot.logging_repo:
            if not await self.bot.logging_repo.is_logging_enabled(guild_id):
                return False
            return await self.bot.logging_repo.is_event_enabled(guild_id, event_name)
        return True

    async def _emit_log(
        self,
        guild: discord.Guild,
        category: str,
        event_name: str,
        embed: discord.Embed,
        details: str,
        actor_id: Optional[int] = None,
        target_id: Optional[int] = None,
    ) -> None:
        """Helper to send log embed and record to database."""
        if not await self._is_event_enabled(guild.id, event_name):
            return

        # Ensure consistent KROVEX Audit Vault footer identity
        if embed:
            if not embed.footer or not embed.footer.text:
                embed.set_footer(text="KROVEX AUDIT VAULT • LOGGING ENGINE")
            elif "KROVEX" not in embed.footer.text:
                embed.set_footer(text=f"{embed.footer.text} • KROVEX AUDIT VAULT")

        ch = await self._get_channel(guild, category)
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass
        if hasattr(self.bot, "logging_repo") and self.bot.logging_repo:
            await self.bot.logging_repo.log_event(guild.id, event_name, details, actor_id, target_id)

    async def _cache_guild_invites(self, guild: discord.Guild) -> None:
        """Cache guild invites for invite tracking."""
        try:
            if guild.me.guild_permissions.manage_guild:
                invites = await guild.invites()
                self._invite_cache[guild.id] = {inv.code: (inv.uses or 0) for inv in invites}
        except Exception:
            pass

    # ── 1. Message Events ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        if await self._is_channel_ignored(message.guild, message.channel):
            return
        if self._is_duplicate_event(f"msg_delete:{message.id}", window=2.0):
            return

        disp_name, handle = await self._format_user(message.author, message.guild)
        content = _sanitize(message.content or "*No text content*")
        embed = discord.Embed(
            title="🗑️ Message Deleted",
            description=(
                f"**User:** {disp_name}\n"
                f"**Username:** {handle}\n"
                f"**Channel:** {message.channel.mention}\n\n"
                f"**Content:**\n{content[:1800]}"
            ),
            color=0xFF4444,
            timestamp=datetime.now(timezone.utc),
        )
        await self._emit_log(message.guild, "messages", "msg_delete", embed, f"Deleted message by {message.author.id} in {message.channel.id}", actor_id=message.author.id)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if not before.guild or before.author.bot or before.content == after.content:
            return
        if await self._is_channel_ignored(before.guild, before.channel):
            return
        if self._is_duplicate_event(f"msg_edit:{after.id}:{hash(after.content)}", window=2.0):
            return

        disp_name, handle = await self._format_user(before.author, before.guild)
        old_c = _sanitize(before.content or "*Empty*")
        new_c = _sanitize(after.content or "*Empty*")
        embed = discord.Embed(
            title="✏️ Message Edited",
            description=(
                f"**User:** {disp_name}\n"
                f"**Username:** {handle}\n"
                f"**Channel:** {before.channel.mention}\n"
                f"[Jump to Message]({after.jump_url})"
            ),
            color=0xFFA500,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Before", value=old_c[:1000], inline=False)
        embed.add_field(name="After", value=new_c[:1000], inline=False)
        await self._emit_log(before.guild, "messages", "msg_edit", embed, f"Edited message by {before.author.id}", actor_id=before.author.id)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: List[discord.Message]) -> None:
        if not messages:
            return
        guild = messages[0].guild
        if not guild:
            return
        channel = messages[0].channel
        if await self._is_channel_ignored(guild, channel):
            return
        if self._is_duplicate_event(f"bulk_delete:{channel.id}:{len(messages)}", window=3.0):
            return

        embed = discord.Embed(
            title="💥 Bulk Message Deletion",
            description=f"**Channel:** {channel.mention}\n**Count:** **{len(messages)}** messages purged.",
            color=0xFF2222,
            timestamp=datetime.now(timezone.utc),
        )
        await self._emit_log(guild, "messages", "bulk_delete", embed, f"Purged {len(messages)} messages in {channel.id}")

    # ── 2. Member Events & Invite Tracking ─────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        if self._is_duplicate_event(f"member_join:{guild.id}:{member.id}", window=3.0):
            return

        age = datetime.now(timezone.utc) - member.created_at
        disp_name, handle = await self._format_user(member, guild)

        # Check invites
        used_invite: Optional[discord.Invite] = None
        try:
            cached = self._invite_cache.get(guild.id, {})
            current_invites = await guild.invites() if guild.me.guild_permissions.manage_guild else []

            for inv in current_invites:
                prev_uses = cached.get(inv.code, 0)
                if (inv.uses or 0) > prev_uses:
                    used_invite = inv
                    break

            self._invite_cache[guild.id] = {inv.code: (inv.uses or 0) for inv in current_invites}
        except Exception:
            pass

        ordinal_str = _get_ordinal(guild.member_count or len(guild.members))
        created_ago = _format_time_ago(member.created_at)

        embed = discord.Embed(
            title="Member joined",
            description=f"{member.mention} {ordinal_str} to join\ncreated {created_ago} ago",
            color=0x57F287,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=f"{member.name}#{member.discriminator}" if member.discriminator != "0" else member.name, icon_url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id}")

        if used_invite:
            inviter_name, inviter_handle = await self._format_user(used_invite.inviter, guild)
            embed.add_field(name="Invite Code", value=f"`{used_invite.code}`", inline=True)
            embed.add_field(name="Invited By", value=f"{inviter_name} ({inviter_handle})", inline=True)
            embed.add_field(name="Total Uses", value=f"`{used_invite.uses}`", inline=True)

        await self._emit_log(
            guild,
            "members",
            "member_join",
            embed,
            f"Member join: {member.id}" + (f" via {used_invite.code}" if used_invite else ""),
            actor_id=used_invite.inviter.id if (used_invite and used_invite.inviter) else None,
            target_id=member.id
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        guild = member.guild
        if self._is_duplicate_event(f"member_leave:{guild.id}:{member.id}", window=3.0):
            return

        joined_ago = _format_time_ago(member.joined_at) if member.joined_at else "Unknown"
        roles = [r.name for r in member.roles if not r.is_default()]
        roles_str = ", ".join(roles) if roles else ""

        desc = f"{member.mention} joined {joined_ago} ago\nRoles: {roles_str}"
        embed = discord.Embed(
            title="Member left",
            description=desc,
            color=0xFEE75C,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=f"{member.name}#{member.discriminator}" if member.discriminator != "0" else member.name, icon_url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id}")

        await self._emit_log(guild, "members", "member_leave", embed, f"Member left: {member.id}", target_id=member.id)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        guild = before.guild

        # Nickname change
        if before.nick != after.nick:
            disp_name, handle = await self._format_user(after, guild)
            embed = discord.Embed(
                title="🏷️ Nickname Changed",
                description=(
                    f"**User:** {disp_name}\n"
                    f"**Username:** {handle}\n"
                    f"**Before:** {before.nick or '*None*'}\n"
                    f"**After:** {after.nick or '*None*'}"
                ),
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            await self._emit_log(guild, "members", "nick_change", embed, f"Nick changed: {before.nick} -> {after.nick}", target_id=after.id)

        # Role change
        if before.roles != after.roles:
            added = [r.mention for r in after.roles if r not in before.roles]
            removed = [r.mention for r in before.roles if r not in after.roles]
            if added or removed:
                disp_name, handle = await self._format_user(after, guild)
                desc = f"**User:** {disp_name}\n**Username:** {handle}\n"
                if added:
                    desc += f"➕ **Added:** {', '.join(added)}\n"
                if removed:
                    desc += f"➖ **Removed:** {', '.join(removed)}"
                embed = discord.Embed(
                    title="🛡️ Member Roles Updated",
                    description=desc,
                    color=BRAND_COLOR,
                    timestamp=datetime.now(timezone.utc),
                )
                await self._emit_log(guild, "members", "role_change", embed, f"Roles updated for {after.id}", target_id=after.id)

    # ── 3. Member Status & Presence Events ──────────────────────────────────

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.bot or not before.guild:
            return

        # 30-second cooldown per user to prevent rapid status-toggle spam
        now = time.time()
        last_logged = self._status_cooldowns.get(after.id, 0.0)
        if now - last_logged < 30.0:
            return

        if before.status != after.status:
            self._status_cooldowns[after.id] = now
            disp_name, handle = await self._format_user(after, before.guild)
            status_colors = {
                discord.Status.online: 0x00F5A0,
                discord.Status.idle: 0xFFA500,
                discord.Status.dnd: 0xFF4444,
                discord.Status.offline: 0x747F8D,
            }
            embed = discord.Embed(
                title="📡 Member Status Changed",
                description=(
                    f"**User:** {disp_name}\n"
                    f"**Username:** {handle}\n"
                    f"**Before:** `{before.status.name.upper()}`\n"
                    f"**After:** `{after.status.name.upper()}`"
                ),
                color=status_colors.get(after.status, BRAND_COLOR),
                timestamp=datetime.now(timezone.utc),
            )
            await self._emit_log(before.guild, "status", "status_change", embed, f"Status: {before.status.name} -> {after.status.name}", actor_id=after.id)

    # ── 4. Voice Events ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.id == self.bot.user.id:
            return  # Suppress bot's own voice connections from spamming audit logs

        guild = member.guild
        disp_name, handle = await self._format_user(member, guild)

        # 1. Channel connection changes
        if before.channel != after.channel:
            if before.channel is None and after.channel is not None:
                embed = discord.Embed(
                    title="🔊 Voice Channel Joined",
                    description=(
                        f"**User:** {disp_name}\n"
                        f"**Username:** {handle}\n"
                        f"**Channel:** **#{after.channel.name}**"
                    ),
                    color=0x00F5A0,
                    timestamp=datetime.now(timezone.utc),
                )
                await self._emit_log(guild, "voice", "voice_join", embed, f"Joined VC {after.channel.id}", actor_id=member.id)
            elif before.channel is not None and after.channel is None:
                embed = discord.Embed(
                    title="🔇 Voice Channel Left",
                    description=(
                        f"**User:** {disp_name}\n"
                        f"**Username:** {handle}\n"
                        f"**Channel:** **#{before.channel.name}**"
                    ),
                    color=0xFF5555,
                    timestamp=datetime.now(timezone.utc),
                )
                await self._emit_log(guild, "voice", "voice_leave", embed, f"Left VC {before.channel.id}", actor_id=member.id)
            elif before.channel is not None and after.channel is not None:
                embed = discord.Embed(
                    title="🔁 Voice Channel Moved",
                    description=(
                        f"**User:** {disp_name}\n"
                        f"**Username:** {handle}\n"
                        f"**Move:** **#{before.channel.name}** ➔ **#{after.channel.name}**"
                    ),
                    color=0x3B82F6,
                    timestamp=datetime.now(timezone.utc),
                )
                await self._emit_log(guild, "voice", "voice_move", embed, f"Moved VC {before.channel.id} -> {after.channel.id}", actor_id=member.id)

        # 2. Server mute / deafen changes
        if before.mute != after.mute:
            state_str = "Server Muted" if after.mute else "Server Unmuted"
            embed = discord.Embed(
                title=f"🎙️ Voice State: {state_str}",
                description=f"**User:** {disp_name}\n**Username:** {handle}\nMember was **{state_str.lower()}**.",
                color=0xFF4444 if after.mute else 0x00F5A0,
                timestamp=datetime.now(timezone.utc),
            )
            await self._emit_log(guild, "voice", "voice_mute", embed, f"VC Mute: {after.mute}", actor_id=member.id)

        if before.deaf != after.deaf:
            state_str = "Server Deafened" if after.deaf else "Server Undeafened"
            embed = discord.Embed(
                title=f"🎧 Voice State: {state_str}",
                description=f"**User:** {disp_name}\n**Username:** {handle}\nMember was **{state_str.lower()}**.",
                color=0xFF4444 if after.deaf else 0x00F5A0,
                timestamp=datetime.now(timezone.utc),
            )
            await self._emit_log(guild, "voice", "voice_deafen", embed, f"VC Deaf: {after.deaf}", actor_id=member.id)

    # ── 5. Channel & Role Events ────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        if await self._is_channel_ignored(channel.guild, channel):
            return
        if self._is_duplicate_event(f"channel_create:{channel.id}", window=3.0):
            return
        embed = discord.Embed(
            title="📁 Channel Created",
            description=f"**Name:** `#{channel.name}`\n**Type:** `{channel.type}`",
            color=0x00F5A0,
            timestamp=datetime.now(timezone.utc),
        )
        await self._emit_log(channel.guild, "server", "channel_create", embed, f"Channel created: {channel.name} ({channel.id})")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        if await self._is_channel_ignored(channel.guild, channel):
            return
        if self._is_duplicate_event(f"channel_delete:{channel.id}", window=3.0):
            return
        embed = discord.Embed(
            title="🗑️ Channel Deleted",
            description=f"**Name:** `#{channel.name}`\n**Type:** `{channel.type}`",
            color=0xFF3333,
            timestamp=datetime.now(timezone.utc),
        )
        await self._emit_log(channel.guild, "server", "channel_delete", embed, f"Channel deleted: {channel.name} ({channel.id})")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        if self._is_duplicate_event(f"role_create:{role.id}", window=3.0):
            return
        hex_color = f"#{role.color.value:06X}" if role.color.value else "#000000"
        embed = discord.Embed(
            title="New role created",
            description=(
                f"**Name:** {role.name}\n"
                f"**Color:** {hex_color}\n"
                f"**Mentionable:** {role.mentionable}\n"
                f"**Displayed separately:** {role.hoist}"
            ),
            color=0x57F287,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Role ID: {role.id}")
        await self._emit_log(role.guild, "server", "role_change", embed, f"Role created: {role.name} ({role.id})")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        if self._is_duplicate_event(f"role_delete:{role.id}", window=3.0):
            return
        hex_color = f"#{role.color.value:06X}" if role.color.value else "#000000"
        embed = discord.Embed(
            title="Role deleted",
            description=(
                f"**Name:** {role.name}\n"
                f"**Color:** {hex_color}"
            ),
            color=0xED4245,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Role ID: {role.id}")
        await self._emit_log(role.guild, "server", "role_change", embed, f"Role deleted: {role.name} ({role.id})")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        if self._is_duplicate_event(f"role_update:{after.id}", window=2.0):
            return
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** `{before.name}` ➔ `{after.name}`")
        if before.color != after.color:
            b_hex = f"#{before.color.value:06X}" if before.color.value else "#000000"
            a_hex = f"#{after.color.value:06X}" if after.color.value else "#000000"
            changes.append(f"**Color:** `{b_hex}` ➔ `{a_hex}`")
        if before.hoist != after.hoist:
            changes.append(f"**Displayed separately:** `{before.hoist}` ➔ `{after.hoist}`")
        if before.mentionable != after.mentionable:
            changes.append(f"**Mentionable:** `{before.mentionable}` ➔ `{after.mentionable}`")
        if not changes:
            return

        embed = discord.Embed(
            title="Role updated",
            description=f"**Role:** {after.mention}\n" + "\n".join(changes),
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Role ID: {after.id}")
        await self._emit_log(after.guild, "server", "role_change", embed, f"Role updated: {after.name} ({after.id})")

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** `{before.name}` ➔ `{after.name}`")
        if before.icon != after.icon:
            changes.append("**Icon:** Updated server avatar/icon.")
        if changes:
            embed = discord.Embed(
                title="⚙️ Server Configuration Updated",
                description="\n".join(changes),
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            await self._emit_log(after, "server", "server_update", embed, f"Server updated: {', '.join(changes)}")


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(LoggingService(bot))
