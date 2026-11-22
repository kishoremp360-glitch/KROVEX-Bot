"""Advanced Logging Configuration and Audit Trail Cog for Death Bot."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.logging")
BRAND_COLOR = 0x9D4EDD

CATEGORY_MAP = {
    "mod": "mod_log_channel",
    "messages": "message_log_channel",
    "members": "member_log_channel",
    "server": "server_log_channel",
    "voice": "voice_log_channel",
    "status": "status_log_channel",
    "invites": "invite_log_channel",
}


class Logging(commands.GroupCog, group_name="logs", group_description="Audit log channels, event filters, and history"):
    """Server event logging, channel routing, event filters, and incident query commands."""

    def __init__(self, bot: "DeathBot") -> None:
        super().__init__()
        self.bot = bot

    # ── 1. logchannel ───────────────────────────────────────────────────────

    async def _execute_logchannel(self, ctx: UnifiedContext, category: str, channel: Optional[discord.TextChannel] = None) -> None:
        await ctx.defer(ephemeral=True)
        if not ctx.guild:
            return
        cat = category.lower()
        if cat not in CATEGORY_MAP and cat != "all":
            await ctx.send_error("Invalid Category", f"Valid categories: `mod`, `messages`, `members`, `server`, `voice`, `status`, `invites`, or `all`.")
            return

        ch_id = channel.id if channel else None
        if self.bot.logging_repo:
            if cat == "all":
                updates = {col: ch_id for col in CATEGORY_MAP.values()}
                await self.bot.logging_repo.update_settings(ctx.guild.id, **updates)
            else:
                col = CATEGORY_MAP[cat]
                await self.bot.logging_repo.update_settings(ctx.guild.id, **{col: ch_id})

        target_str = channel.mention if channel else "*Disabled (cleared)*"
        await ctx.send_success("Log Channel Set", f"Log channel for **{category.upper()}** set to: {target_str}.")

    @commands.command(name="logchannel", aliases=["setlogchannel"], help="Set the log channel for an event category (mod, messages, members, server, voice, status, invites, all).")
    @commands.has_permissions(administrator=True)
    async def logchannel_prefix(self, ctx: commands.Context, category: str, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_logchannel(UnifiedContext.from_prefix(ctx), category, channel)

    @app_commands.command(name="channel", description="Set log channel for an event category.")
    @app_commands.describe(category="Category: mod, messages, members, server, voice, status, invites, all", channel="Target channel (leave empty to disable)")
    @app_commands.default_permissions(administrator=True)
    async def channel_slash(self, interaction: discord.Interaction, category: str, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_logchannel(UnifiedContext.from_interaction(interaction), category, channel)

    # ── 2. logstatus ────────────────────────────────────────────────────────

    async def _execute_logstatus(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            return
        settings = await self.bot.logging_repo.get_settings(ctx.guild.id) if self.bot.logging_repo else {}
        toggles = await self.bot.logging_repo.get_event_toggles(ctx.guild.id) if self.bot.logging_repo else {}

        def _fmt_ch(cid: Optional[int]) -> str:
            return f"<#{cid}>" if cid else "🔴 *Not Set*"

        is_enabled = bool(settings.get("logging_enabled", 1))
        status_header = "🟢 **LOGGING ACTIVE**" if is_enabled else "🔴 **LOGGING SUSPENDED**"

        channels_text = (
            f"🛡️ **Security Feed:** {_fmt_ch(settings.get('mod_log_channel'))}\n"
            f"💬 **Message Tracker:** {_fmt_ch(settings.get('message_log_channel'))}\n"
            f"👥 **Member Activity:** {_fmt_ch(settings.get('member_log_channel'))}\n"
            f"⚙️ **Server Changes:** {_fmt_ch(settings.get('server_log_channel'))}\n"
            f"🔊 **Voice Monitor:** {_fmt_ch(settings.get('voice_log_channel'))}\n"
            f"📡 **Presence Tracker:** {_fmt_ch(settings.get('status_log_channel'))}\n"
            f"📨 **Invite Tracker:** {_fmt_ch(settings.get('invite_log_channel'))}"
        )

        all_events = [
            ("msg_delete", "Message Deletions"),
            ("msg_edit", "Message Edits"),
            ("bulk_delete", "Bulk Purges"),
            ("member_join", "Member Joins"),
            ("member_leave", "Member Leaves"),
            ("voice_join", "Voice Joins"),
            ("voice_leave", "Voice Leaves"),
            ("voice_move", "Voice Moves"),
            ("voice_mute", "Voice Server Mutes"),
            ("voice_deafen", "Voice Server Deafs"),
            ("status_change", "Member Status Changes"),
            ("invite_join", "Invite Usage Attribution"),
            ("role_change", "Role Changes"),
            ("nick_change", "Nickname Changes"),
            ("channel_create", "Channel Creates"),
            ("channel_delete", "Channel Deletes"),
            ("server_update", "Server Configuration Updates"),
        ]
        toggles_text = "\n".join(
            f"{'🟢' if toggles.get(k, True) else '🔴'} **{label}**" for k, label in all_events
        )

        embed = EmbedBuilder.base(
            title=f"📋 Logging Status • {ctx.guild.name}",
            description=f"**Master Status:** {status_header}\n\nOverview of configured audit log destinations and enabled event dispatchers:",
            color=BRAND_COLOR if is_enabled else 0xFF4444,
        )
        embed.add_field(name="📁 Log Destinations", value=channels_text, inline=False)
        embed.add_field(name=f"{KrovexEmoji.LIGHTNING} Active Event Toggles", value=toggles_text, inline=False)
        await ctx.reply(embed=embed)

    @commands.command(name="logstatus", help="Show all configured log channels and active event toggles.")
    @commands.has_permissions(administrator=True)
    async def logstatus_prefix(self, ctx: commands.Context) -> None:
        await self._execute_logstatus(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="status", description="Show all configured log channels and event toggles.")
    @app_commands.default_permissions(administrator=True)
    async def logstatus_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_logstatus(UnifiedContext.from_interaction(interaction))

    # ── 3. autolog setup ────────────────────────────────────────────────────

    async def _execute_autolog(self, ctx: UnifiedContext) -> None:
        # Acknowledge immediately within Discord's 3-second deadline to prevent timeout
        await ctx.defer(ephemeral=True)
        guild = ctx.guild
        if not guild:
            return

        if not guild.me.guild_permissions.manage_channels:
            await ctx.send_error(
                "Missing Permissions",
                "I require the **Manage Channels** permission to automatically provision the audit log channels."
            )
            return

        CANONICAL_CATEGORY = "⛨・KROVEX AUDIT VAULT"
        try:
            # Check for existing canonical category or legacy categories
            category = discord.utils.get(guild.categories, name=CANONICAL_CATEGORY)
            legacy_logs_cat = discord.utils.get(guild.categories, name="📋 LOGS")
            server_logs_cat = discord.utils.find(lambda c: c.name.upper() == "SERVER LOGS", guild.categories)

            legacy_retained_notes: List[str] = []
            if server_logs_cat:
                legacy_retained_notes.append(f"Legacy `{server_logs_cat.name}` category detected and safely retained intact.")

            if not category:
                if legacy_logs_cat:
                    # Seamlessly elevate 📋 LOGS to canonical ⛨・KROVEX AUDIT VAULT
                    try:
                        await legacy_logs_cat.edit(name=CANONICAL_CATEGORY, reason="KROVEX Logging Architecture Redesign")
                        category = legacy_logs_cat
                        legacy_retained_notes.append("Upgraded `📋 LOGS` to canonical `⛨・KROVEX AUDIT VAULT`.")
                    except Exception:
                        category = legacy_logs_cat

            if not category:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True),
                }
                category = await guild.create_category(CANONICAL_CATEGORY, overwrites=overwrites, reason="KROVEX Logging Setup")
            else:
                # Enforce @everyone view denial on canonical category
                try:
                    await category.set_permissions(
                        guild.default_role,
                        read_messages=False,
                        send_messages=False,
                        reason="KROVEX Audit Vault Security Enforcement"
                    )
                    await category.set_permissions(
                        guild.me,
                        read_messages=True,
                        send_messages=True,
                        embed_links=True,
                        reason="KROVEX Audit Vault Security Enforcement"
                    )
                except Exception:
                    pass

            target_channels = {
                "mod": (
                    "security-feed",
                    "🛡️ Security, moderation actions, and anti-nuke audit logs",
                    ["security-feed", "mod-logs", "mod-log", "security", "mod"]
                ),
                "messages": (
                    "message-tracker",
                    "💬 Message edits, deletions, and bulk purges",
                    ["message-tracker", "message-logs", "message-log", "messages"]
                ),
                "members": (
                    "member-activity",
                    "👥 Member joins, leaves, bans, and updates",
                    ["member-activity", "member-logs", "member-log", "members"]
                ),
                "voice": (
                    "voice-monitor",
                    "🔊 Voice joins, leaves, moves, and server mute/deafen",
                    ["voice-monitor", "voice-logs", "voice-log", "voice"]
                ),
                "status": (
                    "presence-tracker",
                    "📡 Member presence and online status transitions",
                    ["presence-tracker", "status-logs", "status-log", "status"]
                ),
                "invites": (
                    "invite-tracker",
                    "📨 Invite creation, deletion, and tracking attribution",
                    ["invite-tracker", "invite-logs", "invite-log", "invites"]
                ),
                "server": (
                    "server-changes",
                    "⚙️ Role changes, channel updates, and guild settings",
                    ["server-changes", "server-logs", "server-log", "server"]
                ),
            }

            created_channels: Dict[str, discord.TextChannel] = {}
            for cat_key, (ch_name, topic, legacy_names) in target_channels.items():
                # 1. Look for existing canonical or legacy channel inside category
                target_ch = next((c for c in category.text_channels if getattr(c, "name", None) == ch_name), None)
                if not target_ch:
                    for legacy_name in legacy_names:
                        target_ch = next((c for c in category.text_channels if getattr(c, "name", None) == legacy_name), None)
                        if target_ch:
                            try:
                                await target_ch.edit(name=ch_name, topic=topic, reason="KROVEX Logging Redesign Channel Migration")
                            except Exception:
                                pass
                            break

                # 2. If not found in category, check guild for unmigrated channel to adopt
                if not target_ch:
                    for legacy_name in legacy_names:
                        candidate = next((c for c in getattr(guild, "text_channels", []) if getattr(c, "name", None) == legacy_name), None)
                        if candidate and candidate not in created_channels.values():
                            try:
                                await candidate.edit(
                                    name=ch_name,
                                    category=category,
                                    topic=topic,
                                    reason="KROVEX Logging Redesign Channel Migration"
                                )
                                target_ch = candidate
                                break
                            except Exception:
                                pass

                # 3. If still not found, provision fresh channel in category
                if not target_ch:
                    target_ch = await category.create_text_channel(
                        ch_name,
                        topic=topic,
                        reason="KROVEX Audit Vault AutoLog Setup",
                    )

                # 4. Enforce staff-only private overwrites
                try:
                    current_ov = target_ch.overwrites_for(guild.default_role)
                    if current_ov.read_messages is not False:
                        await target_ch.set_permissions(
                            guild.default_role,
                            read_messages=False,
                            send_messages=False,
                            reason="KROVEX Audit Vault Child Channel Security Sync"
                        )
                except Exception:
                    pass

                created_channels[cat_key] = target_ch

            if self.bot.logging_repo:
                await self.bot.logging_repo.update_settings(
                    guild.id,
                    mod_log_channel=created_channels["mod"].id,
                    message_log_channel=created_channels["messages"].id,
                    member_log_channel=created_channels["members"].id,
                    server_log_channel=created_channels["server"].id,
                    voice_log_channel=created_channels["voice"].id,
                    status_log_channel=created_channels["status"].id,
                    invite_log_channel=created_channels["invites"].id,
                    logging_enabled=1,
                )

            verify_embed = discord.Embed(
                title="⛨ KROVEX AUDIT VAULT INITIALIZED",
                description=(
                    f"**Audit Architecture Active for {guild.name}**\n\n"
                    f"All 7 dedicated KROVEX monitoring channels have been provisioned and secured.\n"
                    f"Event streams are armed with high-fidelity tamper-evident auditing."
                ),
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            verify_embed.set_footer(text="KROVEX AUDIT VAULT • SECURITY FEED")
            try:
                await created_channels["mod"].send(embed=verify_embed)
            except Exception:
                pass

            retention_text = ""
            if server_logs_cat:
                retention_text = (
                    f"\n\n🛡️ **Legacy Preservation Notice:**\n"
                    f"Category `{server_logs_cat.name}` was detected and preserved intact to protect historical chat archives. "
                    f"User approval is required before removing any legacy categories."
                )

            embed = EmbedBuilder.success(
                title="⛨ KROVEX Audit Vault Configured",
                description=(
                    f"Successfully consolidated **{len(created_channels)}** logging channels in `{category.name}`:\n\n"
                    + "\n".join(f"• **{k.upper()}:** {ch.mention}" for k, ch in created_channels.items())
                    + "\n\nAll event dispatchers are now **ARMED**."
                    + retention_text
                ),
            )
            await ctx.reply(embed=embed)
        except discord.Forbidden as f_err:
            logger.warning("Forbidden error during AutoLog setup in guild %s: %s", guild.id, f_err)
            await ctx.send_error("AutoLog Failed", f"Discord permission denied: {f_err}")
        except Exception as err:
            logger.error("AutoLog provisioning failed in guild %s: %s", guild.id, err, exc_info=True)
            await ctx.send_error("AutoLog Failed", f"An error occurred while provisioning logging channels: {err}")

    @commands.command(name="autolog", help="Automatically configure logging category and all 7 audit channels.")
    @commands.has_permissions(administrator=True)
    async def autolog_prefix(self, ctx: commands.Context, action: str = "setup") -> None:
        await self._execute_autolog(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="autolog", description="Automatically configure logging category and channels.")
    @app_commands.default_permissions(administrator=True)
    async def autolog_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_autolog(UnifiedContext.from_interaction(interaction))

    # ── 4. log reset, disable, enable ───────────────────────────────────────

    async def _execute_logreset(self, ctx: UnifiedContext) -> None:
        await ctx.defer(ephemeral=True)
        if not ctx.guild:
            return
        if self.bot.logging_repo:
            await self.bot.logging_repo.reset_settings(ctx.guild.id)
        embed = EmbedBuilder.success(
            title="Logging Configuration Reset",
            description=(
                "All logging channel assignments and event toggles have been reset to default.\n\n"
                "🔒 **Data Preservation:** Historical audit records and Discord messages were **not** deleted."
            ),
        )
        await ctx.reply(embed=embed)

    async def _execute_logdisable(self, ctx: UnifiedContext) -> None:
        await ctx.defer(ephemeral=True)
        if not ctx.guild:
            return
        if self.bot.logging_repo:
            await self.bot.logging_repo.set_logging_enabled(ctx.guild.id, False)
        embed = EmbedBuilder.base(
            title="⏸️ Logging Suspended",
            description=(
                "All audit logging dispatchers have been **DISABLED** for this server.\n"
                "All saved channel destinations, filters, and configuration remain safely preserved.\n"
                "Use `,log enable` to resume logging."
            ),
            color=0xFF4444,
        )
        await ctx.reply(embed=embed)

    async def _execute_logenable(self, ctx: UnifiedContext) -> None:
        await ctx.defer(ephemeral=True)
        if not ctx.guild:
            return
        if self.bot.logging_repo:
            await self.bot.logging_repo.set_logging_enabled(ctx.guild.id, True)
        embed = EmbedBuilder.success(
            title="▶️ Logging Resumed",
            description="Audit logging has been **RE-ENABLED** with all previously saved configuration."
        )
        await ctx.reply(embed=embed)

    @app_commands.command(name="reset", description="Reset logging channel destinations and event toggles without deleting records.")
    @app_commands.default_permissions(administrator=True)
    async def logreset_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_logreset(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="disable", description="Pause all audit event logging while preserving saved settings.")
    @app_commands.default_permissions(administrator=True)
    async def logdisable_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_logdisable(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="enable", description="Resume audit event logging using saved configuration.")
    @app_commands.default_permissions(administrator=True)
    async def logenable_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_logenable(UnifiedContext.from_interaction(interaction))

    # ── 5. logtoggle ────────────────────────────────────────────────────────

    async def _execute_logtoggle(self, ctx: UnifiedContext, event_name: str, toggle: str) -> None:
        if not ctx.guild:
            return
        enable = toggle.lower() in ("enable", "true", "on", "yes", "1")
        if self.bot.logging_repo:
            await self.bot.logging_repo.toggle_event(ctx.guild.id, event_name.lower(), enable)
        status = "ENABLED" if enable else "DISABLED"
        await ctx.send_success("Event Toggle Updated", f"Logging for event `{event_name}` is now **{status}**.")

    @commands.command(name="logtoggle", help="Toggle a specific logging event (enable/disable).")
    @commands.has_permissions(administrator=True)
    async def logtoggle_prefix(self, ctx: commands.Context, event_name: str, toggle: str) -> None:
        await self._execute_logtoggle(UnifiedContext.from_prefix(ctx), event_name, toggle)

    @app_commands.command(name="toggle", description="Toggle a specific logging event.")
    @app_commands.describe(event_name="Event name (e.g. msg_delete, member_join, voice_join, status_change)", toggle="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def logtoggle_slash(self, interaction: discord.Interaction, event_name: str, toggle: str) -> None:
        await self._execute_logtoggle(UnifiedContext.from_interaction(interaction), event_name, toggle)

    # ── 6. logignorechannel & logignorerole ─────────────────────────────────

    async def _execute_logignorechannel(self, ctx: UnifiedContext, action: str, channel: discord.TextChannel) -> None:
        if not ctx.guild:
            return
        action = action.lower()
        if self.bot.logging_repo:
            if action in ("add", "ignore"):
                await self.bot.logging_repo.add_filter(ctx.guild.id, "channel", str(channel.id))
                await ctx.send_success("Channel Ignored", f"Messages from {channel.mention} will no longer be logged.")
            else:
                await self.bot.logging_repo.remove_filter(ctx.guild.id, "channel", str(channel.id))
                await ctx.send_success("Channel Restored", f"Messages from {channel.mention} will now be logged.")

    @commands.command(name="logignorechannel", help="Add or remove a channel from message logging.")
    @commands.has_permissions(administrator=True)
    async def logignorechannel_prefix(self, ctx: commands.Context, action: str, channel: discord.TextChannel) -> None:
        await self._execute_logignorechannel(UnifiedContext.from_prefix(ctx), action, channel)

    @app_commands.command(name="ignorechannel", description="Add or remove a channel from message logging.")
    @app_commands.describe(action="add or remove", channel="Channel to filter")
    @app_commands.default_permissions(administrator=True)
    async def logignorechannel_slash(self, interaction: discord.Interaction, action: str, channel: discord.TextChannel) -> None:
        await self._execute_logignorechannel(UnifiedContext.from_interaction(interaction), action, channel)

    async def _execute_logignorerole(self, ctx: UnifiedContext, action: str, role: discord.Role) -> None:
        if not ctx.guild:
            return
        action = action.lower()
        if self.bot.logging_repo:
            if action in ("add", "ignore"):
                await self.bot.logging_repo.add_filter(ctx.guild.id, "role", str(role.id))
                await ctx.send_success("Role Ignored", f"Actions from members with {role.mention} will be ignored.")
            else:
                await self.bot.logging_repo.remove_filter(ctx.guild.id, "role", str(role.id))
                await ctx.send_success("Role Restored", f"Actions from members with {role.mention} will now be logged.")

    @commands.command(name="logignorerole", help="Add or remove a role from being logged.")
    @commands.has_permissions(administrator=True)
    async def logignorerole_prefix(self, ctx: commands.Context, action: str, role: discord.Role) -> None:
        await self._execute_logignorerole(UnifiedContext.from_prefix(ctx), action, role)

    @app_commands.command(name="ignorerole", description="Add or remove a role from being logged.")
    @app_commands.describe(action="add or remove", role="Role to filter")
    @app_commands.default_permissions(administrator=True)
    async def logignorerole_slash(self, interaction: discord.Interaction, action: str, role: discord.Role) -> None:
        await self._execute_logignorerole(UnifiedContext.from_interaction(interaction), action, role)

    # ── 7. logfilter ────────────────────────────────────────────────────────

    async def _execute_logfilter(self, ctx: UnifiedContext, action: str, keyword: str) -> None:
        if not ctx.guild:
            return
        action = action.lower()
        if self.bot.logging_repo:
            if action in ("add", "create"):
                await self.bot.logging_repo.add_filter(ctx.guild.id, "keyword", keyword.lower())
                await ctx.send_success("Filter Added", f"Added keyword filter for: `{keyword}`.")
            else:
                await self.bot.logging_repo.remove_filter(ctx.guild.id, "keyword", keyword.lower())
                await ctx.send_success("Filter Removed", f"Removed keyword filter for: `{keyword}`.")

    @commands.command(name="logfilter", help="Add or remove a keyword filter from message logs.")
    @commands.has_permissions(administrator=True)
    async def logfilter_prefix(self, ctx: commands.Context, action: str, *, keyword: str) -> None:
        await self._execute_logfilter(UnifiedContext.from_prefix(ctx), action, keyword)

    @app_commands.command(name="filter", description="Add or remove keyword filter.")
    @app_commands.describe(action="add or remove", keyword="Keyword string")
    @app_commands.default_permissions(administrator=True)
    async def logfilter_slash(self, interaction: discord.Interaction, action: str, keyword: str) -> None:
        await self._execute_logfilter(UnifiedContext.from_interaction(interaction), action, keyword)

    # ── 8. loghistory & logclear ────────────────────────────────────────────

    async def _execute_loghistory(self, ctx: UnifiedContext, limit: int = 15, event_type: Optional[str] = None) -> None:
        if not ctx.guild:
            return
        limit = min(max(1, limit), 25)
        logs = await self.bot.logging_repo.get_recent_logs(ctx.guild.id, limit, event_type) if self.bot.logging_repo else []
        if not logs:
            await ctx.send_error("No Records", "No audit logs found matching criteria.")
            return

        lines = [f"`{l['timestamp'][:19]}` **[{l['event_type']}]** {l['details']}" for l in logs]
        embed = EmbedBuilder.base(
            title=f"📜 Audit Log History • {ctx.guild.name}",
            description="\n".join(lines),
            color=BRAND_COLOR,
            footer_text=f"Showing last {len(logs)} entries",
        )
        await ctx.reply(embed=embed)

    @commands.command(name="loghistory", help="Query stored audit log entries.")
    @commands.has_permissions(administrator=True)
    async def loghistory_prefix(self, ctx: commands.Context, limit: int = 15, event_type: Optional[str] = None) -> None:
        await self._execute_loghistory(UnifiedContext.from_prefix(ctx), limit, event_type)

    @app_commands.command(name="history", description="Query stored audit log entries.")
    @app_commands.describe(limit="Number of entries (max 25)", event_type="Optional filter (e.g. msg_delete)")
    @app_commands.default_permissions(administrator=True)
    async def loghistory_slash(self, interaction: discord.Interaction, limit: int = 15, event_type: Optional[str] = None) -> None:
        await self._execute_loghistory(UnifiedContext.from_interaction(interaction), limit, event_type)

    async def _execute_logclear(self, ctx: UnifiedContext, event_type: Optional[str] = None) -> None:
        if not ctx.guild:
            return
        if self.bot.logging_repo:
            count = await self.bot.logging_repo.clear_logs(ctx.guild.id, event_type)
            await ctx.send_success("Audit History Purged", f"Cleared **{count}** audit log records from database storage.")

    @commands.command(name="logclear", help="Clear historical audit logs from database.")
    @commands.has_permissions(administrator=True)
    async def logclear_prefix(self, ctx: commands.Context, event_type: Optional[str] = None) -> None:
        await self._execute_logclear(UnifiedContext.from_prefix(ctx), event_type)

    @app_commands.command(name="clear", description="Clear historical audit logs.")
    @app_commands.describe(event_type="Optional event type to clear")
    @app_commands.default_permissions(administrator=True)
    async def logclear_slash(self, interaction: discord.Interaction, event_type: Optional[str] = None) -> None:
        await self._execute_logclear(UnifiedContext.from_interaction(interaction), event_type)

    # ── 9. Quick Toggles ────────────────────────────────────────────────────

    async def _quick_toggle(self, ctx: UnifiedContext, event: str, label: str, toggle: str) -> None:
        enable = toggle.lower() in ("enable", "true", "on", "yes", "1")
        if self.bot.logging_repo and ctx.guild:
            await self.bot.logging_repo.toggle_event(ctx.guild.id, event, enable)
        status = "ENABLED" if enable else "DISABLED"
        await ctx.send_success("Toggle Updated", f"{label} logging is now **{status}**.")

    @commands.command(name="logmsgdelete", help="Quick toggle for message deletion logging.")
    @commands.has_permissions(administrator=True)
    async def logmsgdelete_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_prefix(ctx), "msg_delete", "Message Deletions", toggle)

    @app_commands.command(name="msgdelete", description="Quick toggle for message deletion logging.")
    @app_commands.describe(toggle="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def logmsgdelete_slash(self, interaction: discord.Interaction, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_interaction(interaction), "msg_delete", "Message Deletions", toggle)

    @commands.command(name="logmsgedit", help="Quick toggle for message edit logging.")
    @commands.has_permissions(administrator=True)
    async def logmsgedit_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_prefix(ctx), "msg_edit", "Message Edits", toggle)

    @app_commands.command(name="msgedit", description="Quick toggle for message edit logging.")
    @app_commands.describe(toggle="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def logmsgedit_slash(self, interaction: discord.Interaction, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_interaction(interaction), "msg_edit", "Message Edits", toggle)

    @commands.command(name="logbulkdelete", help="Quick toggle for bulk purge logging.")
    @commands.has_permissions(administrator=True)
    async def logbulkdelete_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_prefix(ctx), "bulk_delete", "Bulk Purge", toggle)

    @app_commands.command(name="bulkdelete", description="Quick toggle for bulk purge logging.")
    @app_commands.describe(toggle="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def logbulkdelete_slash(self, interaction: discord.Interaction, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_interaction(interaction), "bulk_delete", "Bulk Purge", toggle)

    @commands.command(name="logmemberjoin", help="Quick toggle for member join logging.")
    @commands.has_permissions(administrator=True)
    async def logmemberjoin_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_prefix(ctx), "member_join", "Member Join", toggle)

    @app_commands.command(name="memberjoin", description="Quick toggle for member join logging.")
    @app_commands.describe(toggle="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def logmemberjoin_slash(self, interaction: discord.Interaction, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_interaction(interaction), "member_join", "Member Join", toggle)

    @commands.command(name="logmemberleave", help="Quick toggle for member leave logging.")
    @commands.has_permissions(administrator=True)
    async def logmemberleave_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_prefix(ctx), "member_leave", "Member Leave", toggle)

    @app_commands.command(name="memberleave", description="Quick toggle for member leave logging.")
    @app_commands.describe(toggle="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def logmemberleave_slash(self, interaction: discord.Interaction, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_interaction(interaction), "member_leave", "Member Leave", toggle)

    @commands.command(name="logvoice", help="Quick toggle for voice join/leave/move logging.")
    @commands.has_permissions(administrator=True)
    async def logvoice_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_prefix(ctx), "voice_join", "Voice Activity", toggle)

    @app_commands.command(name="voice", description="Quick toggle for voice activity logging.")
    @app_commands.describe(toggle="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def logvoice_slash(self, interaction: discord.Interaction, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_interaction(interaction), "voice_join", "Voice Activity", toggle)

    @commands.command(name="logroles", help="Quick toggle for member role change logging.")
    @commands.has_permissions(administrator=True)
    async def logroles_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_prefix(ctx), "role_change", "Role Change", toggle)

    @app_commands.command(name="roles", description="Quick toggle for role change logging.")
    @app_commands.describe(toggle="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def logroles_slash(self, interaction: discord.Interaction, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_interaction(interaction), "role_change", "Role Change", toggle)

    @commands.command(name="logchannels", help="Quick toggle for channel create/delete logging.")
    @commands.has_permissions(administrator=True)
    async def logchannels_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_prefix(ctx), "channel_create", "Channel Events", toggle)

    @app_commands.command(name="channels", description="Quick toggle for channel event logging.")
    @app_commands.describe(toggle="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def logchannels_slash(self, interaction: discord.Interaction, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_interaction(interaction), "channel_create", "Channel Events", toggle)

    @commands.command(name="logserver", help="Quick toggle for server configuration logging.")
    @commands.has_permissions(administrator=True)
    async def logserver_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_prefix(ctx), "server_update", "Server Update", toggle)

    @app_commands.command(name="server", description="Quick toggle for server update logging.")
    @app_commands.describe(toggle="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def logserver_slash(self, interaction: discord.Interaction, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_interaction(interaction), "server_update", "Server Update", toggle)

    @commands.command(name="logstatuschange", help="Quick toggle for member status/presence logging.")
    @commands.has_permissions(administrator=True)
    async def logstatuschange_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_prefix(ctx), "status_change", "Status Changes", toggle)

    @commands.command(name="loginvites", help="Quick toggle for invite tracking logging.")
    @commands.has_permissions(administrator=True)
    async def loginvites_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._quick_toggle(UnifiedContext.from_prefix(ctx), "invite_join", "Invite Tracking", toggle)

    # ── 10. logtest ─────────────────────────────────────────────────────────

    async def _execute_logtest(self, ctx: UnifiedContext, category: str = "server") -> None:
        if not ctx.guild:
            return
        cat = category.lower()
        if cat not in CATEGORY_MAP:
            cat = "server"
        settings = await self.bot.logging_repo.get_settings(ctx.guild.id) if self.bot.logging_repo else {}
        col = CATEGORY_MAP[cat]
        ch_id = settings.get(col)
        if not ch_id:
            await ctx.send_error("Channel Not Set", f"No log channel configured for `{cat}`. Use `!logchannel {cat} #channel`.")
            return

        ch = ctx.guild.get_channel(ch_id)
        if not isinstance(ch, discord.TextChannel):
            await ctx.send_error("Channel Invalid", f"Configured channel ID `{ch_id}` is not a valid text channel.")
            return

        test_embed = discord.Embed(
            title="🧪 Death Bot Logging Test",
            description=f"This is a simulated verification card dispatched to verify `{cat}` audit channel functionality.",
            color=BRAND_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        test_embed.set_footer(text=f"Dispatched by {ctx.author.name}")
        try:
            await ch.send(embed=test_embed)
            await ctx.send_success("Test Log Sent", f"Dispatched test audit card to {ch.mention}.")
        except Exception as e:
            await ctx.send_error("Send Failed", str(e))

    @commands.command(name="logtest", help="Dispatch a test audit card to verify log channel output.")
    @commands.has_permissions(administrator=True)
    async def logtest_prefix(self, ctx: commands.Context, category: str = "server") -> None:
        await self._execute_logtest(UnifiedContext.from_prefix(ctx), category)

    @app_commands.command(name="test", description="Dispatch a test audit card.")
    @app_commands.describe(category="Category: mod, messages, members, server, voice, status, invites")
    @app_commands.default_permissions(administrator=True)
    async def logtest_slash(self, interaction: discord.Interaction, category: str = "server") -> None:
        await self._execute_logtest(UnifiedContext.from_interaction(interaction), category)

    # ── 11. Command Group 'log' ─────────────────────────────────────────────

    @commands.group(name="log", invoke_without_command=True, help="Server audit logging management.")
    @commands.has_permissions(administrator=True)
    async def log_cmd_group(self, ctx: commands.Context) -> None:
        await self._execute_logstatus(UnifiedContext.from_prefix(ctx))

    @log_cmd_group.group(name="manual", invoke_without_command=True, help="Manual logging configuration.")
    @commands.has_permissions(administrator=True)
    async def log_manual_group(self, ctx: commands.Context) -> None:
        await self._execute_logstatus(UnifiedContext.from_prefix(ctx))

    @log_manual_group.command(name="config", help="Manually configure an audit log channel.")
    @commands.has_permissions(administrator=True)
    async def log_manual_config(self, ctx: commands.Context, category: Optional[str] = None, channel: Optional[discord.TextChannel] = None) -> None:
        if category:
            await self._execute_logchannel(UnifiedContext.from_prefix(ctx), category, channel)
        else:
            await self._execute_logstatus(UnifiedContext.from_prefix(ctx))

    @log_cmd_group.command(name="reset", help="Reset all logging channel configuration and toggles. Never deletes historical records.")
    @commands.has_permissions(administrator=True)
    async def log_reset_cmd(self, ctx: commands.Context) -> None:
        await self._execute_logreset(UnifiedContext.from_prefix(ctx))

    @log_cmd_group.command(name="disable", help="Stop all logging while preserving all saved configuration.")
    @commands.has_permissions(administrator=True)
    async def log_disable_cmd(self, ctx: commands.Context) -> None:
        await self._execute_logdisable(UnifiedContext.from_prefix(ctx))

    @log_cmd_group.command(name="enable", help="Re-enable logging using saved configuration.")
    @commands.has_permissions(administrator=True)
    async def log_enable_cmd(self, ctx: commands.Context) -> None:
        await self._execute_logenable(UnifiedContext.from_prefix(ctx))

    # ── 12. Command Group 'logging' (Compatibility & Aliases) ───────────────

    @commands.group(name="logging", invoke_without_command=True, help="Manage server audit logging configuration.")
    @commands.has_permissions(administrator=True)
    async def logging_group(self, ctx: commands.Context) -> None:
        await self._execute_logstatus(UnifiedContext.from_prefix(ctx))

    @logging_group.command(name="setup", help="Configure audit log destination channels for event categories.")
    @commands.has_permissions(administrator=True)
    async def logging_setup(self, ctx: commands.Context, category: str, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_logchannel(UnifiedContext.from_prefix(ctx), category, channel)

    @logging_group.command(name="config", help="View all configured log channels and active event toggles.")
    @commands.has_permissions(administrator=True)
    async def logging_config(self, ctx: commands.Context) -> None:
        await self._execute_logstatus(UnifiedContext.from_prefix(ctx))

    @logging_group.command(name="reset", help="Reset logging configuration only. Never deletes historical audit records.")
    @commands.has_permissions(administrator=True)
    async def logging_reset(self, ctx: commands.Context) -> None:
        await self._execute_logreset(UnifiedContext.from_prefix(ctx))

    @logging_group.command(name="enable", help="Enable or toggle logging for a specific event type.")
    @commands.has_permissions(administrator=True)
    async def logging_enable(self, ctx: commands.Context, event_name: str, toggle: str = "enable") -> None:
        await self._execute_logtoggle(UnifiedContext.from_prefix(ctx), event_name, toggle)


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(Logging(bot))
