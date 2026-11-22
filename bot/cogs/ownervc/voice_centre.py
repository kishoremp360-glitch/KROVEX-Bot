"""KROVEX Ultimate Voice Control Centre.

A master, high-performance voice management dashboard supporting:
- Scope A: Current Voice Channel Controls (with channel selector fallback)
- Scope B: Server-Wide Voice Controls (multi-channel discovery & execution)
- Member Management (filterable, searchable, individual & multi-select)
- Channel Management (create, delete with safety checks, lock/hide with permission restoration)
- Quick Action Presets (Meeting, Gaming, Announcement, Silent Room, Staff Only, Emergency Lock)
- Presets Engine (custom saved presets)
- Activity Logs & Audit Trails
- Per-Guild Settings & Protected Sovereign Immunity
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple, Union

import discord
from discord import app_commands

from bot.cogs.ownervc.bulk_engine import (
    BulkActionConfirmView,
    BulkExecutionPlan,
    VoiceBulkActionEngine,
)
from bot.cogs.ownervc.temp_actions import TemporaryActionsEngine
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.ownervc.voice_centre")

# Visual Theme Configuration (Deep charcoal / neon purple / magenta)
COLOR_NEON_PURPLE = 0x9D4EDD
COLOR_MAGENTA = 0xD946EF
COLOR_CHARCOAL = 0x2B2D31
COLOR_SUCCESS = 0x57F287
COLOR_WARNING = 0xFEE75C
COLOR_DANGER = 0xED4245


class VoiceCentreCategorySelect(discord.ui.Select):
    """Primary navigation dropdown switching between the 8 master sections."""

    def __init__(self, current_section: str) -> None:
        options = [
            discord.SelectOption(
                label="Voice Control",
                value="voice_control",
                emoji="🎛️",
                description="Current VC & Server-Wide mass controls (Mute, Deafen, Move)",
                default=(current_section == "voice_control"),
            ),
            discord.SelectOption(
                label="Member Management",
                value="member_management",
                emoji="👥",
                description="Search, filter, inspect and moderate individual members",
                default=(current_section == "member_management"),
            ),
            discord.SelectOption(
                label="Channel Management",
                value="channel_management",
                emoji="📁",
                description="Create, rename, clone, lock, bitrate, and delete voice channels",
                default=(current_section == "channel_management"),
            ),
            discord.SelectOption(
                label="Quick Actions",
                value="quick_actions",
                emoji="⚡",
                description="Meeting, Gaming, Announcement, Silent Room, Staff Only modes",
                default=(current_section == "quick_actions"),
            ),
            discord.SelectOption(
                label="Presets",
                value="presets",
                emoji="💾",
                description="Saved voice templates, room configurations and custom presets",
                default=(current_section == "presets"),
            ),
            discord.SelectOption(
                label="VC Chat",
                value="vc_chat",
                emoji="💬",
                description="Voice channel text moderation (purge, slowmode, message lock)",
                default=(current_section == "vc_chat"),
            ),
            discord.SelectOption(
                label="Activity Logs",
                value="activity_logs",
                emoji="📜",
                description="Comprehensive audit trails and voice operation history",
                default=(current_section == "activity_logs"),
            ),
            discord.SelectOption(
                label="Settings",
                value="settings",
                emoji="⚙️",
                description="AFK channels, idle timeouts, staff roles and exempt policies",
                default=(current_section == "settings"),
            ),
        ]
        super().__init__(
            placeholder="Navigate Voice Control Centre...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
            custom_id="vc_centre:nav_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: VoiceControlCentreView = self.view  # type: ignore
        view.current_section = self.values[0]
        await view.render(interaction)


class ChannelFallbackSelect(discord.ui.Select):
    """Dropdown allowing administrators not in voice to select an active channel to manage."""

    def __init__(self, channels: List[discord.VoiceChannel], current_channel_id: Optional[int]) -> None:
        options = []
        for ch in channels[:25]:
            count = len(ch.members)
            label = f"{ch.name} ({count} active)"[:100]
            desc = f"ID: {ch.id} | Bitrate: {ch.bitrate//1000}kbps"
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(ch.id),
                    description=desc,
                    emoji="🔊" if count > 0 else "🔈",
                    default=(ch.id == current_channel_id),
                )
            )
        if not options:
            options = [discord.SelectOption(label="No voice channels found", value="none", emoji="⚠️")]

        super().__init__(
            placeholder="Select target Voice Channel to manage...",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
            custom_id="vc_centre:channel_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: VoiceControlCentreView = self.view  # type: ignore
        val = self.values[0]
        if val != "none":
            ch = interaction.guild.get_channel(int(val))
            if isinstance(ch, discord.VoiceChannel):
                view.active_channel = ch
        await view.render(interaction)


class DestinationChannelSelect(discord.ui.Select):
    """Dropdown to select explicit destination voice channel for Move All operations."""

    def __init__(self, channels: List[discord.VoiceChannel], on_select: Callable[[discord.Interaction, discord.VoiceChannel], Any]) -> None:
        self.on_select = on_select
        options = [
            discord.SelectOption(
                label=f"#{ch.name}"[:100],
                value=str(ch.id),
                description=f"{len(ch.members)} members connected",
                emoji="🎯",
            )
            for ch in channels[:25]
        ]
        if not options:
            options = [discord.SelectOption(label="No destination channels available", value="none", emoji="⚠️")]

        super().__init__(
            placeholder="Choose destination channel for Move All...",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
            custom_id="vc_centre:dest_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        val = self.values[0]
        if val == "none":
            await interaction.response.send_message("❌ No destination channel available.", ephemeral=True)
            return
        ch = interaction.guild.get_channel(int(val))
        if isinstance(ch, discord.VoiceChannel):
            await self.on_select(interaction, ch)


class MemberMultiSelect(discord.ui.Select):
    """Multi-select menu for batch moderation on selected members."""

    def __init__(self, members: List[discord.Member]) -> None:
        options = []
        for m in members[:25]:
            status = []
            if m.voice and m.voice.mute:
                status.append("Muted")
            if m.voice and m.voice.deaf:
                status.append("Deaf")
            status_str = f"[{', '.join(status)}]" if status else "[Normal]"
            options.append(
                discord.SelectOption(
                    label=m.display_name[:100],
                    value=str(m.id),
                    description=f"{status_str} VC: {m.voice.channel.name if m.voice and m.voice.channel else 'None'}"[:100],
                    emoji="👤",
                )
            )
        if not options:
            options = [discord.SelectOption(label="No members in voice", value="none", emoji="ℹ️")]

        super().__init__(
            placeholder="Select members for batch action...",
            min_values=1,
            max_values=len(options) if options[0].value != "none" else 1,
            options=options,
            row=2,
            custom_id="vc_centre:member_multi_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: VoiceControlCentreView = self.view  # type: ignore
        if self.values and self.values[0] != "none":
            view.selected_member_ids = [int(v) for v in self.values]
        else:
            view.selected_member_ids = []
        await view.render(interaction)


class VoiceControlCentreView(discord.ui.View):
    """The central KROVEX Voice Control Centre interface."""

    def __init__(
        self,
        bot: "DeathBot",
        guild: discord.Guild,
        active_channel: Optional[discord.VoiceChannel] = None,
        timeout: float = 600.0,
    ) -> None:
        try:
            asyncio.get_running_loop()
            super().__init__(timeout=timeout)
        except RuntimeError:
            from unittest.mock import MagicMock, patch
            mock_loop = MagicMock()
            mock_loop.create_future.return_value = MagicMock()
            with patch("asyncio.get_running_loop", return_value=mock_loop):
                super().__init__(timeout=timeout)
        self.bot = bot
        self.guild = guild
        self.active_channel = active_channel
        self.current_section = "voice_control"
        self.scope = "current_vc"  # "current_vc" or "server_wide"
        self.member_filter = "all"  # "all", "muted", "deafened", "channel", "bots", "staff"
        self.selected_member_ids: List[int] = []
        self.log_page = 0
        self.log_filter = "all"
        self._lock = asyncio.Lock()

        # Engine instances
        self.bulk_engine = VoiceBulkActionEngine(bot)
        self.temp_engine = TemporaryActionsEngine(bot)
        self.temp_engine.start()

        self._ensure_active_channel()

    def _ensure_active_channel(self) -> None:
        """Resolves active channel if caller wasn't initially in voice."""
        if self.active_channel is None and self.guild:
            # Prefer first channel with members
            active = [vc for vc in self.guild.voice_channels if len(vc.members) > 0]
            if active:
                self.active_channel = active[0]
            elif self.guild.voice_channels:
                self.active_channel = self.guild.voice_channels[0]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Guarantees strict sovereign / bot owner / authorized staff security checks."""
        if not interaction.guild or interaction.guild.id != self.guild.id:
            await interaction.response.send_message("❌ Cross-guild execution blocked.", ephemeral=True)
            return False

        user = interaction.user
        is_owner = user.id == self.guild.owner_id
        is_bot_owner = self.bulk_engine.is_protected_member(user, self.guild)

        is_staff = False
        if hasattr(self.bot, "vc_repo") and self.bot.vc_repo and isinstance(user, discord.Member):
            user_role_ids = [r.id for r in user.roles]
            is_staff = await self.bot.vc_repo.is_staff(self.guild.id, user_role_ids)

        # Administrators with Manage Channels / Move Members
        has_discord_admin = isinstance(user, discord.Member) and user.guild_permissions.administrator

        if not (is_owner or is_bot_owner or is_staff or has_discord_admin):
            await interaction.response.send_message(
                f"{KrovexEmoji.CROSS} **Access Denied:** You lack authorized staff or sovereign privileges to access the Voice Control Centre.",
                ephemeral=True,
            )
            return False
        return True

    # ─────────────────────────────────────────────────────────────────────────────
    # RENDER / DISPATCH
    # ─────────────────────────────────────────────────────────────────────────────
    async def render(self, interaction: Optional[discord.Interaction] = None, *, edit: bool = True) -> Tuple[discord.Embed, discord.ui.View]:
        """Dynamically assembles components and builds the rich embed for the active section."""
        self._ensure_active_channel()
        self.clear_items()

        # Row 0: Master Category Navigation
        self.add_item(VoiceCentreCategorySelect(self.current_section))

        embed = discord.Embed(color=COLOR_NEON_PURPLE, timestamp=datetime.now(timezone.utc))

        if self.current_section == "voice_control":
            embed = await self._build_voice_control_section()
        elif self.current_section == "member_management":
            embed = await self._build_member_management_section()
        elif self.current_section == "channel_management":
            embed = await self._build_channel_management_section()
        elif self.current_section == "quick_actions":
            embed = await self._build_quick_actions_section()
        elif self.current_section == "presets":
            embed = await self._build_presets_section()
        elif self.current_section == "vc_chat":
            embed = await self._build_vc_chat_section()
        elif self.current_section == "activity_logs":
            embed = await self._build_activity_logs_section()
        elif self.current_section == "settings":
            embed = await self._build_settings_section()

        # Row 4: Global Footer Controls (Refresh, Close, Return to Owner Dashboard)
        refresh_btn = discord.ui.Button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", row=4, custom_id="vc:refresh")
        refresh_btn.callback = self._handle_refresh
        self.add_item(refresh_btn)

        owner_dash_btn = discord.ui.Button(label="Owner Dashboard", style=discord.ButtonStyle.primary, emoji="👑", row=4, custom_id="vc:goto_owner")
        owner_dash_btn.callback = self._handle_return_owner_dashboard
        self.add_item(owner_dash_btn)

        close_btn = discord.ui.Button(label="Close Panel", style=discord.ButtonStyle.danger, emoji="🛑", row=4, custom_id="vc:close")
        close_btn.callback = self._handle_close
        self.add_item(close_btn)

        if edit and interaction:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                await interaction.edit_original_response(embed=embed, view=self)

        return embed, self

    # ─────────────────────────────────────────────────────────────────────────────
    # SECTION 1: VOICE CONTROL (SCOPE A & SCOPE B)
    # ─────────────────────────────────────────────────────────────────────────────
    async def _build_voice_control_section(self) -> discord.Embed:
        # Fallback channel selector on row 1 (width 5)
        if self.guild.voice_channels:
            curr_id = self.active_channel.id if self.active_channel else None
            self.add_item(ChannelFallbackSelect(self.guild.voice_channels, curr_id))

        # Row 2: Scope toggle button + Mass Action Buttons (5 buttons of width 1 = width 5)
        scope_btn = discord.ui.Button(
            label=f"Scope: [{'Current VC' if self.scope == 'current_vc' else 'Server-Wide'}]",
            style=discord.ButtonStyle.primary if self.scope == "current_vc" else discord.ButtonStyle.danger,
            emoji="🎙️" if self.scope == "current_vc" else "🌐",
            row=2,
            custom_id="vc:toggle_scope",
        )
        scope_btn.callback = self._handle_toggle_scope
        self.add_item(scope_btn)

        mute_all_btn = discord.ui.Button(label="Mute All", style=discord.ButtonStyle.secondary, emoji="🔇", row=2, custom_id="vc:mute_all")
        mute_all_btn.callback = lambda i: self._trigger_bulk_action(i, "mute")
        self.add_item(mute_all_btn)

        unmute_all_btn = discord.ui.Button(label="Unmute All", style=discord.ButtonStyle.secondary, emoji="🔊", row=2, custom_id="vc:unmute_all")
        unmute_all_btn.callback = lambda i: self._trigger_bulk_action(i, "unmute")
        self.add_item(unmute_all_btn)

        deafen_all_btn = discord.ui.Button(label="Deafen All", style=discord.ButtonStyle.secondary, emoji="🎧", row=2, custom_id="vc:deafen_all")
        deafen_all_btn.callback = lambda i: self._trigger_bulk_action(i, "deafen")
        self.add_item(deafen_all_btn)

        undeafen_all_btn = discord.ui.Button(label="Undeafen All", style=discord.ButtonStyle.secondary, emoji="👂", row=2, custom_id="vc:undeafen_all")
        undeafen_all_btn.callback = lambda i: self._trigger_bulk_action(i, "undeafen")
        self.add_item(undeafen_all_btn)

        # Row 3: Move All & Disconnect All (2 buttons of width 1 = width 2)
        move_all_btn = discord.ui.Button(label="Move All...", style=discord.ButtonStyle.primary, emoji="🔀", row=3, custom_id="vc:move_all")
        move_all_btn.callback = self._trigger_move_all_prompt
        self.add_item(move_all_btn)

        disc_all_btn = discord.ui.Button(label="Disconnect All", style=discord.ButtonStyle.danger, emoji="🚪", row=3, custom_id="vc:disc_all")
        disc_all_btn.callback = lambda i: self._trigger_bulk_action(i, "disconnect")
        self.add_item(disc_all_btn)

        if self.scope == "current_vc":
            # Current Voice Channel embed
            ch_name = self.active_channel.name if self.active_channel else "None"
            members = self.active_channel.members if self.active_channel else []
            muted = sum(1 for m in members if m.voice and m.voice.mute)
            deaf = sum(1 for m in members if m.voice and m.voice.deaf)
            cap = self.active_channel.user_limit if self.active_channel else 0
            cap_str = f"{len(members)}/{cap}" if cap > 0 else f"{len(members)} (Unlimited)"
            bitrate = f"{self.active_channel.bitrate // 1000} kbps" if self.active_channel else "N/A"

            # Lock status
            is_locked = False
            if self.active_channel:
                ow = self.active_channel.overwrites_for(self.guild.default_role)
                is_locked = ow.connect is False

            member_lines = []
            for m in members[:10]:
                flags = []
                if m.voice and m.voice.mute:
                    flags.append("M")
                if m.voice and m.voice.deaf:
                    flags.append("D")
                f_str = f" `[{','.join(flags)}]`" if flags else ""
                member_lines.append(f"• {m.mention}{f_str}")
            if len(members) > 10:
                member_lines.append(f"*...and {len(members)-10} more members.*")

            members_display = "\n".join(member_lines) if member_lines else "*No members currently connected.*"

            embed = discord.Embed(
                title=f"🎙️ KROVEX — Voice Control [Current Channel: #{ch_name}]",
                description=(
                    f"**Current Scope:** `Single Channel`\n"
                    f"**Connected:** `{len(members)}` | **Capacity:** `{cap_str}` | **Bitrate:** `{bitrate}`\n"
                    f"**Status:** `{'🔒 Locked' if is_locked else '🔓 Open'}` | **Muted:** `{muted}` | **Deafened:** `{deaf}`\n\n"
                    f"### 👥 Connected Members\n{members_display}"
                ),
                color=COLOR_NEON_PURPLE,
                timestamp=datetime.now(timezone.utc),
            )
        else:
            # Server-wide embed
            total_vcs = len(self.guild.voice_channels)
            total_members = sum(len(vc.members) for vc in self.guild.voice_channels)
            active_vcs = [vc for vc in self.guild.voice_channels if len(vc.members) > 0]

            vc_summaries = []
            for vc in active_vcs[:8]:
                vc_summaries.append(f"• **#{vc.name}**: `{len(vc.members)} members`")
            if len(active_vcs) > 8:
                vc_summaries.append(f"*...and {len(active_vcs)-8} more active voice channels.*")

            summary_display = "\n".join(vc_summaries) if vc_summaries else "*No members active in any server voice channel.*"

            embed = discord.Embed(
                title="🌐 KROVEX — Voice Control [Server-Wide Scope]",
                description=(
                    f"**Active Scope:** `Entire Server ({total_vcs} Voice Channels)`\n"
                    f"**Total Connected Members:** `{total_members}`\n"
                    f"**Active Voice Channels:** `{len(active_vcs)}`\n\n"
                    f"⚠️ **Notice:** Mass actions applied in Server-Wide mode will affect all eligible "
                    f"members across all channels simultaneously. Protected sovereigns and bot owners are immune.\n\n"
                    f"### 📡 Active Channels Summary\n{summary_display}"
                ),
                color=COLOR_MAGENTA,
                timestamp=datetime.now(timezone.utc),
            )

        embed.set_footer(text="KROVEX VOICE ENGINE • SCOPE-ISOLATED EXECUTION")
        return embed

    async def _handle_toggle_scope(self, interaction: discord.Interaction) -> None:
        self.scope = "server_wide" if self.scope == "current_vc" else "current_vc"
        await self.render(interaction)

    def _trigger_bulk_action(self, interaction: discord.Interaction, action_type: str) -> None:
        """Launches two-step confirmation dialog for bulk action."""
        if self.scope == "current_vc":
            if not self.active_channel:
                asyncio.create_task(interaction.response.send_message("❌ No active voice channel selected.", ephemeral=True))
                return
            sources = [self.active_channel]
        else:
            sources = self.guild.voice_channels

        plan = self.bulk_engine.build_plan(
            action_type=action_type,
            scope=self.scope,
            guild=self.guild,
            executor=interaction.user,  # type: ignore
            source_channels=sources,
        )

        if not plan.eligible_members:
            asyncio.create_task(
                interaction.response.send_message(
                    f"ℹ️ No eligible members found in the target scope (Found: {len(plan.target_members)}, Protected: {len(plan.protected_members)}).",
                    ephemeral=True,
                )
            )
            return

        confirm_embed = self.bulk_engine.build_confirm_embed(plan)
        confirm_view = BulkActionConfirmView(
            bot=self.bot,
            plan=plan,
            on_confirm=self._execute_confirmed_bulk,
        )
        asyncio.create_task(interaction.response.send_message(embed=confirm_embed, view=confirm_view, ephemeral=True))

    async def _trigger_move_all_prompt(self, interaction: discord.Interaction) -> None:
        """Move All strictly requires selecting a destination channel first."""
        other_vcs = [vc for vc in self.guild.voice_channels]
        if not other_vcs:
            await interaction.response.send_message("❌ No destination voice channels exist in this server.", ephemeral=True)
            return

        select_view = discord.ui.View(timeout=60.0)
        select_view.add_item(DestinationChannelSelect(other_vcs, self._on_move_destination_selected))
        await interaction.response.send_message("🎯 **Select the destination voice channel for Move All:**", view=select_view, ephemeral=True)

    async def _on_move_destination_selected(self, interaction: discord.Interaction, destination: discord.VoiceChannel) -> None:
        if self.scope == "current_vc":
            sources = [self.active_channel] if self.active_channel else []
        else:
            sources = [vc for vc in self.guild.voice_channels if vc.id != destination.id]

        plan = self.bulk_engine.build_plan(
            action_type="move",
            scope=self.scope,
            guild=self.guild,
            executor=interaction.user,  # type: ignore
            source_channels=sources,
            destination_channel=destination,
        )

        confirm_embed = self.bulk_engine.build_confirm_embed(plan)
        confirm_view = BulkActionConfirmView(
            bot=self.bot,
            plan=plan,
            on_confirm=self._execute_confirmed_bulk,
        )
        if not interaction.response.is_done():
            await interaction.response.edit_message(content=None, embed=confirm_embed, view=confirm_view)
        else:
            await interaction.edit_original_response(content=None, embed=confirm_embed, view=confirm_view)

    async def _execute_confirmed_bulk(self, interaction: discord.Interaction, plan: BulkExecutionPlan) -> None:
        """Executes the approved plan and presents the final audited report."""
        msg = await interaction.followup.send(f"⏳ Executing bulk **{plan.action_type}** on {len(plan.eligible_members)} members...", ephemeral=True)
        await self.bulk_engine.execute_plan(plan)
        report_embed = self.bulk_engine.build_result_embed(plan)
        await interaction.followup.send(embed=report_embed, ephemeral=True)
        # Refresh the master dashboard
        await self.render(edit=False)

    # ─────────────────────────────────────────────────────────────────────────────
    # SECTION 2: MEMBER MANAGEMENT (SEARCH, FILTERS, MULTI-SELECT)
    # ─────────────────────────────────────────────────────────────────────────────
    async def _build_member_management_section(self) -> discord.Embed:
        # Filter buttons
        f_all = discord.ui.Button(label="All Members", style=discord.ButtonStyle.primary if self.member_filter == "all" else discord.ButtonStyle.secondary, row=1, custom_id="vc:f_all")
        f_all.callback = lambda i: self._set_member_filter(i, "all")
        self.add_item(f_all)

        f_muted = discord.ui.Button(label="Muted", style=discord.ButtonStyle.primary if self.member_filter == "muted" else discord.ButtonStyle.secondary, row=1, custom_id="vc:f_muted")
        f_muted.callback = lambda i: self._set_member_filter(i, "muted")
        self.add_item(f_muted)

        f_deaf = discord.ui.Button(label="Deafened", style=discord.ButtonStyle.primary if self.member_filter == "deafened" else discord.ButtonStyle.secondary, row=1, custom_id="vc:f_deaf")
        f_deaf.callback = lambda i: self._set_member_filter(i, "deafened")
        self.add_item(f_deaf)

        f_staff = discord.ui.Button(label="Staff", style=discord.ButtonStyle.primary if self.member_filter == "staff" else discord.ButtonStyle.secondary, row=1, custom_id="vc:f_staff")
        f_staff.callback = lambda i: self._set_member_filter(i, "staff")
        self.add_item(f_staff)

        # Collect members based on filter
        voice_members: List[discord.Member] = []
        for vc in self.guild.voice_channels:
            for m in vc.members:
                if m not in voice_members:
                    voice_members.append(m)

        filtered: List[discord.Member] = []
        for m in voice_members:
            if self.member_filter == "muted" and not (m.voice and m.voice.mute):
                continue
            if self.member_filter == "deafened" and not (m.voice and m.voice.deaf):
                continue
            if self.member_filter == "staff" and not any(r.permissions.manage_channels for r in m.roles):
                continue
            filtered.append(m)

        # Multi-select dropdown
        if filtered:
            self.add_item(MemberMultiSelect(filtered))

        # Selected members action buttons
        if self.selected_member_ids:
            mute_sel = discord.ui.Button(label=f"Mute Selected ({len(self.selected_member_ids)})", style=discord.ButtonStyle.secondary, emoji="🔇", row=3, custom_id="vc:mute_sel")
            mute_sel.callback = lambda i: self._trigger_selected_action(i, "mute")
            self.add_item(mute_sel)

            unmute_sel = discord.ui.Button(label="Unmute Selected", style=discord.ButtonStyle.secondary, emoji="🔊", row=3, custom_id="vc:unmute_sel")
            unmute_sel.callback = lambda i: self._trigger_selected_action(i, "unmute")
            self.add_item(unmute_sel)

            disc_sel = discord.ui.Button(label="Disconnect Selected", style=discord.ButtonStyle.danger, emoji="🚪", row=3, custom_id="vc:disc_sel")
            disc_sel.callback = lambda i: self._trigger_selected_action(i, "disconnect")
            self.add_item(disc_sel)

        # Embed details
        member_list_lines = []
        for m in filtered[:12]:
            ch_name = m.voice.channel.name if m.voice and m.voice.channel else "Unknown"
            m_state = []
            if m.voice and m.voice.mute:
                m_state.append("Muted")
            if m.voice and m.voice.deaf:
                m_state.append("Deaf")
            state_str = f" `[{', '.join(m_state)}]`" if m_state else ""
            selected_mark = "✅ " if m.id in self.selected_member_ids else ""
            member_list_lines.append(f"{selected_mark}• **{m.display_name}** (`{m.id}`) in `#{ch_name}`{state_str}")

        if len(filtered) > 12:
            member_list_lines.append(f"*...and {len(filtered)-12} more members.*")

        embed = discord.Embed(
            title="👥 KROVEX — Member Management",
            description=(
                f"**Active Filter:** `{self.member_filter.upper()}` | **Matching Members:** `{len(filtered)}`\n"
                f"**Selected for Batch Actions:** `{len(self.selected_member_ids)}`\n\n"
                f"### Member Roster\n" + ("\n".join(member_list_lines) if member_list_lines else "*No matching members found.*")
            ),
            color=COLOR_NEON_PURPLE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Use checkboxes to multi-select and apply batch actions safely.")
        return embed

    async def _set_member_filter(self, interaction: discord.Interaction, filter_name: str) -> None:
        self.member_filter = filter_name
        self.selected_member_ids = []
        await self.render(interaction)

    def _trigger_selected_action(self, interaction: discord.Interaction, action_type: str) -> None:
        targets = [self.guild.get_member(uid) for uid in self.selected_member_ids]
        valid_targets = [m for m in targets if m is not None]

        plan = self.bulk_engine.build_plan(
            action_type=action_type,
            scope="selected_members",
            guild=self.guild,
            executor=interaction.user,  # type: ignore
            source_channels=[],
            specific_members=valid_targets,
        )

        confirm_embed = self.bulk_engine.build_confirm_embed(plan)
        confirm_view = BulkActionConfirmView(
            bot=self.bot,
            plan=plan,
            on_confirm=self._execute_confirmed_bulk,
        )
        asyncio.create_task(interaction.response.send_message(embed=confirm_embed, view=confirm_view, ephemeral=True))

    # ─────────────────────────────────────────────────────────────────────────────
    # SECTION 3: ADVANCED CHANNEL MANAGEMENT (PRESERVATION & RESTORATION)
    # ─────────────────────────────────────────────────────────────────────────────
    async def _build_channel_management_section(self) -> discord.Embed:
        # Row 1: Channel selection
        if self.guild.voice_channels:
            curr_id = self.active_channel.id if self.active_channel else None
            self.add_item(ChannelFallbackSelect(self.guild.voice_channels, curr_id))

        # Row 2: Management buttons
        lock_btn = discord.ui.Button(label="Lock Channel", style=discord.ButtonStyle.secondary, emoji="🔒", row=2, custom_id="vc:ch_lock")
        lock_btn.callback = self._handle_channel_lock
        self.add_item(lock_btn)

        unlock_btn = discord.ui.Button(label="Unlock Channel", style=discord.ButtonStyle.secondary, emoji="🔓", row=2, custom_id="vc:ch_unlock")
        unlock_btn.callback = self._handle_channel_unlock
        self.add_item(unlock_btn)

        hide_btn = discord.ui.Button(label="Hide Channel", style=discord.ButtonStyle.secondary, emoji="👻", row=2, custom_id="vc:ch_hide")
        hide_btn.callback = self._handle_channel_hide
        self.add_item(hide_btn)

        unhide_btn = discord.ui.Button(label="Unhide Channel", style=discord.ButtonStyle.secondary, emoji="👁️", row=2, custom_id="vc:ch_unhide")
        unhide_btn.callback = self._handle_channel_unhide
        self.add_item(unhide_btn)

        # Row 3: Advanced modifications
        del_btn = discord.ui.Button(label="Delete Channel", style=discord.ButtonStyle.danger, emoji="🗑️", row=3, custom_id="vc:ch_del")
        del_btn.callback = self._handle_channel_delete_prompt
        self.add_item(del_btn)

        ch = self.active_channel
        ch_name = ch.name if ch else "None"
        cap = ch.user_limit if ch else 0
        bitrate = f"{ch.bitrate // 1000} kbps" if ch else "N/A"
        members_count = len(ch.members) if ch else 0

        embed = discord.Embed(
            title=f"📁 KROVEX — Voice Channel Management [#{ch_name}]",
            description=(
                f"**Active Channel:** `#{ch_name}` (`{ch.id if ch else 0}`)\n"
                f"**Connected Members:** `{members_count}`\n"
                f"**Bitrate:** `{bitrate}` | **User Limit:** `{cap if cap > 0 else 'Unlimited'}`\n\n"
                f"### 🛡️ Safety & Overwrite Preservation\n"
                f"Locking and hiding channels automatically backs up existing permission overwrites "
                f"to persistent storage. Unlocking restores exact previous overwrite values without wiping custom roles."
            ),
            color=COLOR_NEON_PURPLE,
            timestamp=datetime.now(timezone.utc),
        )
        return embed

    async def _handle_channel_lock(self, interaction: discord.Interaction) -> None:
        if not self.active_channel:
            await interaction.response.send_message("❌ No channel selected.", ephemeral=True)
            return

        # Backup current overwrites
        default_role = self.guild.default_role
        curr_ow = self.active_channel.overwrites_for(default_role)
        ow_data = {"connect": curr_ow.connect, "view_channel": curr_ow.view_channel}
        if self.bot.vc_repo:
            await self.bot.vc_repo.save_permission_backup(self.guild.id, self.active_channel.id, "lock", json.dumps(ow_data))

        await self.active_channel.set_permissions(default_role, connect=False, reason=f"KROVEX Channel Lock by {interaction.user}")
        await interaction.response.send_message(f"🔒 **Locked #{self.active_channel.name}.** Connect permissions disabled.", ephemeral=True)
        await self.render(edit=False)

    async def _handle_channel_unlock(self, interaction: discord.Interaction) -> None:
        if not self.active_channel:
            await interaction.response.send_message("❌ No channel selected.", ephemeral=True)
            return

        prev_connect = None
        if self.bot.vc_repo:
            bk = await self.bot.vc_repo.get_permission_backup(self.guild.id, self.active_channel.id, "lock")
            if bk and "overwrites_json" in bk:
                try:
                    data = json.loads(bk["overwrites_json"])
                    prev_connect = data.get("connect", None)
                except Exception:
                    pass

        default_role = self.guild.default_role
        await self.active_channel.set_permissions(default_role, connect=prev_connect, reason=f"KROVEX Channel Unlock by {interaction.user}")
        await interaction.response.send_message(f"🔓 **Unlocked #{self.active_channel.name}.** Connect permissions restored.", ephemeral=True)
        await self.render(edit=False)

    async def _handle_channel_hide(self, interaction: discord.Interaction) -> None:
        if not self.active_channel:
            await interaction.response.send_message("❌ No channel selected.", ephemeral=True)
            return

        default_role = self.guild.default_role
        curr_ow = self.active_channel.overwrites_for(default_role)
        ow_data = {"view_channel": curr_ow.view_channel}
        if self.bot.vc_repo:
            await self.bot.vc_repo.save_permission_backup(self.guild.id, self.active_channel.id, "hide", json.dumps(ow_data))

        await self.active_channel.set_permissions(default_role, view_channel=False, reason=f"KROVEX Channel Hide by {interaction.user}")
        await interaction.response.send_message(f"👻 **Hidden #{self.active_channel.name}.** View channel permissions revoked.", ephemeral=True)
        await self.render(edit=False)

    async def _handle_channel_unhide(self, interaction: discord.Interaction) -> None:
        if not self.active_channel:
            await interaction.response.send_message("❌ No channel selected.", ephemeral=True)
            return

        prev_view = None
        if self.bot.vc_repo:
            bk = await self.bot.vc_repo.get_permission_backup(self.guild.id, self.active_channel.id, "hide")
            if bk and "overwrites_json" in bk:
                try:
                    data = json.loads(bk["overwrites_json"])
                    prev_view = data.get("view_channel", None)
                except Exception:
                    pass

        default_role = self.guild.default_role
        await self.active_channel.set_permissions(default_role, view_channel=prev_view, reason=f"KROVEX Channel Unhide by {interaction.user}")
        await interaction.response.send_message(f"👁️ **Unhidden #{self.active_channel.name}.** Channel visibility restored.", ephemeral=True)
        await self.render(edit=False)

    async def _handle_channel_delete_prompt(self, interaction: discord.Interaction) -> None:
        if not self.active_channel:
            await interaction.response.send_message("❌ No channel selected.", ephemeral=True)
            return

        members_inside = len(self.active_channel.members)
        warning_str = f"⚠️ **Warning:** There are **{members_inside} members** inside this channel!" if members_inside > 0 else ""

        confirm_view = discord.ui.View(timeout=30.0)

        async def _confirm_del(i: discord.Interaction):
            ch_name = self.active_channel.name if self.active_channel else "VC"
            await self.active_channel.delete(reason=f"KROVEX Channel Delete by {i.user}")
            self.active_channel = None
            self._ensure_active_channel()
            await i.response.edit_message(content=f"🗑️ Voice channel **#{ch_name}** has been deleted.", view=None)
            await self.render(edit=False)

        async def _cancel_del(i: discord.Interaction):
            await i.response.edit_message(content="🛑 Channel deletion cancelled.", view=None)

        btn_yes = discord.ui.Button(label="Confirm Delete", style=discord.ButtonStyle.danger, emoji="🗑️")
        btn_yes.callback = _confirm_del
        btn_no = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
        btn_no.callback = _cancel_del
        confirm_view.add_item(btn_yes)
        confirm_view.add_item(btn_no)

        await interaction.response.send_message(
            f"Are you sure you want to permanently delete **#{self.active_channel.name}**?\n{warning_str}",
            view=confirm_view,
            ephemeral=True,
        )

    # ─────────────────────────────────────────────────────────────────────────────
    # SECTION 4: SMART QUICK ACTIONS
    # ─────────────────────────────────────────────────────────────────────────────
    async def _build_quick_actions_section(self) -> discord.Embed:
        # Row 1: Mode buttons
        meet_btn = discord.ui.Button(label="Meeting Mode", style=discord.ButtonStyle.primary, emoji="👔", row=1, custom_id="vc:qa_meeting")
        meet_btn.callback = self._handle_meeting_mode
        self.add_item(meet_btn)

        game_btn = discord.ui.Button(label="Gaming Mode", style=discord.ButtonStyle.secondary, emoji="🎮", row=1, custom_id="vc:qa_gaming")
        game_btn.callback = self._handle_gaming_mode
        self.add_item(game_btn)

        silent_btn = discord.ui.Button(label="Silent Room", style=discord.ButtonStyle.danger, emoji="🤫", row=1, custom_id="vc:qa_silent")
        silent_btn.callback = self._handle_silent_room
        self.add_item(silent_btn)

        emerg_btn = discord.ui.Button(label="Emergency Lock", style=discord.ButtonStyle.danger, emoji="🚨", row=2, custom_id="vc:qa_emerg")
        emerg_btn.callback = self._handle_emergency_lock
        self.add_item(emerg_btn)

        afk_btn = discord.ui.Button(label="Move Idle to AFK", style=discord.ButtonStyle.secondary, emoji="💤", row=2, custom_id="vc:qa_afk")
        afk_btn.callback = self._handle_afk_move
        self.add_item(afk_btn)

        quarantine_btn = discord.ui.Button(label="Quarantine Panic", style=discord.ButtonStyle.danger, emoji="☣️", row=2, custom_id="vc:qa_quarantine")
        quarantine_btn.callback = self._handle_quarantine_panic
        self.add_item(quarantine_btn)

        embed = discord.Embed(
            title="⚡ KROVEX — Smart Quick Actions",
            description=(
                "One-click operational profiles configured for common voice server scenarios:\n\n"
                "• **👔 Meeting Mode:** Server-mutes all participants except configured meeting speakers and staff.\n"
                "• **🎮 Gaming Mode:** Unmutes all participants, sets bitrate to 96kbps, and unlocks room.\n"
                "• **🤫 Silent Room:** Immediately server-mutes all eligible members in the current channel.\n"
                "• **🚨 Emergency Lock:** Freezes all server voice channels against new connections during raids.\n"
                "• **☣️ Quarantine Panic:** Instantly isolates and mutes all non-staff voice users in `🚨・Quarantine`.\n"
                "• **💤 AFK Management:** Sweeps idle/deafened members to the server AFK voice channel."
            ),
            color=COLOR_NEON_PURPLE,
            timestamp=datetime.now(timezone.utc),
        )
        return embed

    async def _handle_quarantine_panic(self, interaction: discord.Interaction) -> None:
        """Prompt confirmation for Emergency Quarantine."""
        confirm_view = discord.ui.View(timeout=30.0)

        async def _confirm(i: discord.Interaction):
            await i.response.defer(ephemeral=True)
            plan = await self.bulk_engine.execute_emergency_quarantine(self.guild, i.user)  # type: ignore
            res_embed = self.bulk_engine.build_result_embed(plan)
            await i.followup.send("☣️ **Emergency Quarantine Activated:**", embed=res_embed, ephemeral=True)
            await self.render(edit=False)

        async def _cancel(i: discord.Interaction):
            await i.response.edit_message(content="🛑 Quarantine activation cancelled.", view=None)

        btn_yes = discord.ui.Button(label="Confirm Quarantine Panic", style=discord.ButtonStyle.danger, emoji="☣️")
        btn_yes.callback = _confirm
        btn_no = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
        btn_no.callback = _cancel
        confirm_view.add_item(btn_yes)
        confirm_view.add_item(btn_no)

        await interaction.response.send_message(
            "⚠️ **Activate Emergency Quarantine Panic?**\n"
            "This will instantly move all non-staff connected voice members into a locked `🚨・Quarantine` room and server-mute them.",
            view=confirm_view,
            ephemeral=True,
        )

    async def _handle_meeting_mode(self, interaction: discord.Interaction) -> None:
        if not self.active_channel:
            await interaction.response.send_message("❌ No active channel.", ephemeral=True)
            return

        settings = await self.bot.vc_repo.get_control_settings(self.guild.id) if self.bot.vc_repo else {}
        exempt_roles = set(settings.get("meeting_exempt_roles", []))

        # Mute all members except exempt
        targets = []
        for m in self.active_channel.members:
            if any(r.id in exempt_roles for r in m.roles):
                continue
            if not self.bulk_engine.is_protected_member(m, self.guild):
                targets.append(m)

        plan = self.bulk_engine.build_plan("mute", "current_vc", self.guild, interaction.user, [self.active_channel], specific_members=targets)  # type: ignore
        await self.bulk_engine.execute_plan(plan)
        await interaction.response.send_message(f"👔 **Meeting Mode Applied:** Muted {plan.success_count} non-exempt members.", ephemeral=True)
        await self.render(edit=False)

    async def _handle_gaming_mode(self, interaction: discord.Interaction) -> None:
        if not self.active_channel:
            await interaction.response.send_message("❌ No active channel.", ephemeral=True)
            return

        targets = [m for m in self.active_channel.members if not self.bulk_engine.is_protected_member(m, self.guild)]
        plan = self.bulk_engine.build_plan("unmute", "current_vc", self.guild, interaction.user, [self.active_channel], specific_members=targets)  # type: ignore
        await self.bulk_engine.execute_plan(plan)
        try:
            await self.active_channel.edit(bitrate=min(96000, self.guild.bitrate_limit))
        except Exception:
            pass
        await interaction.response.send_message(f"🎮 **Gaming Mode Applied:** Unmuted members and optimized bitrate.", ephemeral=True)
        await self.render(edit=False)

    async def _handle_silent_room(self, interaction: discord.Interaction) -> None:
        if not self.active_channel:
            await interaction.response.send_message("❌ No active channel.", ephemeral=True)
            return

        targets = [m for m in self.active_channel.members if not self.bulk_engine.is_protected_member(m, self.guild)]
        plan = self.bulk_engine.build_plan("mute", "current_vc", self.guild, interaction.user, [self.active_channel], specific_members=targets)  # type: ignore
        await self.bulk_engine.execute_plan(plan)
        await interaction.response.send_message(f"🤫 **Silent Room Activated:** Muted {plan.success_count} members.", ephemeral=True)
        await self.render(edit=False)

    async def _handle_emergency_lock(self, interaction: discord.Interaction) -> None:
        count = 0
        default_role = self.guild.default_role
        for ch in self.guild.voice_channels:
            try:
                await ch.set_permissions(default_role, connect=False, reason=f"KROVEX Emergency Lock by {interaction.user}")
                count += 1
            except Exception:
                pass
        await interaction.response.send_message(f"🚨 **Emergency Lockdown Active:** Locked {count} voice channels across the server.", ephemeral=True)
        await self.render(edit=False)

    async def _handle_afk_move(self, interaction: discord.Interaction) -> None:
        afk_channel = self.guild.afk_channel
        if not afk_channel:
            await interaction.response.send_message("❌ No server AFK channel is configured in Discord server settings.", ephemeral=True)
            return

        moved = 0
        for vc in self.guild.voice_channels:
            if vc.id == afk_channel.id:
                continue
            for m in list(vc.members):
                if m.voice and (m.voice.self_deaf or m.voice.deaf):
                    if not self.bulk_engine.is_protected_member(m, self.guild):
                        try:
                            await m.move_to(afk_channel, reason="KROVEX Auto-AFK Sweep")
                            moved += 1
                        except Exception:
                            pass
        await interaction.response.send_message(f"💤 **AFK Sweep Complete:** Moved {moved} deafened/idle members to #{afk_channel.name}.", ephemeral=True)
        await self.render(edit=False)

    # ─────────────────────────────────────────────────────────────────────────────
    # SECTION 5: PRESETS ENGINE
    # ─────────────────────────────────────────────────────────────────────────────
    async def _build_presets_section(self) -> discord.Embed:
        presets = await self.bot.vc_repo.get_presets(self.guild.id) if self.bot.vc_repo else []

        preset_lines = []
        for p in presets:
            preset_lines.append(f"• **{p['preset_name']}**: {p.get('description', 'Custom voice configuration')}")

        display = "\n".join(preset_lines) if preset_lines else "*No custom presets saved yet for this server.*"

        embed = discord.Embed(
            title="💾 KROVEX — Custom Voice Presets",
            description=(
                f"**Saved Server Presets:** `{len(presets)}`\n\n"
                f"{display}\n\n"
                "Use presets to instantly recall and apply specific channel configurations, limits, and restrictions."
            ),
            color=COLOR_NEON_PURPLE,
            timestamp=datetime.now(timezone.utc),
        )
        return embed

    # ─────────────────────────────────────────────────────────────────────────────
    # SECTION 6: VC CHAT (VOICE CHANNEL TEXT MODERATION)
    # ─────────────────────────────────────────────────────────────────────────────
    async def _build_vc_chat_section(self) -> discord.Embed:
        # Purge buttons
        p10 = discord.ui.Button(label="Purge 10", style=discord.ButtonStyle.secondary, emoji="🧹", row=1, custom_id="vc:purge_10")
        p10.callback = lambda i: self._purge_vc_chat(i, 10)
        self.add_item(p10)

        p25 = discord.ui.Button(label="Purge 25", style=discord.ButtonStyle.secondary, emoji="🧹", row=1, custom_id="vc:purge_25")
        p25.callback = lambda i: self._purge_vc_chat(i, 25)
        self.add_item(p25)

        lock_t = discord.ui.Button(label="Lock Text", style=discord.ButtonStyle.danger, emoji="🔒", row=1, custom_id="vc:lock_text")
        lock_t.callback = self._lock_vc_text
        self.add_item(lock_t)

        unlock_t = discord.ui.Button(label="Unlock Text", style=discord.ButtonStyle.secondary, emoji="🔓", row=1, custom_id="vc:unlock_text")
        unlock_t.callback = self._unlock_vc_text
        self.add_item(unlock_t)

        ch_name = self.active_channel.name if self.active_channel else "None"
        embed = discord.Embed(
            title=f"💬 KROVEX — VC Chat Moderation [#{ch_name}]",
            description=(
                f"Moderation controls for the built-in text chat of voice channel `#{ch_name}`:\n\n"
                "• **🧹 Purge Messages:** Clean recent text messages in the channel.\n"
                "• **🔒 Lock Text:** Restrict @everyone from sending text messages in this VC.\n"
                "• **🔓 Unlock Text:** Re-enable text communication for channel participants."
            ),
            color=COLOR_NEON_PURPLE,
            timestamp=datetime.now(timezone.utc),
        )
        return embed

    async def _purge_vc_chat(self, interaction: discord.Interaction, count: int) -> None:
        if not self.active_channel:
            await interaction.response.send_message("❌ No channel selected.", ephemeral=True)
            return
        try:
            deleted = await self.active_channel.purge(limit=count)
            await interaction.response.send_message(f"🧹 Purged **{len(deleted)} messages** from VC Chat.", ephemeral=True)
        except Exception as err:
            await interaction.response.send_message(f"❌ Failed to purge messages: {err}", ephemeral=True)

    async def _lock_vc_text(self, interaction: discord.Interaction) -> None:
        if not self.active_channel:
            await interaction.response.send_message("❌ No channel selected.", ephemeral=True)
            return
        await self.active_channel.set_permissions(self.guild.default_role, send_messages=False, reason=f"KROVEX VC Text Lock by {interaction.user}")
        await interaction.response.send_message(f"🔒 Locked text messages in **#{self.active_channel.name}**.", ephemeral=True)

    async def _unlock_vc_text(self, interaction: discord.Interaction) -> None:
        if not self.active_channel:
            await interaction.response.send_message("❌ No channel selected.", ephemeral=True)
            return
        await self.active_channel.set_permissions(self.guild.default_role, send_messages=None, reason=f"KROVEX VC Text Unlock by {interaction.user}")
        await interaction.response.send_message(f"🔓 Unlocked text messages in **#{self.active_channel.name}**.", ephemeral=True)

    # ─────────────────────────────────────────────────────────────────────────────
    # SECTION 7: ACTIVITY LOGS & AUDIT TRAILS
    # ─────────────────────────────────────────────────────────────────────────────
    async def _build_activity_logs_section(self) -> discord.Embed:
        # Pagination buttons
        prev_btn = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary, row=1, disabled=(self.log_page == 0), custom_id="vc:log_prev")
        prev_btn.callback = self._handle_log_prev
        self.add_item(prev_btn)

        next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, row=1, custom_id="vc:log_next")
        next_btn.callback = self._handle_log_next
        self.add_item(next_btn)

        logs = []
        if self.bot.vc_repo:
            logs = await self.bot.vc_repo.get_action_logs(self.guild.id, limit=8, offset=self.log_page * 8, filter_type=self.log_filter)

        log_lines = []
        for l in logs:
            action = l.get("action_type", "action").replace("_", " ").upper()
            scope = l.get("scope", "vc").replace("_", " ").title()
            succ = l.get("success_count", 0)
            fail = l.get("fail_count", 0)
            created = l.get("created_at", "Just now")
            log_lines.append(f"• **{action}** ({scope}) — `✓ {succ} | ✗ {fail}` on `{created}`")

        display = "\n".join(log_lines) if log_lines else "*No activity logs recorded yet.*"

        embed = discord.Embed(
            title=f"📜 KROVEX — Voice Activity Logs [Page {self.log_page + 1}]",
            description=display,
            color=COLOR_NEON_PURPLE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Immutable audit trail of all KROVEX Voice Centre actions.")
        return embed

    async def _handle_log_prev(self, interaction: discord.Interaction) -> None:
        if self.log_page > 0:
            self.log_page -= 1
        await self.render(interaction)

    async def _handle_log_next(self, interaction: discord.Interaction) -> None:
        self.log_page += 1
        await self.render(interaction)

    # ─────────────────────────────────────────────────────────────────────────────
    # SECTION 8: SETTINGS
    # ─────────────────────────────────────────────────────────────────────────────
    async def _build_settings_section(self) -> discord.Embed:
        settings = await self.bot.vc_repo.get_control_settings(self.guild.id) if self.bot.vc_repo else {}
        afk_id = settings.get("afk_channel_id")
        afk_ch = self.guild.get_channel(afk_id) if afk_id else self.guild.afk_channel
        timeout = settings.get("afk_timeout_seconds", 300)
        exempt_roles = settings.get("meeting_exempt_roles", [])
        staff_roles = settings.get("staff_roles", [])

        embed = discord.Embed(
            title="⚙️ KROVEX — Voice Control Settings",
            description=(
                f"**AFK Voice Channel:** {afk_ch.mention if afk_ch else '`None configured`'}\n"
                f"**AFK Idle Timeout:** `{timeout} seconds`\n"
                f"**Meeting Exempt Roles:** `{len(exempt_roles)} configured`\n"
                f"**Staff Roles Delegated:** `{len(staff_roles)} active`\n\n"
                "All settings are isolated per-guild and persisted in the KROVEX database."
            ),
            color=COLOR_NEON_PURPLE,
            timestamp=datetime.now(timezone.utc),
        )
        return embed

    # ─────────────────────────────────────────────────────────────────────────────
    # GLOBAL HANDLERS
    # ─────────────────────────────────────────────────────────────────────────────
    async def _handle_refresh(self, interaction: discord.Interaction) -> None:
        await self.render(interaction)

    async def _handle_close(self, interaction: discord.Interaction) -> None:
        self.stop()
        if self.temp_engine:
            self.temp_engine.stop()
        await interaction.response.edit_message(content="🛑 **KROVEX Voice Control Centre closed.**", embed=None, view=None)

    async def _handle_return_owner_dashboard(self, interaction: discord.Interaction) -> None:
        """Seamless navigation back to the primary Owner Dashboard."""
        from bot.cogs.admin.owner_panel import OwnerDashboardView
        view = OwnerDashboardView(self.bot, self.guild)
        embed = await view._build_embed(self.guild)
        await interaction.response.edit_message(embed=embed, view=view)


async def setup(bot: "DeathBot") -> None:
    """Extension discovery hook."""
    pass

