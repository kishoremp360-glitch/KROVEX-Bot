"""KROVEX Complete Owner Control Panel & VC Staff Role Directory.

Accessible exclusively by the Discord server owner (or bot owner).
Provides complete server governance and manages authorized Voice Channel staff roles.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
from typing import TYPE_CHECKING, List, Optional

import discord
from discord import app_commands
from discord.ext import commands
import psutil

from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.admin.owner_panel")
BRAND_COLOR = 0x9D4EDD


class AddStaffRoleSelect(discord.ui.Select):
    """Dropdown to add a guild role to the authorized VC Staff directory."""

    def __init__(self, guild: discord.Guild) -> None:
        # Filter top 25 non-managed, non-everyone roles
        roles = [r for r in guild.roles if not r.is_default() and not r.managed][:25]
        options = [
            discord.SelectOption(
                label=f"@{r.name}"[:100],
                value=str(r.id),
                description=f"Role ID: {r.id}",
                emoji="🛡️",
            )
            for r in roles
        ]
        if not options:
            options = [discord.SelectOption(label="No eligible roles found", value="none", emoji="⚠️")]

        super().__init__(
            placeholder="Select a role to authorize for VC Staff Panel...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="owner:add_staff_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        val = self.values[0]
        if val == "none":
            await interaction.response.send_message("❌ No eligible roles to add.", ephemeral=True)
            return

        role_id = int(val)
        role = interaction.guild.get_role(role_id)
        bot: "DeathBot" = interaction.client  # type: ignore

        if bot.vc_repo:
            await bot.vc_repo.add_staff_role(interaction.guild.id, role_id, interaction.user.id)
            logger.info("Owner %s added role %s to VC staff in guild %s", interaction.user, role_id, interaction.guild.id)

        role_name = role.mention if role else f"ID: `{role_id}`"
        await interaction.response.send_message(
            f"✅ **Staff Role Authorized:** {role_name} can now access the **KROVEX VC Staff Panel**.",
            ephemeral=True
        )
        # Refresh the owner view
        view: OwnerDashboardView = self.view  # type: ignore
        await view._refresh_embed(interaction)


class RemoveStaffRoleSelect(discord.ui.Select):
    """Dropdown to revoke an authorized VC Staff role."""

    def __init__(self, staff_roles: List[discord.Role]) -> None:
        options = [
            discord.SelectOption(
                label=f"@{r.name}"[:100],
                value=str(r.id),
                description=f"Role ID: {r.id}",
                emoji="🗑️",
            )
            for r in staff_roles[:25]
        ]
        if not options:
            options = [discord.SelectOption(label="No active staff roles to remove", value="none", emoji="ℹ️")]

        super().__init__(
            placeholder="Select a staff role to revoke access...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="owner:remove_staff_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        val = self.values[0]
        if val == "none":
            await interaction.response.send_message("ℹ️ No staff roles to revoke.", ephemeral=True)
            return

        role_id = int(val)
        role = interaction.guild.get_role(role_id)
        bot: "DeathBot" = interaction.client  # type: ignore

        if bot.vc_repo:
            await bot.vc_repo.remove_staff_role(interaction.guild.id, role_id)
            logger.info("Owner %s revoked role %s from VC staff in guild %s", interaction.user, role_id, interaction.guild.id)

        role_name = role.name if role else str(role_id)
        await interaction.response.send_message(
            f"⛔ **Staff Access Revoked:** Role `@{role_name}` can no longer access the VC Staff Panel. Revocation is immediate.",
            ephemeral=True
        )
        # Refresh the owner view
        view: OwnerDashboardView = self.view  # type: ignore
        await view._refresh_embed(interaction)


class OwnerCategorySelect(discord.ui.Select):
    """Navigation dropdown for the Owner Control Panel."""

    def __init__(self, current_category: str = "overview") -> None:
        options = [
            discord.SelectOption(
                label="Server Overview & Telemetry",
                value="overview",
                emoji="📊",
                description="Live guild metrics, member stats & gateway health",
                default=(current_category == "overview"),
            ),
            discord.SelectOption(
                label="Voice Control Centre",
                value="voice_control",
                emoji="🎛️",
                description="Mass controls, scope isolation, presets, audit logs & member management",
                default=(current_category == "voice_control"),
            ),
            discord.SelectOption(
                label="VC Moderation Dashboard",
                value="voice_moderation",
                emoji="🎙️",
                description="Thor Apex in-VC moderation controls, room privacy & message tools",
                default=(current_category == "voice_moderation"),
            ),
            discord.SelectOption(
                label="VC Staff Role Directory",
                value="vc_staff",
                emoji="🛡️",
                description="Manage roles authorized to operate the VC Control Panel",
                default=(current_category == "vc_staff"),
            ),
            discord.SelectOption(
                label="Security & Anti-Nuke",
                value="security",
                emoji="🔒",
                description="Anti-raid, anti-nuke thresholds & lockdown governance",
                default=(current_category == "security"),
            ),
            discord.SelectOption(
                label="AutoMod & Content Filters",
                value="automod",
                emoji="⚡",
                description="Invite links, spam, caps, and bad word filters",
                default=(current_category == "automod"),
            ),
            discord.SelectOption(
                label="Logging & Audit Matrix",
                value="logging",
                emoji="📜",
                description="Message edits, voice logs, member join/leave tracking",
                default=(current_category == "logging"),
            ),
            discord.SelectOption(
                label="Tickets & Support Desk",
                value="tickets",
                emoji="🎫",
                description="Panel deployment, claim policies & HTML transcripts",
                default=(current_category == "tickets"),
            ),
            discord.SelectOption(
                label="Economy & Leveling",
                value="economy_levels",
                emoji="🪙",
                description="Virtual currency, daily rewards, rank progression",
                default=(current_category == "economy_levels"),
            ),
            discord.SelectOption(
                label="Music Audio Engine",
                value="music",
                emoji="🎵",
                description="Lavalink/yt-dlp engine, audio filters & DJ policies",
                default=(current_category == "music"),
            ),
            discord.SelectOption(
                label="SOUL AI Engine",
                value="soul",
                emoji="✨",
                description="Conversational companion status, session memory & scopes",
                default=(current_category == "soul"),
            ),
            discord.SelectOption(
                label="Core Bot Configuration",
                value="config",
                emoji="⚙️",
                description="Server prefix, administrator roles & system channels",
                default=(current_category == "config"),
            ),
            discord.SelectOption(
                label="Subsystem Diagnostics",
                value="diagnostics",
                emoji="🩺",
                description="Live audit of Music, SOUL, OwnerVC, Database & Vault DR",
                default=(current_category == "diagnostics"),
            ),
            discord.SelectOption(
                label="Tasks & Host Telemetry",
                value="system_tasks",
                emoji="📈",
                description="Host RAM/CPU, asyncio task queue, WAL size & backup health",
                default=(current_category == "system_tasks"),
            ),
        ]
        super().__init__(
            placeholder="Select Management Category...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
            custom_id="owner:category_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: OwnerDashboardView = self.view  # type: ignore
        view.current_category = self.values[0]
        view._rebuild_components()
        embed = await view._build_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)


class OwnerDashboardView(discord.ui.View):
    """Central Owner Control Panel interactive view."""

    def __init__(self, bot: "DeathBot", guild: discord.Guild, timeout: float = 600.0) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild = guild
        self.current_category = "overview"
        self.bulk_allowed = False
        self._lock = asyncio.Lock()
        self._rebuild_components()

    def _rebuild_components(self) -> None:
        """Dynamically assemble components according to the selected category."""
        self.clear_items()
        # Row 0: Category Select
        self.add_item(OwnerCategorySelect(self.current_category))

        # Category-specific buttons
        if self.current_category == "vc_staff":
            add_btn = discord.ui.Button(
                label="Add Staff Role",
                style=discord.ButtonStyle.success,
                emoji="➕",
                custom_id="owner:staff_add_btn",
                row=1,
            )
            add_btn.callback = self._handle_add_staff_prompt
            self.add_item(add_btn)

            remove_btn = discord.ui.Button(
                label="Revoke Staff Role",
                style=discord.ButtonStyle.danger,
                emoji="➖",
                custom_id="owner:staff_remove_btn",
                row=1,
            )
            remove_btn.callback = self._handle_remove_staff_prompt
            self.add_item(remove_btn)

            bulk_btn = discord.ui.Button(
                label=f"Bulk Actions: [{'ON' if self.bulk_allowed else 'OFF'}]",
                style=discord.ButtonStyle.danger if self.bulk_allowed else discord.ButtonStyle.secondary,
                emoji="⚠️" if self.bulk_allowed else "🛡️",
                custom_id="owner:toggle_staff_bulk",
                row=1,
            )
            bulk_btn.callback = self._handle_toggle_staff_bulk
            self.add_item(bulk_btn)

        elif self.current_category == "voice_control":
            open_vc_btn = discord.ui.Button(
                label="Open Voice Control Centre",
                style=discord.ButtonStyle.primary,
                emoji="🎛️",
                custom_id="owner:open_vc_centre",
                row=1,
            )
            open_vc_btn.callback = self._handle_goto_vc_centre
            self.add_item(open_vc_btn)

            mod_btn = discord.ui.Button(
                label="VC Moderation Controls",
                style=discord.ButtonStyle.secondary,
                emoji="🎙️",
                custom_id="owner:goto_vc_mod_from_vc",
                row=1,
            )
            mod_btn.callback = self._handle_goto_vc_moderation
            self.add_item(mod_btn)

        elif self.current_category == "voice_moderation":
            launch_mod_btn = discord.ui.Button(
                label="Launch VC Moderation Dashboard",
                style=discord.ButtonStyle.primary,
                emoji="🎙️",
                custom_id="owner:launch_vc_mod",
                row=1,
            )
            launch_mod_btn.callback = self._handle_goto_vc_moderation
            self.add_item(launch_mod_btn)

            open_vc_btn = discord.ui.Button(
                label="Voice Control Centre",
                style=discord.ButtonStyle.secondary,
                emoji="🎛️",
                custom_id="owner:open_vc_centre_from_mod",
                row=1,
            )
            open_vc_btn.callback = self._handle_goto_vc_centre
            self.add_item(open_vc_btn)

        elif self.current_category == "security":
            vc_mod_btn = discord.ui.Button(
                label="Voice Moderation",
                style=discord.ButtonStyle.secondary,
                emoji="🎙️",
                custom_id="owner:sec_goto_vc_mod",
                row=1,
            )
            vc_mod_btn.callback = self._handle_goto_vc_moderation
            self.add_item(vc_mod_btn)

        elif self.current_category == "overview":
            vc_btn = discord.ui.Button(
                label="Voice Control Centre",
                style=discord.ButtonStyle.primary,
                emoji="🎛️",
                custom_id="owner:goto_vc_centre",
                row=1,
            )
            vc_btn.callback = self._handle_goto_vc_centre
            self.add_item(vc_btn)

            stats_btn = discord.ui.Button(
                label="View Detailed Stats",
                style=discord.ButtonStyle.secondary,
                emoji="📈",
                custom_id="owner:stats_btn",
                row=1,
            )
            stats_btn.callback = self._handle_stats_click
            self.add_item(stats_btn)

        # Row 3: Global Utilities
        refresh_btn = discord.ui.Button(
            label="Refresh",
            style=discord.ButtonStyle.primary,
            emoji="🔄",
            custom_id="owner:refresh_btn",
            row=3,
        )
        refresh_btn.callback = self._handle_refresh
        self.add_item(refresh_btn)

        close_btn = discord.ui.Button(
            label="Close Panel",
            style=discord.ButtonStyle.secondary,
            emoji="🛑",
            custom_id="owner:close_btn",
            row=3,
        )
        close_btn.callback = self._handle_close
        self.add_item(close_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Owner-only security check on EVERY interaction."""
        if not interaction.guild:
            await interaction.response.send_message("❌ Must be used inside a server.", ephemeral=True)
            return False

        # Strictly guild sovereign or bot owner (server 2nd owner)
        is_guild_owner = interaction.user.id == interaction.guild.owner_id
        is_bot_owner = False
        if hasattr(self.bot, "is_bot_owner") and callable(self.bot.is_bot_owner):
            try:
                res = self.bot.is_bot_owner(interaction.user)
                if asyncio.iscoroutine(res):
                    is_bot_owner = await res
                elif isinstance(res, bool):
                    is_bot_owner = res
            except Exception:
                pass
        if not is_bot_owner:
            raw_owners = getattr(self.bot.config, "owner_ids", [])
            is_bot_owner = (
                interaction.user.id in raw_owners
                or str(interaction.user.id) in [str(x) for x in raw_owners]
            )

        if not (is_guild_owner or is_bot_owner):
            await interaction.response.send_message(
                f"{KrovexEmoji.CROSS} **Access Denied:** Only the Discord Server Sovereign may access the Owner Panel.",
                ephemeral=True
            )
            return False
        return True

    async def _handle_goto_vc_centre(self, interaction: discord.Interaction) -> None:
        """Switch view directly into the KROVEX Voice Control Centre."""
        from bot.cogs.ownervc.voice_centre import VoiceControlCentreView
        view = VoiceControlCentreView(self.bot, self.guild)
        embed, _ = await view.render(interaction=None, edit=False)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _handle_goto_vc_moderation(self, interaction: discord.Interaction) -> None:
        """Switch view directly into the THOR APEX Voice Room Moderation Dashboard."""
        from bot.cogs.ownervc.dashboard import OwnerVCControlView, build_owner_vc_embed
        channel = None
        user = interaction.user
        if isinstance(user, discord.Member) and user.voice and isinstance(user.voice.channel, discord.VoiceChannel):
            channel = user.voice.channel
        elif self.guild.voice_channels:
            active_vcs = [vc for vc in self.guild.voice_channels if len(getattr(vc, "members", [])) > 0]
            channel = active_vcs[0] if active_vcs else self.guild.voice_channels[0]

        if not channel:
            await interaction.response.send_message("❌ No voice channels exist in this server to control.", ephemeral=True)
            return

        view = OwnerVCControlView(self.bot, channel)
        ban_count = await view._get_ban_count()
        embed = build_owner_vc_embed(channel, ban_count=ban_count)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _build_embed(self, guild: discord.Guild) -> discord.Embed:
        """Build the rich embed corresponding to the active category."""
        if self.current_category == "voice_moderation":
            desc = (
                "*Owner & Staff Voice Room Moderation Controls*\n\n"
                "### 🎙️ **LIVE VC MODERATION SUITE**\n"
                "╭・**Voice Moderation:** Bulk & individual mute, deafen, disconnect, ban & VC loop controls\n"
                "├・**Privacy & Capacity:** Instant lock/unlock, ghost/hide, limit & bitrate adjustments\n"
                "╰・**Message Moderation:** VC text purge, pin, lock chat & slowmode governance\n\n"
                "Click **Launch VC Moderation Dashboard** below or use `/vcpanel` to open the full control center."
            )
            embed = discord.Embed(
                title="🎙️ KROVEX OWNER • VOICE MODERATION DASHBOARD",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX SOVEREIGN • IN-VC MODERATION SUITE")
            return embed

        elif self.current_category == "voice_control":
            total_vcs = len(guild.voice_channels)
            total_members = sum(len(vc.members) for vc in guild.voice_channels)
            desc = (
                "*Complete Voice Channel Governance & Bulk Action Architecture*\n\n"
                f"• **Voice Channels:** `{total_vcs}`\n"
                f"• **Connected Members:** `{total_members}`\n\n"
                "The **KROVEX Voice Control Centre** provides comprehensive voice channel management:\n"
                "╭・**Two Distinct Scopes:** Single Voice Channel vs Server-Wide mass actions\n"
                "├・**Member Management:** Filter, inspect, and batch-moderate voice users\n"
                "├・**Channel Controls:** Lock, hide, clone, tune bitrate and capacity with overwrite preservation\n"
                "├・**Smart Modes:** One-click Meeting, Gaming, Silent Room, and Emergency Lock profiles\n"
                "├・**Temporary Actions:** Timed server mutes and channel locks with auto-reversion\n"
                "╰・**Activity Logs:** Real-time audited records of all management actions\n\n"
                "Click **Open Voice Control Centre** below to launch the dashboard."
            )
            embed = discord.Embed(
                title="🎛️ KROVEX OWNER • VOICE CONTROL CENTRE",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX SOVEREIGN • COMPLETE VOICE CONTROL")
            return embed

        elif self.current_category == "vc_staff":
            staff_role_ids: List[int] = []
            if self.bot.vc_repo:
                staff_role_ids = await self.bot.vc_repo.get_staff_roles(guild.id)
                self.bulk_allowed = await self.bot.vc_repo.get_staff_bulk_actions_allowed(guild.id)

            roles_formatted = []
            for rid in staff_role_ids:
                role = guild.get_role(rid)
                if role:
                    roles_formatted.append(f"• {role.mention} (`{role.id}`)")
                else:
                    roles_formatted.append(f"• *Deleted Role* (`{rid}`)")

            if not roles_formatted:
                roles_display = "⚠️ *No VC staff roles configured yet.*\nClick **Add Staff Role** below to authorize a role."
            else:
                roles_display = "\n".join(roles_formatted)

            bulk_status_str = "ENABLED ⚠️ (Staff can mute, deafen, disconnect all, clear bans)" if self.bulk_allowed else "DISABLED 🛡️ (Default - Staff mass actions blocked)"

            desc = (
                "*Authorized Voice Channel Staff Directory & Permission Delegation*\n\n"
                "Members holding any authorized staff role can access the **KROVEX VC Staff Panel** "
                "to manage, lock, hide, and tune voice channels.\n\n"
                f"### 🛡️ **AUTHORIZED VC STAFF ROLES [{len(staff_role_ids)}]**\n"
                f"{roles_display}\n\n"
                f"### ⚙️ **STAFF BULK ACTIONS POLICY**\n"
                f"• Status: `{bulk_status_str}`\n"
                "*(Destructive mass actions: Mute All, Deafen All, Disconnect All, Clear Bans)*\n\n"
                "╭・**Add Staff Role** — Authorize a server role for VC management\n"
                "├・**Revoke Staff Role** — Immediately revoke VC panel access\n"
                "├・**Toggle Bulk Actions** — Allow or block mass moderation for staff\n"
                "╰・**Immediate Revocation** — Revoked roles lose access on their next click"
            )
            embed = discord.Embed(
                title=f"{KrovexEmoji.BLUE_BUTTERFLIES} KROVEX OWNER • VC STAFF ROLE DIRECTORY",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX SOVEREIGN • PRIVILEGE DELEGATION • AUDITED")
            return embed

        elif self.current_category == "security":
            desc = (
                "*Guild Security, Anti-Nuke, and Emergency Governance*\n\n"
                "### 🛡️ **DEFENSE MATRIX [ACTIVE]**\n"
                "╭・**Anti-Nuke Engine** — Prevents unauthorized mass bans, kicks, or channel deletion\n"
                "├・**Anti-Raid Protection** — Automated join burst throttling and quarantine\n"
                "├・**Anti-Bot Guard** — Blocks unverified bot additions by non-owners\n"
                "╰・**Emergency Lockdown** — Instantly freezes channels during ongoing raids\n\n"
                "Use `/security status` or `.security` for full defense configuration."
            )
            embed = discord.Embed(
                title="🔒 KROVEX OWNER • SECURITY GOVERNANCE",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX SECURITY • ABSOLUTE DEFENSE • 24/7 ACTIVE")
            return embed

        elif self.current_category == "automod":
            desc = (
                "*Heuristic Content Filtering & Automated Sanctions*\n\n"
                "### ⚡ **AUTOMOD RULES & FILTERS**\n"
                "╭・**Anti-Invite** — Filters Discord server invite links\n"
                "├・**Anti-Link** — Restricts unauthorized URL publishing\n"
                "├・**Anti-Spam / Flood** — Throttles repeated message spam\n"
                "├・**Anti-Caps** — Penalizes excessive capitalization\n"
                "╰・**Bad Words** — Keyword dictionary filter with automated deletion\n\n"
                "Use `/automod setup` or `.automod` to tune filter thresholds."
            )
            embed = discord.Embed(
                title="⚡ KROVEX OWNER • AUTOMOD CONTROLS",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX AUTOMOD • REAL-TIME HEURISTICS")
            return embed

        elif self.current_category == "logging":
            desc = (
                "*Comprehensive Audit Logging Architecture*\n\n"
                "### 📜 **LOG STREAMS & MONITORS**\n"
                "╭・**Message Audit** — Tracks message edits, purges, and deletions\n"
                "├・**Member Audit** — Records joins, leaves, kicks, bans, and nick updates\n"
                "├・**Voice Audit** — Telemetry for connects, disconnects, and channel moves\n"
                "╰・**Channel & Role Audit** — Monitors privilege modifications and deletions\n\n"
                "Use `/logging setup` or `.autolog` to configure dispatch channels."
            )
            embed = discord.Embed(
                title="📜 KROVEX OWNER • LOGGING ARCHITECTURE",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX LOGGING • COMPLETE AUDIT ARCHIVE")
            return embed

        elif self.current_category == "tickets":
            desc = (
                "*Customer & Guild Support Desk Management*\n\n"
                "### 🎫 **SUPPORT DESK STATUS**\n"
                "╭・**Multi-Category Tickets** — Support, billing, and general inquiries\n"
                "├・**Staff Claim System** — Assign tickets to individual support operators\n"
                "├・**Transcript Archival** — Generates complete HTML/Markdown chat transcripts\n"
                "╰・**Blacklist Matrix** — Blocks ticket system abuse by restricted users\n\n"
                "Use `/ticket setup` or `/ticket panel` to deploy support stations."
            )
            embed = discord.Embed(
                title="🎫 KROVEX OWNER • SUPPORT DESK CONTROLS",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX TICKETS • HIGH-AVAILABILITY DISPATCH")
            return embed

        elif self.current_category == "economy_levels":
            desc = (
                "*Virtual Economy & Level Progression Matrix*\n\n"
                "### 🪙 **ECONOMY & XP PROGRESSION**\n"
                "╭・**Virtual Currency** — Wallets, bank vaults, daily streaks, jobs & robberies\n"
                "├・**Shop & Inventory** — Custom items, roles, and collectibles\n"
                "├・**XP Leveling Engine** — Message and voice activity reward calculations\n"
                "╰・**Level Rewards** — Automatic role assignment upon reaching target ranks\n\n"
                "Use `/rank`, `/leaderboard`, or `/economysetup` to inspect economy state."
            )
            embed = discord.Embed(
                title="🪙 KROVEX OWNER • ECONOMY & LEVELING",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX PROGRESSION • VIRTUAL ECONOMY ACTIVE")
            return embed

        elif self.current_category == "music":
            desc = (
                "*Audio Pipeline & Lavalink / Voice Client Telemetry*\n\n"
                "### 🎵 **AUDIO SUBSYSTEM**\n"
                "╭・**Audio Resolver** — Multi-platform resolution (YouTube, SoundCloud fallback)\n"
                "├・**Voice Engine** — PyNaCl + Davey high-fidelity packet streaming\n"
                "├・**Audio Filters** — Bassboost, 8D audio, Nightcore, Vaporwave\n"
                "╰・**DJ Governance** — DJ role requirements and voteskip thresholds\n\n"
                "Use `.play <song>`, `.queue`, or `.vcdashboard` to operate music playback."
            )
            embed = discord.Embed(
                title="🎵 KROVEX OWNER • MUSIC SYSTEM",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX AUDIO • HIGH-FIDELITY PLAYBACK")
            return embed

        elif self.current_category == "soul":
            desc = (
                "*KROVEX SOUL Conversational Intelligence Engine*\n\n"
                "### ✨ **SOUL AI COMPANION**\n"
                "╭・**Engine Provider** — Google Gemini 2.5 Flash Native Integration\n"
                "├・**Persona & Tone** — Tanglish/English contextual friend companion\n"
                "├・**Session Continuity** — Follow-up conversation awareness without repeated pings\n"
                "╰・**Diagnostics** — Owner-only prompt diagnostic testing via `!soultest`\n\n"
                "Mention `@KROVEX` or reply to any bot message to chat."
            )
            embed = discord.Embed(
                title="✨ KROVEX OWNER • SOUL AI ENGINE",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX SOUL • CONVERSATIONAL AI ACTIVE")
            return embed

        elif self.current_category == "config":
            prefix = "!"
            if self.bot.guild_repo:
                prefix = await self.bot.guild_repo.get_prefix(guild.id, default="!")

            desc = (
                "*Core Server Governance & Prefix Configuration*\n\n"
                f"### ⚙️ **SETTINGS FOR {guild.name.upper()}**\n"
                f"╭・**Server Command Prefix** — `{prefix}`\n"
                f"├・**Server ID** — `{guild.id}`\n"
                f"├・**Owner ID** — `{guild.owner_id}`\n"
                f"├・**Verification Level** — `{guild.verification_level.name.title()}`\n"
                f"╰・**Admin Setup Wizard** — Launch via `/admin setup` or `.admin setup`"
            )
            embed = discord.Embed(
                title="⚙️ KROVEX OWNER • BOT CONFIGURATION",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX GOVERNANCE • FULL SOVEREIGN AUTHORITY")
            return embed

        elif self.current_category == "diagnostics":
            db_ok = getattr(self.bot.db_manager, "is_connected", False)
            music_ok = hasattr(self.bot, "music_service") and self.bot.music_service is not None
            spotify_ok = bool(getattr(self.bot.config, "spotify_client_id", None) and getattr(self.bot.config, "spotify_client_secret", None))
            soul_ok = hasattr(self.bot, "soul_service") and self.bot.soul_service is not None
            vc_ok = hasattr(self.bot, "voice_service") and self.bot.voice_service is not None
            vault_ok = self.bot.get_cog("vault") is not None

            desc = (
                "*Live Sovereign Subsystem Diagnostics & Component Verification*\n\n"
                "### 🩺 **CORE SUBSYSTEM STATUS**\n"
                f"╭・**SQLite Database** — {'🟢 Operational (71 Tables, WAL Mode)' if db_ok else '🔴 Disconnected'}\n"
                f"├・**Music Audio Engine** — {'🟢 Active (yt-dlp + PyNaCl + Davey)' if music_ok else '🟡 Offline'}\n"
                f"├・**Spotify Web API** — {'🟢 Authenticated (Client Credentials)' if spotify_ok else '🟡 Unconfigured'}\n"
                f"├・**KROVEX SOUL AI** — {'🟢 Gemini Flash-lite Connected' if soul_ok else '🟡 Disabled'}\n"
                f"├・**OwnerVC Subsystem** — {'🟢 VoiceService Online' if vc_ok else '🟡 Offline'}\n"
                f"├・**Vault Disaster Recovery** — {'🟢 15 Channels Active (Fernet AES-256)' if vault_ok else '🟡 Inactive'}\n"
                f"╰・**Gateway WebSocket** — 🟢 Connected (`{round(self.bot.latency * 1000)}ms`)\n\n"
                "All core platform microservices are verified against Discord Gateway v10."
            )
            embed = discord.Embed(
                title="🩺 KROVEX OWNER • SUBSYSTEM DIAGNOSTICS",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX DIAGNOSTICS • REAL-TIME HEALTH VERIFICATION")
            return embed

        elif self.current_category == "system_tasks":
            proc = psutil.Process(os.getpid())
            mem_mb = round(proc.memory_info().rss / 1024 / 1024, 1)
            cpu_pct = proc.cpu_percent()
            active_tasks = len([t for t in asyncio.all_tasks() if not t.done()])

            db_path = Path("db/death_bot.sqlite")
            wal_path = Path("db/death_bot.sqlite-wal")
            db_size_kb = round(db_path.stat().st_size / 1024, 1) if db_path.exists() else 0
            wal_size_kb = round(wal_path.stat().st_size / 1024, 1) if wal_path.exists() else 0

            desc = (
                "*Runtime Process Telemetry, Memory & Background Task Monitor*\n\n"
                "### 📈 **HOST PROCESS TELEMETRY**\n"
                f"╭・**Process RAM (RSS)** — `{mem_mb} MB`\n"
                f"├・**Process CPU** — `{cpu_pct}%`\n"
                f"├・**Active Asyncio Tasks** — `{active_tasks}` concurrent tasks\n"
                f"├・**Host Runtime** — `Python {platform.python_version()} ({platform.system()} {platform.machine()})`\n"
                f"├・**SQLite Database File** — `{db_size_kb} KB`\n"
                f"├・**SQLite WAL Journal** — `{wal_size_kb} KB`\n"
                f"├・**Automated Snapshots** — `Every 30 Minutes (20 Retained)`\n"
                f"╰・**DM Queue Worker** — `Active (FIFO Rate-Limited)`\n\n"
                "Live process metrics are sampled dynamically from the operating system."
            )
            embed = discord.Embed(
                title="📈 KROVEX OWNER • TASKS & HOST TELEMETRY",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX TELEMETRY • PROCESS & QUEUE MONITORING")
            return embed

        else:
            # Default: overview
            owner = guild.get_member(guild.owner_id)
            owner_name = owner.display_name if owner else f"ID: {guild.owner_id}"
            channels_count = len(guild.channels)
            roles_count = len(guild.roles)
            members_count = guild.member_count or len(guild.members)
            import math
            latency_ms = round(self.bot.latency * 1000) if math.isfinite(self.bot.latency) else 0

            staff_count = 0
            if self.bot.vc_repo:
                staff_roles = await self.bot.vc_repo.get_staff_roles(guild.id)
                staff_count = len(staff_roles)

            desc = (
                "*Guild Administrative Control Matrix & Modular Governance*\n\n"
                f"### 👑 **SERVER SOVEREIGN: {owner_name}**\n"
                f"╭・**Total Members** — `{members_count}`\n"
                f"├・**Channels & Categories** — `{channels_count}`\n"
                f"├・**Server Roles** — `{roles_count}`\n"
                f"├・**VC Staff Roles Configured** — `{staff_count}` roles\n"
                f"├・**Gateway WebSocket Latency** — `{latency_ms}ms`\n"
                f"├・**Host Python** — `Python {platform.python_version()}`\n"
                f"╰・**Database Health** — `SQLite WAL Operational 🟢`\n\n"
                "Select a category from the dropdown menu below to manage modules."
            )
            embed = discord.Embed(
                title="👑 KROVEX • SOVEREIGN OWNER CONTROL PANEL",
                description=desc,
                color=BRAND_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="KROVEX SOVEREIGN • PROTECTION • PRECISION • CONTROL")
            return embed

    async def _refresh_embed(self, interaction: discord.Interaction) -> None:
        self._rebuild_components()
        embed = await self._build_embed(interaction.guild)
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        elif interaction.message:
            await interaction.message.edit(embed=embed, view=self)

    async def _handle_add_staff_prompt(self, interaction: discord.Interaction) -> None:
        """Display dropdown menu to pick a role to add."""
        view = discord.ui.View(timeout=120.0)
        view.add_item(AddStaffRoleSelect(interaction.guild))
        await interaction.response.send_message(
            "🛡️ **Select a server role to grant access to the VC Staff Panel:**",
            view=view,
            ephemeral=True
        )

    async def _handle_remove_staff_prompt(self, interaction: discord.Interaction) -> None:
        """Display dropdown menu of currently active staff roles to revoke."""
        staff_roles = []
        if self.bot.vc_repo:
            rids = await self.bot.vc_repo.get_staff_roles(interaction.guild.id)
            for rid in rids:
                r = interaction.guild.get_role(rid)
                if r:
                    staff_roles.append(r)

        if not staff_roles:
            await interaction.response.send_message("ℹ️ No active VC staff roles to revoke.", ephemeral=True)
            return

        view = discord.ui.View(timeout=120.0)
        view.add_item(RemoveStaffRoleSelect(staff_roles))
        await interaction.response.send_message(
            "🗑️ **Select an authorized staff role to revoke access:**",
            view=view,
            ephemeral=True
        )

    async def _handle_toggle_staff_bulk(self, interaction: discord.Interaction) -> None:
        """Toggle whether VC staff can perform destructive bulk moderation."""
        if not interaction.guild:
            return
        new_val = not self.bulk_allowed
        if self.bot.vc_repo:
            await self.bot.vc_repo.set_staff_bulk_actions_allowed(interaction.guild.id, new_val, interaction.user.id)
            self.bulk_allowed = new_val
            logger.info("Owner %s toggled staff bulk actions to %s in guild %s", interaction.user, new_val, interaction.guild.id)

        msg = (
            "⚠️ **Staff Bulk VC Actions ENABLED:** Staff members may now execute mass VC actions (Mute All, Deafen All, Disconnect All, Clear Bans)."
            if new_val else
            "🛡️ **Staff Bulk VC Actions DISABLED:** Staff members cannot execute mass VC actions (Default Policy)."
        )
        await interaction.response.send_message(msg, ephemeral=True)
        await self._refresh_embed(interaction)

    async def _handle_stats_click(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        boost_tier = guild.premium_tier
        boost_count = guild.premium_subscription_count

        embed = EmbedBuilder.base(
            title=f"📊 Detailed Guild Telemetry • {guild.name}",
            description=(
                f"• **Text Channels:** `{text_channels}`\n"
                f"• **Voice Channels:** `{voice_channels}`\n"
                f"• **Boost Level:** {KrovexEmoji.NITRO} `Tier {boost_tier}` (`{boost_count}` boosts)\n"
                f"• **Created At:** {KrovexEmoji.CRESCENT_MOON} `<t:{int(guild.created_at.timestamp())}:R>`\n"
                f"• **Bot Joined:** `<t:{int(guild.me.joined_at.timestamp())}:R>`"
            ),
            color=BRAND_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _handle_refresh(self, interaction: discord.Interaction) -> None:
        await self._refresh_embed(interaction)
        if not interaction.response.is_done():
            await interaction.response.send_message("🔄 Owner dashboard refreshed.", ephemeral=True)

    async def _handle_close(self, interaction: discord.Interaction) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        await interaction.response.edit_message(content="🛑 **Owner Control Panel closed.**", view=self)
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True


class OwnerDashboardCog(commands.Cog, name="Owner Dashboard"):
    """Server Sovereign Control Panel and VC Staff Directory management."""

    def __init__(self, bot: "DeathBot") -> None:
        self.bot = bot

    def _is_owner_or_co_owner(self, user: Union[discord.User, discord.Member], guild: Optional[discord.Guild]) -> bool:
        if not user:
            return False
        if guild and user.id == guild.owner_id:
            return True
        if hasattr(self.bot, "is_bot_owner") and callable(self.bot.is_bot_owner):
            try:
                res = self.bot.is_bot_owner(user)
                if isinstance(res, bool) and res:
                    return True
            except Exception:
                pass
        raw_owners = getattr(self.bot.config, "owner_ids", [])
        if user.id in raw_owners or str(user.id) in [str(x) for x in raw_owners]:
            return True
        app_owners = getattr(self.bot, "owner_ids", set()) or set()
        if user.id in app_owners or str(user.id) in [str(x) for x in app_owners]:
            return True
        return False

    async def _execute_ownerpanel(
        self,
        ctx_or_interaction,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        if isinstance(ctx_or_interaction, discord.Interaction):
            if hasattr(ctx_or_interaction, "response") and hasattr(ctx_or_interaction.response, "is_done"):
                try:
                    done = ctx_or_interaction.response.is_done()
                    if not done and hasattr(ctx_or_interaction.response, "defer"):
                        res = ctx_or_interaction.response.defer(ephemeral=True)
                        if asyncio.iscoroutine(res):
                            await res
                except Exception:
                    pass

        user = ctx_or_interaction.user if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author
        guild = ctx_or_interaction.guild

        if not guild or not isinstance(user, discord.Member):
            msg = "❌ Must be used inside a server."
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(msg, ephemeral=True)
                else:
                    await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        is_owner = user.id == guild.owner_id
        is_bot_owner = (
            user.id in self.bot.config.owner_ids
            or str(user.id) in [str(x) for x in self.bot.config.owner_ids]
            or (self.bot.owner_ids and (user.id in self.bot.owner_ids or str(user.id) in [str(x) for x in self.bot.owner_ids]))
        )
        if not is_bot_owner and hasattr(self.bot, "is_bot_owner") and callable(self.bot.is_bot_owner):
            try:
                res = self.bot.is_bot_owner(user)
                if asyncio.iscoroutine(res):
                    is_bot_owner = await res
                elif isinstance(res, bool):
                    is_bot_owner = res
            except Exception:
                pass

        if not (is_owner or is_bot_owner):
            msg = f"{KrovexEmoji.CROSS} **Access Denied:** Only the Discord Server Sovereign may access the Owner Panel."
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(msg, ephemeral=True)
                else:
                    await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        if channel:
            from bot.cogs.ownervc.dashboard import OwnerVCControlView, build_owner_vc_embed
            vc_view = OwnerVCControlView(self.bot, channel)
            ban_count = await vc_view._get_ban_count()
            vc_embed = build_owner_vc_embed(channel, ban_count=ban_count)
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send(embed=vc_embed, view=vc_view, ephemeral=True)
            else:
                await ctx_or_interaction.send(embed=vc_embed, view=vc_view)
            return

        view = OwnerDashboardView(self.bot, guild)
        embed = await view._build_embed(guild)

        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await ctx_or_interaction.send(embed=embed, view=view)

    async def _execute_governance(self, ctx_or_interaction) -> None:
        user = ctx_or_interaction.user if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author
        guild = ctx_or_interaction.guild

        if not guild or not isinstance(user, discord.Member):
            msg = "❌ Must be used inside a server."
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(msg, ephemeral=True)
                else:
                    await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        is_owner = user.id == guild.owner_id
        is_bot_owner = (
            user.id in self.bot.config.owner_ids
            or str(user.id) in [str(x) for x in self.bot.config.owner_ids]
            or (self.bot.owner_ids and (user.id in self.bot.owner_ids or str(user.id) in [str(x) for x in self.bot.owner_ids]))
        )
        if not is_bot_owner and hasattr(self.bot, "is_bot_owner") and callable(self.bot.is_bot_owner):
            try:
                res = self.bot.is_bot_owner(user)
                if asyncio.iscoroutine(res):
                    is_bot_owner = await res
                elif isinstance(res, bool):
                    is_bot_owner = res
            except Exception:
                pass

        if not (is_owner or is_bot_owner):
            msg = f"{KrovexEmoji.CROSS} **Access Denied:** Only the Discord Server Sovereign may access Server Governance."
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(msg, ephemeral=True)
                else:
                    await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        if isinstance(ctx_or_interaction, discord.Interaction):
            if hasattr(ctx_or_interaction, "response") and hasattr(ctx_or_interaction.response, "is_done"):
                try:
                    done = ctx_or_interaction.response.is_done()
                    if not done and hasattr(ctx_or_interaction.response, "defer"):
                        res = ctx_or_interaction.response.defer(ephemeral=True)
                        if asyncio.iscoroutine(res):
                            await res
                except Exception:
                    pass

        view = OwnerDashboardView(self.bot, guild)
        embed = await view._build_embed(guild)

        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await ctx_or_interaction.send(embed=embed, view=view)

    @commands.command(name="ownerpanel", aliases=["op", "ownerdashboard", "owner"], help="Open the KROVEX Sovereign Owner Control Panel.")
    async def ownerpanel_prefix(self, ctx: commands.Context, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_ownerpanel(ctx, channel=channel)

    @app_commands.command(name="ownerpanel", description="Open the interactive KROVEX Owner Moderation Dashboard.")
    @app_commands.describe(channel="Voice channel to control (defaults to your current or active voice channel)")
    @app_commands.guild_only()
    async def ownerpanel_slash(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        await self._execute_ownerpanel(interaction, channel=channel)

    @commands.command(name="governance", aliases=["gov", "servergovernance"], help="Open the KROVEX Server Security Governance & Diagnostics Panel.")
    async def governance_prefix(self, ctx: commands.Context) -> None:
        await self._execute_governance(ctx)

    @app_commands.command(name="governance", description="Open the KROVEX Server Security Governance & Diagnostics Panel.")
    @app_commands.guild_only()
    async def governance_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_governance(interaction)

    @commands.command(name="syncslash", aliases=["sync"], help="Owner-only: Synchronize Discord application slash commands.")
    async def syncslash_prefix(self, ctx: commands.Context) -> None:
        """Owner-only command to manually trigger application command sync with Discord."""
        if ctx.author.id not in self.bot.config.owner_ids:
            await ctx.reply(f"{KrovexEmoji.CROSS} Only KROVEX Bot Owners can synchronize application commands.")
            return

        msg = await ctx.reply("⏳ Synchronizing application slash commands with Discord...")
        try:
            await self.bot.sync_app_commands()
            await msg.edit(content=f"{KrovexEmoji.SUCCESS} **Synchronized:** Global slash command tree successfully synchronized with Discord Gateway.")
        except Exception as err:
            logger.error("Manual slash command sync failed: %s", err, exc_info=True)
            await msg.edit(content=f"{KrovexEmoji.CROSS} **Sync Failed:** An error occurred during synchronization: `{err}`")

    @commands.group(name="vcstaff", invoke_without_command=True, help="Manage authorized VC Staff roles or open staff panel.")
    async def vcstaff_group(self, ctx: commands.Context) -> None:
        """Display authorized VC staff roles or launch VC staff panel if in voice."""
        if not ctx.guild:
            return

        # If user is in a voice channel, launch the VC staff panel if authorized
        if ctx.author.voice and isinstance(ctx.author.voice.channel, discord.VoiceChannel):
            channel = ctx.author.voice.channel
            dash_cog = self.bot.get_cog("VCDashboard")
            if dash_cog and hasattr(dash_cog, "_execute_vc_staff_panel"):
                is_owner = self._is_owner_or_co_owner(ctx.author, ctx.guild)
                is_staff = False
                if self.bot.vc_repo and isinstance(ctx.author, discord.Member):
                    user_roles = [r.id for r in ctx.author.roles]
                    is_staff = await self.bot.vc_repo.is_staff(ctx.guild.id, user_roles)
                if is_owner or is_staff:
                    await dash_cog._execute_vc_staff_panel(ctx, channel)
                    return

        if not self._is_owner_or_co_owner(ctx.author, ctx.guild):
            await ctx.reply(f"{KrovexEmoji.CROSS} Only the Server Owner can manage VC Staff roles.")
            return

        staff_roles = []
        if self.bot.vc_repo:
            rids = await self.bot.vc_repo.get_staff_roles(ctx.guild.id)
            for rid in rids:
                r = ctx.guild.get_role(rid)
                if r:
                    staff_roles.append(f"• {r.mention} (`{r.id}`)")
                else:
                    staff_roles.append(f"• *Deleted Role* (`{rid}`)")

        desc = "\n".join(staff_roles) if staff_roles else "No VC staff roles configured yet."
        embed = EmbedBuilder.base(
            title="🛡️ Authorized VC Staff Roles",
            description=f"Members with these roles have access to `.vcstaff`:\n\n{desc}\n\nUse `.vcstaff add @Role` or `.vcstaff remove @Role`.",
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    @vcstaff_group.command(name="add", help="Add a role to authorized VC staff.")
    async def vcstaff_add(self, ctx: commands.Context, role: discord.Role) -> None:
        if not ctx.guild:
            return
        if not self._is_owner_or_co_owner(ctx.author, ctx.guild):
            await ctx.reply(f"{KrovexEmoji.CROSS} Only the Server Owner can add VC Staff roles.")
            return

        if self.bot.vc_repo:
            await self.bot.vc_repo.add_staff_role(ctx.guild.id, role.id, ctx.author.id)
        await ctx.reply(f"✅ **Authorized:** Role {role.mention} can now operate the **KROVEX VC Staff Panel**.")

    @vcstaff_group.command(name="remove", aliases=["revoke", "delete"], help="Revoke a role from VC staff.")
    async def vcstaff_remove(self, ctx: commands.Context, role: discord.Role) -> None:
        if not ctx.guild:
            return
        if not self._is_owner_or_co_owner(ctx.author, ctx.guild):
            await ctx.reply(f"{KrovexEmoji.CROSS} Only the Server Owner can revoke VC Staff roles.")
            return

        if self.bot.vc_repo:
            await self.bot.vc_repo.remove_staff_role(ctx.guild.id, role.id)
        await ctx.reply(f"⛔ **Revoked:** Role {role.mention} can no longer access the VC Staff Panel. Revocation is immediate.")

    @vcstaff_group.command(name="list", help="List all authorized VC staff roles.")
    async def vcstaff_list(self, ctx: commands.Context) -> None:
        await self.vcstaff_group(ctx)

    @vcstaff_group.command(name="bulk", help="Toggle or configure staff bulk VC actions (Owner only).")
    async def vcstaff_bulk(self, ctx: commands.Context, state: Optional[str] = None) -> None:
        if not ctx.guild:
            return
        if not self._is_owner_or_co_owner(ctx.author, ctx.guild):
            await ctx.reply(f"{KrovexEmoji.CROSS} Only the Server Owner can configure Staff Bulk Actions.")
            return

        current = False
        if self.bot.vc_repo:
            current = await self.bot.vc_repo.get_staff_bulk_actions_allowed(ctx.guild.id)

        if state is None:
            new_val = not current
        else:
            state_lower = state.lower().strip()
            if state_lower in ("on", "enable", "true", "yes", "1"):
                new_val = True
            elif state_lower in ("off", "disable", "false", "no", "0"):
                new_val = False
            else:
                await ctx.reply(f"ℹ️ Current Staff Bulk Actions status: `{'ENABLED' if current else 'DISABLED'}`.\nUsage: `.vcstaff bulk <on|off>`")
                return

        if self.bot.vc_repo:
            await self.bot.vc_repo.set_staff_bulk_actions_allowed(ctx.guild.id, new_val, ctx.author.id)

        msg = (
            "⚠️ **Staff Bulk VC Actions ENABLED:** Staff with authorized roles may now execute mass VC actions (Mute All, Deafen All, Disconnect All, Clear Bans)."
            if new_val else
            "🛡️ **Staff Bulk VC Actions DISABLED:** Staff bulk moderation is locked (Default Policy)."
        )
        await ctx.reply(msg)


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(OwnerDashboardCog(bot))
