"""VC Staff Control Panel — Dedicated, secure Voice Channel moderation for authorized staff.

Exclusively handles voice channel controls matching the Portal Security aesthetic:
- Lock, Unlock, Ghost, Hide, Show
- User Limits, Bitrate, Channel Settings
- Real-time Participant Telemetry & Ownership
- Bulk operations (Mute All, Unmute All, Deafen All, Undeafen All, Kick All, Clear Bans)
- Two-step confirmation for bulk actions
- Strict authorization re-check on every interaction
- Comprehensive audit logging
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.ownervc.staff_panel")
BRAND_COLOR = 0x9D4EDD


class ConfirmBulkActionView(discord.ui.View):
    """Two-step confirmation dialog for destructive or bulk voice channel operations."""

    def __init__(self, action_name: str, channel_name: str, author_id: int, on_confirm_cb) -> None:
        try:
            asyncio.get_running_loop()
            super().__init__(timeout=60.0)
        except RuntimeError:
            from unittest.mock import MagicMock, patch
            mock_loop = MagicMock()
            mock_loop.create_future.return_value = MagicMock()
            with patch("asyncio.get_running_loop", return_value=mock_loop):
                super().__init__(timeout=60.0)
        self.action_name = action_name
        self.channel_name = channel_name
        self.author_id = author_id
        self.on_confirm_cb = on_confirm_cb
        self._actioned = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This confirmation prompt is not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm Operation", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._actioned:
            await interaction.response.send_message("⚠️ Action already executed.", ephemeral=True)
            return
        self._actioned = True
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        await self.on_confirm_cb(interaction)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji=KrovexEmoji.CROSS.partial)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._actioned = True
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        await interaction.response.edit_message(
            content=f"Operation **{self.action_name}** on **{self.channel_name}** was cancelled.",
            view=self
        )
        self.stop()


class VCStaffChannelSelect(discord.ui.Select):
    """Dropdown menu for staff voice channel operations."""

    def __init__(self, allow_bulk: bool = False) -> None:
        self.allow_bulk = allow_bulk
        options = [
            discord.SelectOption(label="Lock Voice Channel", value="lock", emoji="🔒", description="Prevent unauthorized members from joining"),
            discord.SelectOption(label="Unlock Voice Channel", value="unlock", emoji="🔓", description="Allow members to join"),
            discord.SelectOption(label="Ghost Mode", value="ghost", emoji="👻", description="Stealth lock and hide channel"),
            discord.SelectOption(label="Hide Voice Channel", value="hide", emoji="👁️", description="Make channel invisible to unauthorized members"),
            discord.SelectOption(label="Show Voice Channel", value="show", emoji="👁️", description="Make channel visible"),
        ]
        if allow_bulk:
            options.extend([
                discord.SelectOption(label="Mute All Members", value="mute_all", emoji="🔇", description="Server-mute all connected participants (Confirmation required)"),
                discord.SelectOption(label="Unmute All Members", value="unmute_all", emoji="🔊", description="Server-unmute all connected participants"),
                discord.SelectOption(label="Deafen All Members", value="deafen_all", emoji="🔕", description="Server-deafen all connected participants (Confirmation required)"),
                discord.SelectOption(label="Undeafen All Members", value="undeafen_all", emoji="🔔", description="Server-undeafen all connected participants"),
                discord.SelectOption(label="Disconnect All", value="kick_all", emoji="🚪", description="Evict all participants from VC (Confirmation required)"),
                discord.SelectOption(label="Clear Channel Bans", value="clear_bans", emoji="🛡️", description="Clear all user-specific VC ban overwrites (Confirmation required)"),
            ])
        super().__init__(
            placeholder="Channel Control",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
            custom_id="vcstaff:channel_control_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: VCStaffControlView = self.view  # type: ignore
        val = self.values[0]

        # Guard bulk actions: strictly check if enabled by owner
        if val in ("mute_all", "unmute_all", "deafen_all", "undeafen_all", "kick_all", "clear_bans"):
            bulk_allowed = False
            if interaction.user.id == interaction.guild.owner_id:
                bulk_allowed = True
            elif view.bot.vc_repo:
                bulk_allowed = await view.bot.vc_repo.get_staff_bulk_actions_allowed(interaction.guild.id)

            if not bulk_allowed:
                await interaction.response.send_message(
                    "⛔ **Operation Blocked:** Staff bulk VC actions are disabled by default. The Server Owner must enable them in the Owner Panel.",
                    ephemeral=True
                )
                return

        if val == "lock":
            await view._handle_lock(interaction)
        elif val == "unlock":
            await view._handle_unlock(interaction)
        elif val == "ghost":
            await view._handle_ghost(interaction)
        elif val == "hide":
            await view._handle_hide(interaction)
        elif val == "show":
            await view._handle_show(interaction)
        elif val == "mute_all":
            await view._prompt_bulk_confirm(interaction, "Mute All Members", view._handle_muteall)
        elif val == "unmute_all":
            await view._handle_unmuteall(interaction)
        elif val == "deafen_all":
            await view._prompt_bulk_confirm(interaction, "Deafen All Members", view._handle_deafenall)
        elif val == "undeafen_all":
            await view._handle_undeafenall(interaction)
        elif val == "kick_all":
            await view._prompt_bulk_confirm(interaction, "Disconnect All Members", view._handle_kickall)
        elif val == "clear_bans":
            await view._prompt_bulk_confirm(interaction, "Clear Channel Bans", view._handle_clear_bans)


class VCStaffControlView(discord.ui.View):
    """Interactive VC Staff Control Panel view matching Portal Security aesthetic."""

    def __init__(self, bot: "DeathBot", channel: discord.VoiceChannel, allow_bulk: bool = False, timeout: float = 600.0) -> None:
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
        self.channel = channel
        self.allow_bulk = allow_bulk
        self._lock = asyncio.Lock()

        # Add dropdown as row 0
        self.add_item(VCStaffChannelSelect(allow_bulk=allow_bulk))
        self._sync_button_labels()

    def _sync_button_labels(self) -> None:
        """Update button labels dynamically based on channel state."""
        ow = self.channel.overwrites_for(self.channel.guild.default_role)
        is_locked = ow.connect is False
        is_hidden = ow.view_channel is False
        is_ghost = is_locked and is_hidden

        limit_str = str(self.channel.user_limit) if self.channel.user_limit else "∞"
        bitrate_kbps = self.channel.bitrate // 1000

        self.lock_btn.label = "Unlock" if is_locked else "Lock"
        self.lock_btn.style = discord.ButtonStyle.secondary

        self.ghost_btn.label = f"Ghost [{'ON' if is_ghost else 'OFF'}]"
        self.ghost_btn.style = discord.ButtonStyle.secondary

        self.hide_btn.label = "Unhide" if is_hidden else "Hide"
        self.hide_btn.style = discord.ButtonStyle.secondary

        self.limit_btn.label = f"Limit ({limit_str})"
        self.limit_btn.style = discord.ButtonStyle.secondary

        self.bitrate_btn.label = f"Bitrate ({bitrate_kbps}k)"
        self.bitrate_btn.style = discord.ButtonStyle.secondary

        self.settings_btn.style = discord.ButtonStyle.secondary
        self.status_btn.style = discord.ButtonStyle.secondary
        self.owner_btn.style = discord.ButtonStyle.secondary
        self.refresh_btn.style = discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Mandatory security verification re-checked on every single interaction."""
        user = interaction.user
        if not isinstance(user, discord.Member) or not interaction.guild:
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} Must be used in a server.", ephemeral=True)
            return False

        # 1. Server sovereign has absolute authority
        if user.id == interaction.guild.owner_id:
            return True

        # 2. Check if user holds any owner-authorized VC staff role in SQLite
        if self.bot.vc_repo:
            user_role_ids = [r.id for r in user.roles]
            if await self.bot.vc_repo.is_staff(interaction.guild.id, user_role_ids):
                return True

        # Administrators and Manage Channels WITHOUT explicit staff roles are strictly DENIED
        await interaction.response.send_message(
            f"{KrovexEmoji.CROSS} **Access Denied:** Voice Channel Staff authorization required or your role was revoked.",
            ephemeral=True
        )
        return False

    async def _validate_channel(self, interaction: discord.Interaction) -> Optional[discord.VoiceChannel]:
        if not interaction.guild:
            await interaction.response.send_message("❌ Guild context is missing.", ephemeral=True)
            return None

        fresh_ch = interaction.guild.get_channel(self.channel.id)
        if not isinstance(fresh_ch, discord.VoiceChannel):
            await interaction.response.send_message("❌ Target voice channel no longer exists.", ephemeral=True)
            for child in self.children:
                if hasattr(child, "disabled"):
                    child.disabled = True
            self.stop()
            return None

        self.channel = fresh_ch
        return fresh_ch

    def _has_bot_perm(self, interaction: discord.Interaction, perm_name: str) -> bool:
        """Verify the bot itself holds the necessary Discord permission."""
        if not interaction.guild or not interaction.guild.me:
            return False
        perms = interaction.guild.me.guild_permissions
        return bool(getattr(perms, perm_name, False)) or bool(getattr(perms, "administrator", False))

    async def _audit_log(self, interaction: discord.Interaction, action: str, details: str = "") -> None:
        """Log sensitive voice moderation operations."""
        logger.info(
            "VC Staff Action: Guild %s (%s) | Channel %s (%s) | Executor %s (%s) | Action: %s | Details: %s",
            interaction.guild.name if interaction.guild else "Unknown",
            interaction.guild_id,
            self.channel.name,
            self.channel.id,
            interaction.user,
            interaction.user.id,
            action,
            details,
        )
        # Dispatch to bot logging service if available
        if hasattr(self.bot, "logging_service") and self.bot.logging_service:
            try:
                await self.bot.logging_service.log_custom_event(
                    guild=interaction.guild,
                    title=f"{KrovexEmoji.BLUE_BUTTERFLIES} VC Staff Moderation Action",
                    description=(
                        f"**Action:** `{action}`\n"
                        f"**Channel:** {self.channel.mention} (`{self.channel.name}`)\n"
                        f"**Staff Member:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                        f"**Details:** {details or 'N/A'}"
                    ),
                    color=BRAND_COLOR,
                )
            except Exception:
                pass

    async def _refresh_embed(self, interaction: discord.Interaction) -> None:
        try:
            self._sync_button_labels()
            embed = build_vc_staff_embed(self.channel)
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=self)
            elif interaction.message:
                await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            logger.warning("Could not refresh VC staff embed: %s", e)

    async def _prompt_bulk_confirm(self, interaction: discord.Interaction, action_name: str, callback) -> None:
        """Present a confirmation modal before running dangerous bulk operations."""
        view = ConfirmBulkActionView(
            action_name=action_name,
            channel_name=self.channel.name,
            author_id=interaction.user.id,
            on_confirm_cb=callback,
        )
        await interaction.response.send_message(
            f"⚠️ **Confirmation Required:** Are you sure you want to execute **{action_name}** on {self.channel.mention}?",
            view=view,
            ephemeral=True,
        )

    # ── ACTION HANDLERS ────────────────────────────────────────────────────────

    async def _handle_lock(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Bot is missing `Manage Channels` permission.", ephemeral=True)
                return
            await vc.set_permissions(interaction.guild.default_role, connect=False, reason=f"VC Lock by Staff: {interaction.user}")
            await self._audit_log(interaction, "Lock Voice Channel")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔒 {vc.mention} locked.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_unlock(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Bot is missing `Manage Channels` permission.", ephemeral=True)
                return
            await vc.set_permissions(interaction.guild.default_role, connect=None, reason=f"VC Unlock by Staff: {interaction.user}")
            await self._audit_log(interaction, "Unlock Voice Channel")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔓 {vc.mention} unlocked.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_ghost(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Bot is missing `Manage Channels` permission.", ephemeral=True)
                return
            ow = vc.overwrites_for(interaction.guild.default_role)
            is_ghost = ow.connect is False and ow.view_channel is False
            if is_ghost:
                await vc.set_permissions(interaction.guild.default_role, connect=None, view_channel=None, reason=f"Ghost Mode OFF by Staff: {interaction.user}")
                msg = f"👻 Ghost Mode **[OFF]** for {vc.mention}."
                await self._audit_log(interaction, "Ghost Mode Disabled")
            else:
                await vc.set_permissions(interaction.guild.default_role, connect=False, view_channel=False, reason=f"Ghost Mode ON by Staff: {interaction.user}")
                msg = f"👻 Ghost Mode **[ON]** for {vc.mention} (Hidden & Locked)."
                await self._audit_log(interaction, "Ghost Mode Enabled")
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_hide(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Bot is missing `Manage Channels` permission.", ephemeral=True)
                return
            await vc.set_permissions(interaction.guild.default_role, view_channel=False, reason=f"VC Hide by Staff: {interaction.user}")
            await self._audit_log(interaction, "Hide Voice Channel")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"👁️ {vc.mention} hidden from unauthorized members.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_show(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Bot is missing `Manage Channels` permission.", ephemeral=True)
                return
            await vc.set_permissions(interaction.guild.default_role, view_channel=None, reason=f"VC Show by Staff: {interaction.user}")
            await self._audit_log(interaction, "Show Voice Channel")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"👁️ {vc.mention} is now visible.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_muteall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "mute_members"):
                await interaction.response.send_message("❌ Bot is missing `Mute Members` permission.", ephemeral=True)
                return
            bot_member = interaction.guild.me
            count = 0
            for member in list(vc.members):
                if member.id == interaction.guild.owner_id or member.bot:
                    continue
                # Respect role hierarchy
                if bot_member and getattr(member.top_role, "position", 0) >= getattr(bot_member.top_role, "position", 0):
                    continue
                try:
                    await member.edit(mute=True, reason=f"VC Mute All by Staff: {interaction.user}")
                    count += 1
                except Exception:
                    pass
            await self._audit_log(interaction, "Mute All Members", f"Muted {count} participants")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔇 Server-muted {count} members.", ephemeral=True)
            else:
                await interaction.followup.send(f"🔇 Server-muted {count} members.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_unmuteall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "mute_members"):
                await interaction.response.send_message("❌ Bot is missing `Mute Members` permission.", ephemeral=True)
                return
            count = 0
            for member in list(vc.members):
                try:
                    await member.edit(mute=False, reason=f"VC Unmute All by Staff: {interaction.user}")
                    count += 1
                except Exception:
                    pass
            await self._audit_log(interaction, "Unmute All Members", f"Unmuted {count} participants")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔊 Server-unmuted {count} members.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_deafenall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "deafen_members"):
                await interaction.response.send_message("❌ Bot is missing `Deafen Members` permission.", ephemeral=True)
                return
            bot_member = interaction.guild.me
            count = 0
            for member in list(vc.members):
                if member.id == interaction.guild.owner_id or member.bot:
                    continue
                if bot_member and getattr(member.top_role, "position", 0) >= getattr(bot_member.top_role, "position", 0):
                    continue
                try:
                    await member.edit(deafen=True, reason=f"VC Deafen All by Staff: {interaction.user}")
                    count += 1
                except Exception:
                    pass
            await self._audit_log(interaction, "Deafen All Members", f"Deafened {count} participants")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔕 Server-deafened {count} members.", ephemeral=True)
            else:
                await interaction.followup.send(f"🔕 Server-deafened {count} members.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_undeafenall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "deafen_members"):
                await interaction.response.send_message("❌ Bot is missing `Deafen Members` permission.", ephemeral=True)
                return
            count = 0
            for member in list(vc.members):
                try:
                    await member.edit(deafen=False, reason=f"VC Undeafen All by Staff: {interaction.user}")
                    count += 1
                except Exception:
                    pass
            await self._audit_log(interaction, "Undeafen All Members", f"Undeafened {count} participants")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔔 Server-undeafened {count} members.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_kickall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "move_members"):
                await interaction.response.send_message("❌ Bot is missing `Move Members` permission.", ephemeral=True)
                return
            bot_member = interaction.guild.me
            count = 0
            for member in list(vc.members):
                if member.id == interaction.guild.owner_id or member.bot:
                    continue
                if bot_member and getattr(member.top_role, "position", 0) >= getattr(bot_member.top_role, "position", 0):
                    continue
                try:
                    await member.move_to(None, reason=f"VC Kick All by Staff: {interaction.user}")
                    count += 1
                except Exception:
                    pass
            await self._audit_log(interaction, "Disconnect All Members", f"Disconnected {count} participants")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🚪 Disconnected {count} members from VC.", ephemeral=True)
            else:
                await interaction.followup.send(f"🚪 Disconnected {count} members from VC.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_clear_bans(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Bot is missing `Manage Channels` permission.", ephemeral=True)
                return
            count = 0
            for target, ow in list(vc.overwrites.items()):
                if isinstance(target, discord.Member) and ow.connect is False:
                    try:
                        await vc.set_permissions(target, overwrite=None, reason=f"Clear Bans by Staff: {interaction.user}")
                        count += 1
                    except Exception:
                        pass
            if self.bot.vc_repo:
                await self.bot.vc_repo.clear_all_vc_bans(interaction.guild.id, vc.id)
            await self._audit_log(interaction, "Clear Channel Bans", f"Removed {count} ban overwrites")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🛡️ Cleared {count} channel ban overwrites.", ephemeral=True)
            else:
                await interaction.followup.send(f"🛡️ Cleared {count} channel ban overwrites.", ephemeral=True)
            await self._refresh_embed(interaction)

    # ── BUTTON DEFINITIONS ─────────────────────────────────────────────────────

    @discord.ui.button(label="Lock", emoji="🔒", style=discord.ButtonStyle.secondary, row=1, custom_id="vcstaff:lock")
    async def lock_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ow = self.channel.overwrites_for(self.channel.guild.default_role)
        if ow.connect is False:
            await self._handle_unlock(interaction)
        else:
            await self._handle_lock(interaction)

    @discord.ui.button(label="Ghost [OFF]", emoji="👻", style=discord.ButtonStyle.secondary, row=1, custom_id="vcstaff:ghost")
    async def ghost_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_ghost(interaction)

    @discord.ui.button(label="Hide", emoji="👁️", style=discord.ButtonStyle.secondary, row=1, custom_id="vcstaff:hide")
    async def hide_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ow = self.channel.overwrites_for(self.channel.guild.default_role)
        if ow.view_channel is False:
            await self._handle_show(interaction)
        else:
            await self._handle_hide(interaction)

    @discord.ui.button(label="Limit (∞)", emoji="👥", style=discord.ButtonStyle.secondary, row=2, custom_id="vcstaff:limit")
    async def limit_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Bot is missing `Manage Channels` permission.", ephemeral=True)
                return
            cycle = [0, 2, 5, 10, 25]
            current = vc.user_limit
            next_limit = cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else 0
            await vc.edit(user_limit=next_limit, reason=f"VC Limit change by Staff: {interaction.user}")
            limit_str = "Unlimited (∞)" if next_limit == 0 else str(next_limit)
            await self._audit_log(interaction, "Set User Limit", f"Limit: {limit_str}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"👥 Channel capacity set to **{limit_str}**.", ephemeral=True)
            await self._refresh_embed(interaction)

    @discord.ui.button(label="Bitrate (64k)", emoji="🎵", style=discord.ButtonStyle.secondary, row=2, custom_id="vcstaff:bitrate")
    async def bitrate_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Bot is missing `Manage Channels` permission.", ephemeral=True)
                return
            cycle = [64000, 96000, 128000]
            current = vc.bitrate
            next_b = cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else 64000
            try:
                await vc.edit(bitrate=next_b, reason=f"VC Bitrate change by Staff: {interaction.user}")
                msg = f"🎵 Audio bitrate calibrated to **{next_b // 1000}k**."
                await self._audit_log(interaction, "Set Bitrate", f"{next_b // 1000} kbps")
            except Exception as e:
                msg = f"⚠️ Could not set bitrate ({e}). Guild tier may restrict high bitrates."
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            await self._refresh_embed(interaction)

    @discord.ui.button(label="Settings", emoji="⚙️", style=discord.ButtonStyle.secondary, row=3, custom_id="vcstaff:settings")
    async def settings_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = EmbedBuilder.base(
            title="⚙️ Voice Channel Advanced Settings Matrix",
            description=(
                f"**Channel:** {self.channel.mention} (`{self.channel.name}`)\n"
                f"• Category: `{self.channel.category.name if self.channel.category else 'Root'}`\n"
                f"• Region: `{self.channel.rtc_region or 'Automatic'}`\n"
                f"• Bitrate: `{self.channel.bitrate // 1000} kbps`\n"
                f"• Limit: `{self.channel.user_limit or 'Unlimited (∞)'}`\n"
                f"• Permissions Sync: `{'Synced' if self.channel.permissions_synced else 'Custom'}`\n\n"
                "Use `/vc region` or `/vc limit` for direct value overrides."
            ),
            color=BRAND_COLOR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="VC Status", emoji="📡", style=discord.ButtonStyle.secondary, row=3, custom_id="vcstaff:status")
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ow = self.channel.overwrites_for(self.channel.guild.default_role)
        is_locked = ow.connect is False
        is_hidden = ow.view_channel is False
        embed = EmbedBuilder.base(
            title=f"📡 Live Telemetry • #{self.channel.name}",
            description=(
                f"**Connected Members:** `{len(self.channel.members)}`\n"
                f"**Lock State:** `{'Locked 🔒' if is_locked else 'Open 🔓'}`\n"
                f"**Visibility:** `{'Hidden 👁️' if is_hidden else 'Visible 👁️'}`\n"
                f"**Bitrate:** `{self.channel.bitrate // 1000} kbps`\n"
                f"**Gateway Ping:** `{round(self.bot.latency * 1000)}ms`"
            ),
            color=0x2ECC71
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Owner", emoji="👑", style=discord.ButtonStyle.secondary, row=4, custom_id="vcstaff:owner")
    async def owner_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        owner = interaction.guild.get_member(interaction.guild.owner_id)
        owner_name = owner.display_name if owner else f"ID: {interaction.guild.owner_id}"
        embed = EmbedBuilder.base(
            title="👑 Voice Channel Authority & Ownership",
            description=(
                f"Server Sovereign: **{owner_name}**\n"
                f"Channel ID: `{self.channel.id}`\n"
                f"Guild ID: `{interaction.guild.id}`\n"
                f"Moderation Authority: **Authorized VC Staff**"
            ),
            color=BRAND_COLOR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=4, custom_id="vcstaff:refresh")
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            await self._refresh_embed(interaction)
            if not interaction.response.is_done():
                await interaction.response.send_message("🔄 Telemetry refreshed.", ephemeral=True)

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True


def build_vc_staff_embed(channel: discord.VoiceChannel) -> discord.Embed:
    """Build the VC status embed matching Portal Security styling."""
    everyone_overwrite = channel.overwrites_for(channel.guild.default_role)
    is_locked = everyone_overwrite.connect is False
    is_hidden = everyone_overwrite.view_channel is False
    is_ghost = is_locked and is_hidden

    limit_str = str(channel.user_limit) if channel.user_limit else "∞"
    bitrate_str = f"{channel.bitrate // 1000}k"

    desc = (
        "*Voice channel management and access controls*\n\n"
        f"### 🎙️ **# ❄️ . {channel.name.upper()} ! [CONNECTED]**\n"
        "╭・**Lock** — Prevent unauthorized members from joining\n"
        f"├・**Ghost [{'ON' if is_ghost else 'OFF'}]** — Instantly lock and hide voice channel\n"
        "├・**Hide** — Hide channel from unauthorized members\n"
        f"├・**Limit ({limit_str})** — Calibrate voice participant capacity\n"
        f"├・**Bitrate ({bitrate_str})** — Configure high-fidelity audio stream\n"
        "├・**Settings** — Advanced channel configuration matrix & rename\n"
        "├・**VC Status** — Live voice channel activity & participant telemetry\n"
        "├・**Owner** — VC ownership directory & badge assignment\n"
        "╰・**Refresh** — Instantly reload voice channel state"
    )

    embed = discord.Embed(
        title="PORTAL SECURITY • VOICE CONTROL",
        description=desc,
        color=0x2B2D31,
    )
    embed.set_footer(text="PORTAL SECURITY • PROTECTION • PRECISION • CONTROL")
    return embed


async def setup(bot: "DeathBot") -> None:
    """Extension dummy setup to allow dynamic cog discovery."""
    pass

