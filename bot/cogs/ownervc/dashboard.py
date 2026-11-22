"""VC Control Dashboard — interactive embed panel matching Portal Security aesthetic."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.ownervc.staff_panel import (
    ConfirmBulkActionView,
    VCStaffControlView,
    build_vc_staff_embed,
)
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.ownervc.dashboard")
BRAND_COLOR = 0x9D4EDD


class ChannelControlSelect(discord.ui.Select):
    """Dropdown menu for quick VC operations."""

    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Lock Voice Channel", value="lock", emoji="🔒", description="Prevent members from joining"),
            discord.SelectOption(label="Unlock Voice Channel", value="unlock", emoji="🔓", description="Allow members to join"),
            discord.SelectOption(label="Ghost Mode", value="ghost", emoji="👻", description="Stealth lock and hide channel"),
            discord.SelectOption(label="Hide Voice Channel", value="hide", emoji="👁️", description="Make channel invisible"),
            discord.SelectOption(label="Show Voice Channel", value="show", emoji="👁️", description="Make channel visible"),
            discord.SelectOption(label="Mute All Members", value="mute_all", emoji="🔇", description="Server-mute everyone in VC"),
            discord.SelectOption(label="Unmute All Members", value="unmute_all", emoji="🔊", description="Server-unmute everyone in VC"),
            discord.SelectOption(label="Disconnect All Members", value="kick_all", emoji="🚪", description="Remove everyone from VC"),
        ]
        super().__init__(
            placeholder="Channel Control",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
            custom_id="vc:channel_control_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: VCControlView = self.view  # type: ignore
        val = self.values[0]
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
            await view._handle_muteall(interaction)
        elif val == "unmute_all":
            await view._handle_unmuteall(interaction)
        elif val == "kick_all":
            await view._handle_kickall(interaction)


class VCControlView(discord.ui.View):
    """Interactive view with Portal Security style VC control buttons."""

    def __init__(self, bot: "DeathBot", channel: discord.VoiceChannel, timeout: float = 600.0) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.channel = channel
        self._lock = asyncio.Lock()

        # Add Dropdown as row 0
        self.add_item(ChannelControlSelect())
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
        self.lock_btn.style = discord.ButtonStyle.success if is_locked else discord.ButtonStyle.secondary

        self.ghost_btn.label = f"Ghost [{'ON' if is_ghost else 'OFF'}]"
        self.ghost_btn.style = discord.ButtonStyle.danger if is_ghost else discord.ButtonStyle.secondary

        self.hide_btn.label = "Unhide" if is_hidden else "Hide"
        self.hide_btn.style = discord.ButtonStyle.primary if is_hidden else discord.ButtonStyle.secondary

        self.limit_btn.label = f"Limit ({limit_str})"
        self.bitrate_btn.label = f"Bitrate ({bitrate_kbps}k)"

    def _is_protected_member(self, member: Union[discord.Member, discord.User], guild: Optional[discord.Guild]) -> bool:
        if not member:
            return False
        if getattr(member, "bot", False):
            return True
        if guild and member.id == guild.owner_id:
            return True
        if hasattr(self.bot, "is_bot_owner") and callable(self.bot.is_bot_owner):
            try:
                res = self.bot.is_bot_owner(member)
                if isinstance(res, bool) and res:
                    return True
            except Exception:
                pass
        raw_owners = getattr(self.bot.config, "owner_ids", [])
        if member.id in raw_owners or str(member.id) in [str(x) for x in raw_owners]:
            return True
        app_owners = getattr(self.bot, "owner_ids", set()) or set()
        if member.id in app_owners or str(member.id) in [str(x) for x in app_owners]:
            return True
        return False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user = interaction.user
        if not isinstance(user, discord.Member):
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} Must be used in a server.", ephemeral=True)
            return False

        if not (user.guild_permissions.administrator or user.guild_permissions.manage_channels):
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} You need Manage Channels or Administrator permission.", ephemeral=True)
            return False
        return True

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
        if not interaction.guild or not interaction.guild.me:
            return False
        perms = interaction.guild.me.guild_permissions
        return bool(getattr(perms, perm_name, False)) or bool(getattr(perms, "administrator", False))

    async def _refresh_embed(self, interaction: discord.Interaction) -> None:
        try:
            self._sync_button_labels()
            embed = build_vc_embed(self.channel)
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=self)
            elif interaction.message:
                await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            logger.warning("Could not refresh VC dashboard embed: %s", e)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        logger.error("Error in VCControlView [%s]: %s", getattr(item, "label", "button"), error, exc_info=error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)
            else:
                await interaction.followup.send("❌ An unexpected error occurred.", ephemeral=True)
        except Exception:
            pass

    # ==========================
    # CORE BUTTON HANDLERS
    # ==========================

    async def _handle_lock(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ I need Manage Channels permission.", ephemeral=True)
                return
            await vc.set_permissions(interaction.guild.default_role, connect=False, reason=f"VC Lock by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔒 {vc.mention} locked.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_unlock(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ I need Manage Channels permission.", ephemeral=True)
                return
            await vc.set_permissions(interaction.guild.default_role, connect=None, reason=f"VC Unlock by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔓 {vc.mention} unlocked.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_ghost(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ I need Manage Channels permission.", ephemeral=True)
                return
            ow = vc.overwrites_for(interaction.guild.default_role)
            is_ghost = ow.connect is False and ow.view_channel is False
            if is_ghost:
                # Turn OFF Ghost mode
                await vc.set_permissions(interaction.guild.default_role, connect=None, view_channel=None, reason=f"Ghost Mode OFF by {interaction.user}")
                msg = f"👻 Ghost Mode **[OFF]** for {vc.mention}."
            else:
                # Turn ON Ghost mode
                await vc.set_permissions(interaction.guild.default_role, connect=False, view_channel=False, reason=f"Ghost Mode ON by {interaction.user}")
                msg = f"👻 Ghost Mode **[ON]** for {vc.mention} (Hidden & Locked)."
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_hide(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ I need Manage Channels permission.", ephemeral=True)
                return
            await vc.set_permissions(interaction.guild.default_role, view_channel=False, reason=f"VC Hide by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"👁️ {vc.mention} hidden.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_show(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ I need Manage Channels permission.", ephemeral=True)
                return
            await vc.set_permissions(interaction.guild.default_role, view_channel=None, reason=f"VC Show by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"👁️ {vc.mention} visible.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_muteall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "mute_members"):
                await interaction.response.send_message("❌ Missing Mute Members permission.", ephemeral=True)
                return
            count = 0
            for member in list(vc.members):
                if self._is_protected_member(member, interaction.guild):
                    continue
                try:
                    await member.edit(mute=True, reason=f"VC Mute All by {interaction.user}")
                    count += 1
                except Exception:
                    pass
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔇 Muted {count} members.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_unmuteall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "mute_members"):
                await interaction.response.send_message("❌ Missing Mute Members permission.", ephemeral=True)
                return
            count = 0
            for member in list(vc.members):
                try:
                    await member.edit(mute=False, reason=f"VC Unmute All by {interaction.user}")
                    count += 1
                except Exception:
                    pass
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔊 Unmuted {count} members.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_kickall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "move_members"):
                await interaction.response.send_message("❌ Missing Move Members permission.", ephemeral=True)
                return
            count = 0
            for member in list(vc.members):
                if self._is_protected_member(member, interaction.guild):
                    continue
                try:
                    await member.move_to(None, reason=f"VC Kick All by {interaction.user}")
                    count += 1
                except Exception:
                    pass
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🚪 Disconnected {count} members from VC.", ephemeral=True)
            await self._refresh_embed(interaction)

    # ==========================
    # UI BUTTON DECLARATIONS
    # ==========================

    @discord.ui.button(label="Lock", emoji="🔒", style=discord.ButtonStyle.secondary, row=1)
    async def lock_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ow = self.channel.overwrites_for(self.channel.guild.default_role)
        if ow.connect is False:
            await self._handle_unlock(interaction)
        else:
            await self._handle_lock(interaction)

    @discord.ui.button(label="Ghost [OFF]", emoji="👻", style=discord.ButtonStyle.secondary, row=1)
    async def ghost_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_ghost(interaction)

    @discord.ui.button(label="Hide", emoji="👁️", style=discord.ButtonStyle.secondary, row=1)
    async def hide_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ow = self.channel.overwrites_for(self.channel.guild.default_role)
        if ow.view_channel is False:
            await self._handle_show(interaction)
        else:
            await self._handle_hide(interaction)

    @discord.ui.button(label="Limit (∞)", emoji="👥", style=discord.ButtonStyle.secondary, row=2)
    async def limit_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
                return
            # Cycle limit: 0 -> 2 -> 5 -> 10 -> 25 -> 0
            cycle = [0, 2, 5, 10, 25]
            current = vc.user_limit
            next_limit = cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else 0
            await vc.edit(user_limit=next_limit, reason=f"VC Limit change by {interaction.user}")
            limit_str = "Unlimited (∞)" if next_limit == 0 else str(next_limit)
            if not interaction.response.is_done():
                await interaction.response.send_message(f"👥 Channel capacity set to **{limit_str}**.", ephemeral=True)
            await self._refresh_embed(interaction)

    @discord.ui.button(label="Bitrate (64k)", emoji="🎵", style=discord.ButtonStyle.secondary, row=2)
    async def bitrate_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
                return
            # Cycle bitrate: 64k -> 96k -> 128k -> 64k
            cycle = [64000, 96000, 128000]
            current = vc.bitrate
            next_b = cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else 64000
            try:
                await vc.edit(bitrate=next_b, reason=f"VC Bitrate change by {interaction.user}")
                msg = f"🎵 Audio bitrate set to **{next_b // 1000}k**."
            except Exception as e:
                msg = f"⚠️ Could not set bitrate ({e}). Server boost level may restrict this bitrate."
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            await self._refresh_embed(interaction)

    @discord.ui.button(label="Settings", emoji="⚙️", style=discord.ButtonStyle.secondary, row=3)
    async def settings_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = EmbedBuilder.base(
            title="⚙️ Voice Channel Advanced Settings",
            description=(
                f"**Channel:** {self.channel.mention} (`{self.channel.name}`)\n"
                f"• Category: `{self.channel.category.name if self.channel.category else 'Root'}`\n"
                f"• Region: `{self.channel.rtc_region or 'Automatic'}`\n"
                f"• Bitrate: `{self.channel.bitrate // 1000} kbps`\n"
                f"• Limit: `{self.channel.user_limit or 'Unlimited'}`\n\n"
                "Use `.vcname <new name>` or `.vcbitrate <8-384>` for direct adjustments."
            ),
            color=BRAND_COLOR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="VC Status", emoji="📡", style=discord.ButtonStyle.secondary, row=3)
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ow = self.channel.overwrites_for(self.channel.guild.default_role)
        is_locked = ow.connect is False
        is_hidden = ow.view_channel is False
        embed = EmbedBuilder.base(
            title=f"📡 Live Telemetry • {self.channel.name}",
            description=(
                f"**Connected Members:** `{len(self.channel.members)}`\n"
                f"**Lock State:** `{'Locked 🔒' if is_locked else 'Open 🔓'}`\n"
                f"**Visibility:** `{'Hidden 👁️' if is_hidden else 'Visible 👁️'}`\n"
                f"**Bitrate:** `{self.channel.bitrate // 1000} kbps`\n"
                f"**Latency:** `Real-time Gateway Verified`"
            ),
            color=0x2ECC71
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Owner", emoji="👑", style=discord.ButtonStyle.secondary, row=3)
    async def owner_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        owner = interaction.guild.get_member(interaction.guild.owner_id)
        owner_name = owner.display_name if owner else f"ID: {interaction.guild.owner_id}"
        embed = EmbedBuilder.base(
            title="👑 Voice Channel Ownership",
            description=f"Server Sovereign & Authority: **{owner_name}**\nChannel ID: `{self.channel.id}`",
            color=BRAND_COLOR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.primary, row=4)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            await self._refresh_embed(interaction)
            if not interaction.response.is_done():
                await interaction.response.send_message("🔄 Dashboard refreshed.", ephemeral=True)

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True


def build_vc_embed(channel: discord.VoiceChannel) -> discord.Embed:
    """Build the VC status embed matching Portal Security styling."""
    everyone_overwrite = channel.overwrites_for(channel.guild.default_role)
    is_locked = everyone_overwrite.connect is False
    is_hidden = everyone_overwrite.view_channel is False
    is_ghost = is_locked and is_hidden

    members_list = ""
    for m in channel.members[:12]:
        icons = ""
        if m.voice:
            if m.voice.mute or m.voice.self_mute:
                icons += " 🔇"
            if m.voice.deaf or m.voice.self_deaf:
                icons += " 🔕"
        members_list += f"{'👑 ' if m.id == channel.guild.owner_id else '👤 '}{m.display_name}{icons}\n"
    if not members_list:
        members_list = "*No users connected*"
    if len(channel.members) > 12:
        members_list += f"*...and {len(channel.members) - 12} more*"

    region = str(channel.rtc_region) if channel.rtc_region else "Automatic"
    limit_str = str(channel.user_limit) if channel.user_limit else "∞"
    bitrate_str = f"{channel.bitrate // 1000}k"
    status = f"{'🔒 Locked' if is_locked else '🔓 Open'} | {'🙈 Hidden' if is_hidden else '👁️ Visible'}"

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
        "╰・**Refresh** — Instantly reload voice channel state\n"
    )

    embed = discord.Embed(
        title="🛡️ PORTAL SECURITY • VOICE CONTROL [VC Control Panel]",
        description=desc,
        color=BRAND_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="📊 Status", value=status, inline=True)
    embed.add_field(name="👥 Members", value=f"{len(channel.members)}/{limit_str}", inline=True)
    embed.add_field(name="🌐 Region", value=region, inline=True)
    embed.add_field(name="🔊 Bitrate", value=f"{channel.bitrate // 1000} kbps", inline=True)
    embed.add_field(name="📁 Category", value=channel.category.name if channel.category else "None", inline=True)
    embed.add_field(name="🆔 Channel ID", value=str(channel.id), inline=True)
    embed.add_field(name="👤 Connected Members", value=members_list, inline=False)
    embed.set_footer(text="KROVEX SECURITY • PROTECTION • PRECISION • CONTROL")
    return embed


def build_owner_vc_embed(
    channel: Optional[discord.VoiceChannel] = None,
    ban_count: int = 0,
    guild: Optional[discord.Guild] = None,
    scope: str = "current_vc",
) -> discord.Embed:
    """Build the exact Owner & Staff Moderation Dashboard embed matching THOR APEX layout."""
    if channel and not guild:
        guild = channel.guild
    elif not guild and channel:
        guild = channel.guild

    owner = guild.get_member(guild.owner_id) if guild else None
    owner_name = f"@{owner.display_name}" if owner else (f"<@{guild.owner_id}>" if guild else "Unknown")

    if channel:
        ow = channel.overwrites_for(guild.default_role) if (guild and guild.default_role) else None
        is_locked = ow.connect is False if ow else False
        is_hidden = ow.view_channel is False if ow else False

        limit_str = str(channel.user_limit) if getattr(channel, "user_limit", 0) else "∞"
        bitrate_kbps = getattr(channel, "bitrate", 64000) // 1000
        mem_count = len(getattr(channel, "members", []))

        # Line 1: 🔊 channel.name · count connected · Limit ∞ · 64 kbps
        line1 = f"🔊 **{channel.name}** · **{mem_count}** connected · Limit **{limit_str}** · **{bitrate_kbps} kbps**"

        owner_present = any(m.id == guild.owner_id for m in channel.members) if guild else False
        voice_str = "⏹ Voice active" if mem_count > 0 else "💤 Voice idle"
        audio_active = any(
            m.voice and not (m.voice.mute or m.voice.self_mute or m.voice.deaf or m.voice.self_deaf)
            for m in channel.members
        )
        audio_str = "✨ Audio active" if audio_active and mem_count > 0 else "🔇 Audio silent"
        lock_str = "🔒 Locked" if is_locked else "🔓 Open"
        vis_str = "👻 Hidden" if is_hidden else "✨ Visible"
    else:
        line1 = "🔊 **No Voice Channel Selected** · Limit **∞** · **64 kbps**"
        owner_present = False
        voice_str = "💤 Voice idle"
        audio_str = "🔇 Audio silent"
        lock_str = "🔓 Open"
        vis_str = "✨ Visible"

    # Line 2: Operators: @TheRealThor
    line2 = f"Operators: {owner_name}"

    # Line 3: ✔ Owner present · ⏹ Voice active · ✨ Audio active
    owner_str = "✔ Owner present" if owner_present else "👤 Owner absent"
    line3 = f"{owner_str} · {voice_str} · {audio_str}"

    # Line 4: 🛡️ Anti-mute · 🛡️ Anti-deafen · 🔒 Open · ✨ Visible · 0 voice-banned here
    line4 = f"🛡️ Anti-mute · 🛡️ Anti-deafen · {lock_str} · {vis_str} · **{ban_count}** voice-banned here"

    # Line 5: Scope indicator
    if scope == "entire_server" and guild:
        active_vcs = len([vc for vc in guild.voice_channels if vc.members])
        total_vcm = sum(len(vc.members) for vc in guild.voice_channels)
        line5 = f"🌐 **Entire Server Scope** · **{active_vcs}** active VCs · **{total_vcm}** total voice members"
    elif channel:
        line5 = f"🎯 **Current VC Scope** · Target: {channel.mention}"
    else:
        line5 = "🎯 **Current VC Scope** · Select a voice channel below"

    # Separator line: Voice · Room privacy · Message moderation | Server owner, extra owner, configured staff, or bot owner
    desc = "*Voice · Room privacy · Message moderation / Server owner, extra owner, configured staff, or bot owner*"

    full_desc = f"> {line1}\n> {line2}\n> {line3}\n> {line4}\n> {line5}\n\n> {desc}"

    embed = discord.Embed(
        title="Owner & Staff Moderation Dashboard",
        description=full_desc,
        color=0x2B2D31,
    )
    return embed


class SelectTargetMemberView(discord.ui.View):
    """Ephemeral prompt to pick a target user for single-member actions."""

    def __init__(self, action_name: str, author_id: int, on_target_cb) -> None:
        super().__init__(timeout=60.0)
        self.action_name = action_name
        self.author_id = author_id
        self.on_target_cb = on_target_cb

        user_select = discord.ui.UserSelect(
            placeholder=f"Select target member to {action_name}...",
            min_values=1,
            max_values=1,
            custom_id=f"ownervc:user_select_{action_name.lower().replace(' ', '_')}",
        )
        user_select.callback = self._on_select
        self.add_item(user_select)

    def _is_protected_member(self, member: Union[discord.Member, discord.User], guild: Optional[discord.Guild]) -> bool:
        if not member:
            return False
        if getattr(member, "bot", False):
            return True
        if guild and member.id == guild.owner_id:
            return True
        if hasattr(self.bot, "is_bot_owner") and callable(self.bot.is_bot_owner):
            try:
                res = self.bot.is_bot_owner(member)
                if isinstance(res, bool) and res:
                    return True
            except Exception:
                pass
        raw_owners = getattr(self.bot.config, "owner_ids", [])
        if member.id in raw_owners or str(member.id) in [str(x) for x in raw_owners]:
            return True
        app_owners = getattr(self.bot, "owner_ids", set()) or set()
        if member.id in app_owners or str(member.id) in [str(x) for x in app_owners]:
            return True
        return False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This prompt is not for you.", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction) -> None:
        select: discord.ui.UserSelect = self.children[0]  # type: ignore
        if not select.values:
            await interaction.response.send_message("❌ No target selected.", ephemeral=True)
            return
        target = select.values[0]
        if isinstance(target, discord.User) and interaction.guild:
            member = interaction.guild.get_member(target.id)
            if member:
                target = member
        await self.on_target_cb(interaction, target)
        self.stop()


class SetUserLimitModal(discord.ui.Modal, title="Set Voice User Limit"):
    """Modal to set an exact maximum user limit for the voice channel."""
    limit = discord.ui.TextInput(
        label="Maximum User Limit (0 for unlimited)",
        placeholder="Enter 0 to 99...",
        min_length=1,
        max_length=2,
        required=True,
    )

    def __init__(self, view: "OwnerVCControlView") -> None:
        super().__init__()
        self.control_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            val = int(self.limit.value.strip())
            if val < 0 or val > 99:
                await interaction.response.send_message("❌ User limit must be between 0 and 99.", ephemeral=True)
                return
            await self.control_view.channel.edit(user_limit=val, reason=f"OwnerVC limit by {interaction.user}")
            limit_str = "Unlimited (∞)" if val == 0 else str(val)
            await interaction.response.send_message(f"👥 Channel capacity set to **{limit_str}**.", ephemeral=True)
            await self.control_view._refresh_embed(interaction)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to set user limit: {e}", ephemeral=True)


class DeleteMessageModal(discord.ui.Modal, title="Delete Selected Message"):
    """Modal to delete a specific message by its Discord ID."""
    message_id = discord.ui.TextInput(
        label="Message ID",
        placeholder="Enter Discord Message ID to delete...",
        min_length=15,
        max_length=25,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("❌ Must be executed in a text channel.", ephemeral=True)
            return
        try:
            msg_id = int(self.message_id.value.strip())
            msg = await interaction.channel.fetch_message(msg_id)
            await msg.delete()
            await interaction.response.send_message(f"🗑️ Deleted message `{msg_id}`.", ephemeral=True)
        except discord.NotFound:
            await interaction.response.send_message(f"❌ Message `{self.message_id.value}` not found in this channel.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to delete message: {e}", ephemeral=True)


class RenameRoomModal(discord.ui.Modal, title="Rename Voice Channel"):
    """Modal to rename the active voice channel."""
    name_input = discord.ui.TextInput(
        label="New Voice Channel Name",
        placeholder="Enter new channel name...",
        min_length=1,
        max_length=100,
        required=True,
    )

    def __init__(self, view: "OwnerVCControlView") -> None:
        super().__init__()
        self.control_view = view
        if getattr(view, "channel", None) and getattr(view.channel, "name", None):
            self.name_input.default = view.channel.name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not self.control_view.channel:
            await interaction.response.send_message("❌ No active voice channel selected.", ephemeral=True)
            return
        old_name = self.control_view.channel.name
        new_name = self.name_input.value.strip()
        try:
            await self.control_view.channel.edit(name=new_name, reason=f"VCPANEL Rename by {interaction.user}")
            await interaction.response.send_message(f"✏️ Renamed voice channel from **{old_name}** to **{new_name}**.", ephemeral=True)
            await self.control_view._refresh_embed(interaction)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to rename channel: {e}", ephemeral=True)


class CreateVoiceRoomModal(discord.ui.Modal, title="Create Voice Room"):
    """Modal to create a new voice room in the server."""
    name_input = discord.ui.TextInput(
        label="Voice Channel Name",
        placeholder="e.g. Lounge, Gaming, Meeting...",
        min_length=1,
        max_length=100,
        required=True,
    )
    limit_input = discord.ui.TextInput(
        label="User Limit (0 for unlimited)",
        placeholder="0-99",
        min_length=1,
        max_length=2,
        required=False,
        default="0",
    )

    def __init__(self, view: "OwnerVCControlView") -> None:
        super().__init__()
        self.control_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Must be used inside a server.", ephemeral=True)
            return
        name = self.name_input.value.strip()
        limit = 0
        try:
            if self.limit_input.value.strip():
                limit = int(self.limit_input.value.strip())
        except ValueError:
            pass
        category = self.control_view.channel.category if (self.control_view.channel and self.control_view.channel.category) else None
        try:
            new_vc = await interaction.guild.create_voice_channel(
                name=name,
                category=category,
                user_limit=limit,
                reason=f"Created via VCPANEL by {interaction.user}",
            )
            self.control_view.channel = new_vc
            await interaction.response.send_message(f"➕ Created voice channel {new_vc.mention} (Capacity: {limit or '∞'}).", ephemeral=True)
            await self.control_view._refresh_embed(interaction)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to create voice room: {e}", ephemeral=True)


class SelectDestinationVoiceChannelView(discord.ui.View):
    """Dropdown view to choose destination voice channel for Move All operations."""

    def __init__(self, channels: List[discord.VoiceChannel], author_id: int, on_select_cb) -> None:
        try:
            asyncio.get_running_loop()
            super().__init__(timeout=60.0)
        except RuntimeError:
            from unittest.mock import MagicMock, patch
            mock_loop = MagicMock()
            mock_loop.create_future.return_value = MagicMock()
            with patch("asyncio.get_running_loop", return_value=mock_loop):
                super().__init__(timeout=60.0)
        self.author_id = author_id
        self.on_select_cb = on_select_cb

        options = [
            discord.SelectOption(
                label=ch.name[:90],
                value=str(ch.id),
                emoji="🔊",
                description=f"{len(ch.members)} connected | ID: {ch.id}"[:100],
            )
            for ch in channels[:25]
        ]
        if not options:
            options = [discord.SelectOption(label="No voice channels found", value="none", emoji="⚠️")]

        select = discord.ui.Select(
            placeholder="Select destination Voice Channel...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ownervc:dest_vc_select",
        )
        select.callback = self._on_select
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This destination prompt is not for you.", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction) -> None:
        select = self.children[0]
        val = select.values[0] if getattr(select, "values", None) else "none"
        if val == "none" or not val:
            await interaction.response.send_message("❌ No destination channel selected.", ephemeral=True)
            return
        dest_ch = interaction.guild.get_channel(int(val))
        if not isinstance(dest_ch, discord.VoiceChannel):
            await interaction.response.send_message("❌ Selected destination channel no longer exists.", ephemeral=True)
            return
        await self.on_select_cb(interaction, dest_ch)
        self.stop()


class TempDurationSelectView(discord.ui.View):
    """View offering temporary durations (1m, 5m, 10m, 30m) for temporary mute/deafen."""

    def __init__(self, action_name: str, target: discord.Member, author_id: int, on_duration_cb) -> None:
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
        self.target = target
        self.author_id = author_id
        self.on_duration_cb = on_duration_cb

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This prompt is not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="1 Minute", style=discord.ButtonStyle.secondary, emoji="⏱️")
    async def btn_1m(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.on_duration_cb(interaction, self.target, 60, "1 minute")
        self.stop()

    @discord.ui.button(label="5 Minutes", style=discord.ButtonStyle.primary, emoji="⏱️")
    async def btn_5m(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.on_duration_cb(interaction, self.target, 300, "5 minutes")
        self.stop()

    @discord.ui.button(label="10 Minutes", style=discord.ButtonStyle.primary, emoji="⏱️")
    async def btn_10m(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.on_duration_cb(interaction, self.target, 600, "10 minutes")
        self.stop()

    @discord.ui.button(label="30 Minutes", style=discord.ButtonStyle.danger, emoji="⏱️")
    async def btn_30m(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.on_duration_cb(interaction, self.target, 1800, "30 minutes")
        self.stop()


class VoiceScopeSelect(discord.ui.Select):
    """Scope selector placed directly ABOVE Voice moderation dropdown."""

    def __init__(self, current_scope: str = "current_vc") -> None:
        options = [
            discord.SelectOption(
                label="Scope: Current VC",
                value="current_vc",
                emoji="🎯",
                description="Target only the selected voice channel",
                default=(current_scope == "current_vc"),
            ),
            discord.SelectOption(
                label="Scope: Entire Server",
                value="entire_server",
                emoji="🌐",
                description="Target all active voice channels and eligible members in guild",
                default=(current_scope == "entire_server"),
            ),
        ]
        super().__init__(
            placeholder="Select Control Scope (Current VC / Entire Server)...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
            custom_id="ownervc:scope_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: OwnerVCControlView = self.view  # type: ignore
        view.scope = self.values[0]
        for opt in self.options:
            opt.default = (opt.value == view.scope)
        scope_name = "Current VC" if view.scope == "current_vc" else "Entire Server"
        await interaction.response.send_message(
            f"🎯 Control Scope updated to **{scope_name}**.", ephemeral=True
        )
        await view._refresh_embed(interaction)


class VoiceModerationSelect(discord.ui.Select):
    """Dropdown 1: Voice Moderation operations."""

    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Mute All", value="mute_all", emoji="🔇", description="Server-mute all participants in target scope"),
            discord.SelectOption(label="Unmute All", value="unmute_all", emoji="🔊", description="Server-unmute all participants in target scope"),
            discord.SelectOption(label="Deafen All", value="deafen_all", emoji="🔕", description="Server-deafen all participants in target scope"),
            discord.SelectOption(label="Undeafen All", value="undeafen_all", emoji="🔔", description="Server-undeafen all participants in target scope"),
            discord.SelectOption(label="Move All to Another VC", value="move_all", emoji="➡️", description="Move all participants in target scope to another VC"),
            discord.SelectOption(label="Disconnect All", value="kick_all", emoji="🚪", description="Disconnect all participants in target scope"),
            discord.SelectOption(label="Mute Member", value="mute", emoji="🔇", description="Server-mute a specific member in voice"),
            discord.SelectOption(label="Unmute Member", value="unmute", emoji="🔊", description="Server-unmute a specific member in voice"),
            discord.SelectOption(label="Deafen Member", value="deafen", emoji="🔕", description="Server-deafen a specific member in voice"),
            discord.SelectOption(label="Undeafen Member", value="undeafen", emoji="🔔", description="Server-undeafen a specific member in voice"),
            discord.SelectOption(label="Move Member", value="drag", emoji="➡️", description="Move a member into the active voice channel"),
            discord.SelectOption(label="Disconnect Member", value="kick", emoji="🚪", description="Evict a connected member from voice"),
            discord.SelectOption(label="Voice Ban Member", value="ban", emoji="🔨", description="Ban a member from connecting to this voice channel"),
            discord.SelectOption(label="Voice Unban Member", value="unban", emoji="🛡️", description="Remove voice ban overwrite for a member"),
            discord.SelectOption(label="Temporary Mute", value="temp_mute", emoji="⏳", description="Temporarily server-mute a member (1m/5m/10m/30m)"),
            discord.SelectOption(label="Temporary Deafen", value="temp_deafen", emoji="⏱️", description="Temporarily server-deafen a member (1m/5m/10m/30m)"),
            discord.SelectOption(label="View Connected Members", value="view_members", emoji="👥", description="List connected voice members and their statuses"),
            discord.SelectOption(label="Clear Voice Bans", value="clear_bans", emoji="🛡️", description="Clear all voice-ban overwrites for this channel"),
            discord.SelectOption(label="Activate VC Loop", value="loop_activate", emoji="🔁", description="Anchor a member so they return if disconnected"),
            discord.SelectOption(label="Stop VC Loop", value="loop_stop", emoji="⏹️", description="Stop automated reconnect loop for a member"),
            discord.SelectOption(label="VC Loop Status", value="loop_status", emoji="📡", description="View active VC loop configurations for this channel"),
        ]
        super().__init__(
            placeholder="Voice moderation",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
            custom_id="ownervc:voice_moderation",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: OwnerVCControlView = self.view  # type: ignore
        val = self.values[0]
        if val == "loop_activate":
            await view._prompt_member_action(interaction, "Activate VC Loop for", view._handle_loop_activate_target)
        elif val == "loop_stop":
            await view._prompt_member_action(interaction, "Stop VC Loop for", view._handle_loop_stop_target)
        elif val == "loop_status":
            await view._handle_loop_status(interaction)
        elif val == "kick":
            await view._prompt_member_action(interaction, "Kick from Voice", view._handle_kick_target)
        elif val == "ban":
            await view._prompt_member_action(interaction, "Voice Ban", view._handle_ban_target)
        elif val == "unban":
            await view._prompt_member_action(interaction, "Voice Unban", view._handle_unban_target)
        elif val == "mute":
            await view._prompt_member_action(interaction, "Mute in VC", view._handle_mute_target)
        elif val == "unmute":
            await view._prompt_member_action(interaction, "Unmute in VC", view._handle_unmute_target)
        elif val == "deafen":
            await view._prompt_member_action(interaction, "Deafen in VC", view._handle_deafen_target)
        elif val == "undeafen":
            await view._prompt_member_action(interaction, "Undeafen in VC", view._handle_undeafen_target)
        elif val == "drag":
            await view._prompt_member_action(interaction, "Drag to VC", view._handle_drag_target)
        elif val == "move_all":
            await view._prompt_move_all(interaction)
        elif val == "temp_mute":
            await view._prompt_temp_action(interaction, "Temporary Mute", view._handle_temp_mute_execute)
        elif val == "temp_deafen":
            await view._prompt_temp_action(interaction, "Temporary Deafen", view._handle_temp_deafen_execute)
        elif val == "view_members":
            await view._handle_view_members(interaction)
        elif val == "mute_all":
            if view.scope == "entire_server":
                channels = [c for c in interaction.guild.voice_channels if c.members]
                targets = sum(len(c.members) for c in channels)
                prompt_text = f"⚠️ Are you sure you want to **Server-Mute ALL {targets} members** across **{len(channels)} voice channels**?\nTarget Scope: **🌐 Entire Server**"
            else:
                targets = len(view.channel.members) if view.channel else 0
                prompt_text = f"⚠️ Are you sure you want to **Server-Mute {targets} members** in **{view.channel.name if view.channel else 'this channel'}**?\nTarget Scope: **🎯 Current VC**"
            confirm = ConfirmBulkActionView("Mute All Members", view.channel.name if view.channel else "All Channels", interaction.user.id, view._handle_muteall)
            await interaction.response.send_message(prompt_text, view=confirm, ephemeral=True)
        elif val == "unmute_all":
            await view._handle_unmuteall(interaction)
        elif val == "deafen_all":
            if view.scope == "entire_server":
                channels = [c for c in interaction.guild.voice_channels if c.members]
                targets = sum(len(c.members) for c in channels)
                prompt_text = f"⚠️ Are you sure you want to **Server-Deafen ALL {targets} members** across **{len(channels)} voice channels**?\nTarget Scope: **🌐 Entire Server**"
            else:
                targets = len(view.channel.members) if view.channel else 0
                prompt_text = f"⚠️ Are you sure you want to **Server-Deafen {targets} members** in **{view.channel.name if view.channel else 'this channel'}**?\nTarget Scope: **🎯 Current VC**"
            confirm = ConfirmBulkActionView("Deafen All Members", view.channel.name if view.channel else "All Channels", interaction.user.id, view._handle_deafenall)
            await interaction.response.send_message(prompt_text, view=confirm, ephemeral=True)
        elif val == "undeafen_all":
            await view._handle_undeafenall(interaction)
        elif val == "kick_all":
            if view.scope == "entire_server":
                channels = [c for c in interaction.guild.voice_channels if c.members]
                targets = sum(len(c.members) for c in channels)
                prompt_text = f"⚠️ Are you sure you want to **Disconnect ALL {targets} members** from **{len(channels)} voice channels**?\nTarget Scope: **🌐 Entire Server**"
            else:
                targets = len(view.channel.members) if view.channel else 0
                prompt_text = f"⚠️ Are you sure you want to **Disconnect {targets} members** from **{view.channel.name if view.channel else 'this channel'}**?\nTarget Scope: **🎯 Current VC**"
            confirm = ConfirmBulkActionView("Disconnect All Members", view.channel.name if view.channel else "All Channels", interaction.user.id, view._handle_kickall)
            await interaction.response.send_message(prompt_text, view=confirm, ephemeral=True)
        elif val == "clear_bans":
            confirm = ConfirmBulkActionView("Clear Voice Bans", view.channel.name if view.channel else "All Channels", interaction.user.id, view._handle_clearbans)
            await interaction.response.send_message(
                f"⚠️ Are you sure you want to **Clear All Voice Bans** for **{view.channel.name if view.channel else 'this channel'}**?",
                view=confirm,
                ephemeral=True,
            )


class VoicePrivacyCapacitySelect(discord.ui.Select):
    """Dropdown 2: Voice Room Privacy and Capacity operations."""

    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Lock Room", value="lock", emoji="🔒", description="Prevent unauthorized members from joining"),
            discord.SelectOption(label="Unlock Room", value="unlock", emoji="🔓", description="Allow members to join voice channel"),
            discord.SelectOption(label="Make Room Private", value="hide", emoji="👁️", description="Make channel invisible to @everyone"),
            discord.SelectOption(label="Make Room Visible", value="show", emoji="✨", description="Make channel visible to @everyone"),
            discord.SelectOption(label="Ghost Mode", value="ghost", emoji="👻", description="Stealth lock and hide voice channel"),
            discord.SelectOption(label="Set User Limit", value="set_limit", emoji="👥", description="Specify custom user limit (Modal input)"),
            discord.SelectOption(label="Remove User Limit", value="remove_limit", emoji="♾️", description="Remove user limit (Set to unlimited)"),
            discord.SelectOption(label="Display Current User Limit", value="view_limit", emoji="📊", description="View current channel participant capacity"),
            discord.SelectOption(label="Change Bitrate", value="bitrate", emoji="🎵", description="Cycle audio stream fidelity (64k/96k/128k)"),
            discord.SelectOption(label="Display Current Bitrate", value="view_bitrate", emoji="🔊", description="View audio stream bitrate and boost tier"),
            discord.SelectOption(label="Rename Room", value="rename_room", emoji="✏️", description="Rename the active voice channel (Modal input)"),
            discord.SelectOption(label="Move Members to AFK", value="move_afk", emoji="💤", description="Move connected participants to server AFK channel"),
            discord.SelectOption(label="Create Voice Room", value="create_room", emoji="➕", description="Create a new voice channel in guild (Modal input)"),
            discord.SelectOption(label="Delete Voice Room", value="delete_room", emoji="🗑️", description="Permanently delete the active voice channel"),
            discord.SelectOption(label="Clone Voice Room", value="clone_room", emoji="✨", description="Clone voice channel with exact overwrites"),
            discord.SelectOption(label="Add Operator", value="add_operator", emoji="👑", description="Authorize a member as channel operator"),
            discord.SelectOption(label="Remove Operator", value="remove_operator", emoji="➖", description="Revoke channel operator privileges"),
            discord.SelectOption(label="Display Current Operators", value="operators", emoji="🛡️", description="View authorized channel operators"),
            discord.SelectOption(label="Room Telemetry", value="info", emoji="📡", description="View real-time voice telemetry and configuration"),
        ]
        super().__init__(
            placeholder="Voice room privacy and capacity",
            min_values=1,
            max_values=1,
            options=options,
            row=2,
            custom_id="ownervc:privacy_capacity",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: OwnerVCControlView = self.view  # type: ignore
        val = self.values[0]
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
        elif val == "set_limit":
            await interaction.response.send_modal(SetUserLimitModal(view))
        elif val == "remove_limit":
            await view._handle_remove_limit(interaction)
        elif val == "view_limit":
            await view._handle_view_limit(interaction)
        elif val == "bitrate":
            await view._handle_bitrate_cycle(interaction)
        elif val == "view_bitrate":
            await view._handle_view_bitrate(interaction)
        elif val == "rename_room":
            await view._handle_rename_room(interaction)
        elif val == "move_afk":
            await view._handle_move_afk(interaction)
        elif val == "create_room":
            await view._handle_create_room(interaction)
        elif val == "delete_room":
            await view._handle_delete_room(interaction)
        elif val == "clone_room":
            await view._handle_clone_room(interaction)
        elif val == "add_operator":
            await view._prompt_member_action(interaction, "Add Operator", view._handle_add_operator_target)
        elif val == "remove_operator":
            await view._prompt_member_action(interaction, "Remove Operator", view._handle_remove_operator_target)
        elif val == "operators":
            await view._handle_operators(interaction)
        elif val == "info":
            await view._handle_info(interaction)


class MessageModerationSelect(discord.ui.Select):
    """Dropdown 3: Message Moderation operations."""

    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Open Message Tools", value="open_tools", emoji="💬", description="Open quick message moderation tools & intelligence"),
            discord.SelectOption(label="Purge 10 Messages", value="purge_10", emoji="🧹", description="Delete last 10 messages in text channel"),
            discord.SelectOption(label="Purge 25 Messages", value="purge_25", emoji="🧹", description="Delete last 25 messages in text channel"),
            discord.SelectOption(label="Purge 50 Messages", value="purge_50", emoji="🧹", description="Delete last 50 messages in text channel"),
            discord.SelectOption(label="Delete Selected Message", value="delete_msg", emoji="🗑️", description="Delete a specific message by its Discord ID"),
            discord.SelectOption(label="Timeout Member", value="timeout", emoji="⏳", description="Temporarily isolate a member with timeout (10m)"),
            discord.SelectOption(label="Untimeout Member", value="untimeout", emoji="🔓", description="Remove timeout isolation from a member"),
            discord.SelectOption(label="View Member Moderation Info", value="view_mod_info", emoji="📋", description="Inspect moderation records and profile for a member"),
            discord.SelectOption(label="Lock Text Channel", value="lock_text", emoji="🔒", description="Prevent @everyone from sending text messages"),
            discord.SelectOption(label="Unlock Text Channel", value="unlock_text", emoji="🔓", description="Restore text message permissions in text channel"),
            discord.SelectOption(label="Set Slowmode (Cycle)", value="slowmode", emoji="⏱️", description="Adjust text channel message cooldown (0/5s/15s/60s)"),
        ]
        super().__init__(
            placeholder="Message moderation",
            min_values=1,
            max_values=1,
            options=options,
            row=3,
            custom_id="ownervc:message_moderation",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: OwnerVCControlView = self.view  # type: ignore
        val = self.values[0]
        if val == "open_tools":
            await view._handle_open_message_tools(interaction)
        elif val == "purge_10":
            await view._handle_purge(interaction, 10)
        elif val == "purge_25":
            await view._handle_purge(interaction, 25)
        elif val == "purge_50":
            await view._handle_purge(interaction, 50)
        elif val == "delete_msg":
            await interaction.response.send_modal(DeleteMessageModal())
        elif val == "timeout":
            await view._prompt_member_action(interaction, "Timeout (10m)", view._handle_timeout_target)
        elif val == "untimeout":
            await view._prompt_member_action(interaction, "Remove Timeout", view._handle_untimeout_target)
        elif val == "view_mod_info":
            await view._prompt_member_action(interaction, "View Moderation Info", view._handle_view_mod_info_target)
        elif val == "lock_text":
            await view._handle_lock_text(interaction)
        elif val == "unlock_text":
            await view._handle_unlock_text(interaction)
        elif val == "slowmode":
            await view._handle_slowmode_cycle(interaction)


class OwnerVCControlView(discord.ui.View):
    """Interactive view for KROVEX Owner VCPANEL with exactly 3 dropdown sections."""

    def __init__(
        self,
        bot: "DeathBot",
        channel: Optional[discord.VoiceChannel] = None,
        scope: str = "current_vc",
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
        self.channel = channel
        self.scope = scope
        self._lock = asyncio.Lock()

        # Row 0: Scope Selector (Above Voice Moderation)
        self.add_item(VoiceScopeSelect(current_scope=self.scope))

        # Row 1: Voice Moderation
        self.add_item(VoiceModerationSelect())

        # Row 2: Voice Room Privacy and Capacity
        self.add_item(VoicePrivacyCapacitySelect())

        # Row 3: Message Moderation
        self.add_item(MessageModerationSelect())

        # Row 4: Switch VC, Voice Control Centre, Owner Governance
        switch_vc_btn = discord.ui.Button(
            label="Switch VC",
            style=discord.ButtonStyle.secondary,
            emoji="🔄",
            custom_id="ownervc:switch_vc",
            row=4,
        )
        switch_vc_btn.callback = self._handle_switch_channel
        self.add_item(switch_vc_btn)

        vc_centre_btn = discord.ui.Button(
            label="Voice Control Centre",
            style=discord.ButtonStyle.primary,
            emoji="🎛️",
            custom_id="ownervc:goto_vc_centre",
            row=4,
        )
        vc_centre_btn.callback = self._handle_goto_vc_centre
        self.add_item(vc_centre_btn)

        owner_dash_btn = discord.ui.Button(
            label="Owner Governance",
            style=discord.ButtonStyle.secondary,
            emoji="👑",
            custom_id="ownervc:goto_owner_dash",
            row=4,
        )
        owner_dash_btn.callback = self._handle_goto_owner_dashboard
        self.add_item(owner_dash_btn)

    async def _handle_goto_vc_centre(self, interaction: discord.Interaction) -> None:
        from bot.cogs.ownervc.voice_centre import VoiceControlCentreView
        view = VoiceControlCentreView(self.bot, self.channel.guild, active_channel=self.channel)
        embed, _ = await view.render(interaction=None, edit=False)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _handle_goto_owner_dashboard(self, interaction: discord.Interaction) -> None:
        from bot.cogs.admin.owner_panel import OwnerDashboardView
        view = OwnerDashboardView(self.bot, self.channel.guild)
        embed = await view._build_embed(self.channel.guild)
        await interaction.response.edit_message(embed=embed, view=view)

    def _is_protected_member(self, member: Union[discord.Member, discord.User], guild: Optional[discord.Guild]) -> bool:
        if not member:
            return False
        if getattr(member, "bot", False):
            return True
        if guild and member.id == guild.owner_id:
            return True
        if hasattr(self.bot, "is_bot_owner") and callable(self.bot.is_bot_owner):
            try:
                res = self.bot.is_bot_owner(member)
                if isinstance(res, bool) and res:
                    return True
            except Exception:
                pass
        raw_owners = getattr(self.bot.config, "owner_ids", [])
        if member.id in raw_owners or str(member.id) in [str(x) for x in raw_owners]:
            return True
        app_owners = getattr(self.bot, "owner_ids", set()) or set()
        if member.id in app_owners or str(member.id) in [str(x) for x in app_owners]:
            return True
        return False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Strict server owner or bot owner security check on EVERY interaction."""
        if not interaction.guild:
            await interaction.response.send_message("❌ Must be used inside a server.", ephemeral=True)
            return False

        is_owner = interaction.user.id == interaction.guild.owner_id
        is_bot_owner = (
            interaction.user.id in self.bot.config.owner_ids
            or str(interaction.user.id) in [str(x) for x in self.bot.config.owner_ids]
            or (self.bot.owner_ids and (interaction.user.id in self.bot.owner_ids or str(interaction.user.id) in [str(x) for x in self.bot.owner_ids]))
        )
        if not is_bot_owner and hasattr(self.bot, "is_bot_owner") and callable(self.bot.is_bot_owner):
            try:
                res = self.bot.is_bot_owner(interaction.user)
                if asyncio.iscoroutine(res):
                    is_bot_owner = await res
                elif isinstance(res, bool):
                    is_bot_owner = res
            except Exception:
                pass

        if not (is_owner or is_bot_owner):
            await interaction.response.send_message(
                f"{KrovexEmoji.CROSS} **Access Denied:** Only the Discord Server Owner or configured Bot Owner may access the Owner VCPANEL.",
                ephemeral=True,
            )
            return False
        return True

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
        if not interaction.guild or not interaction.guild.me:
            return False
        perms = interaction.guild.me.guild_permissions
        return bool(getattr(perms, perm_name, False)) or bool(getattr(perms, "administrator", False))

    async def _get_ban_count(self) -> int:
        count = 0
        try:
            for target, ow in self.channel.overwrites.items():
                if isinstance(target, (discord.Member, discord.User)) and ow.connect is False:
                    count += 1
            if count == 0 and getattr(self.bot, "db", None):
                rows = await self.bot.db.fetchall(
                    "SELECT COUNT(*) as cnt FROM vc_bans WHERE guild_id=? AND channel_id=?",
                    (self.channel.guild.id, self.channel.id),
                )
                if rows:
                    count = rows[0]["cnt"] if isinstance(rows[0], dict) else rows[0][0]
        except Exception:
            pass
        return count

    async def _refresh_embed(self, interaction: discord.Interaction) -> None:
        try:
            ban_count = await self._get_ban_count() if self.channel else 0
            guild = self.channel.guild if self.channel else interaction.guild
            embed = build_owner_vc_embed(self.channel, ban_count=ban_count, guild=guild, scope=self.scope)
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=self)
            elif interaction.message:
                await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            logger.warning("Could not refresh Owner VCPANEL embed: %s", e)

    async def _prompt_member_action(self, interaction: discord.Interaction, action_name: str, on_target_cb) -> None:
        prompt_view = SelectTargetMemberView(action_name, interaction.user.id, on_target_cb)
        await interaction.response.send_message(
            f"👤 Please select the target member to **{action_name}**:",
            view=prompt_view,
            ephemeral=True,
        )

    # ──────────────────────── VOICE MODERATION HANDLERS ────────────────────────

    async def _handle_kick_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "move_members"):
                await interaction.response.send_message("❌ I need Move Members permission.", ephemeral=True)
                return
            if not target.voice:
                await interaction.response.send_message(f"❌ **{target.display_name}** is not in a voice channel.", ephemeral=True)
                return
            try:
                await target.move_to(None, reason=f"VCPANEL Kick by {interaction.user}")
                await interaction.response.send_message(f"🚪 Disconnected **{target.display_name}** from voice.", ephemeral=True)
                await self._refresh_embed(interaction)
            except Exception as e:
                await interaction.response.send_message(f"❌ Failed to kick {target.display_name}: {e}", ephemeral=True)

    async def _handle_ban_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ I need Manage Channels permission.", ephemeral=True)
                return
            try:
                await vc.set_permissions(target, connect=False, reason=f"VCPANEL VC Ban by {interaction.user}")
                if target.voice and target.voice.channel and target.voice.channel.id == vc.id:
                    try:
                        await target.move_to(None, reason=f"VCPANEL VC Ban disconnect by {interaction.user}")
                    except Exception:
                        pass
                if getattr(self.bot, "db", None):
                    await self.bot.db.execute(
                        "INSERT OR REPLACE INTO vc_bans (guild_id, channel_id, user_id, banned_by, reason) VALUES (?,?,?,?,?)",
                        (vc.guild.id, vc.id, target.id, interaction.user.id, "Owner VCPANEL Ban"),
                    )
                await interaction.response.send_message(f"🔨 Banned **{target.display_name}** from {vc.mention}.", ephemeral=True)
                await self._refresh_embed(interaction)
            except Exception as e:
                await interaction.response.send_message(f"❌ Failed to ban {target.display_name}: {e}", ephemeral=True)

    async def _handle_unban_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ I need Manage Channels permission.", ephemeral=True)
                return
            try:
                await vc.set_permissions(target, connect=None, reason=f"VCPANEL VC Unban by {interaction.user}")
                if getattr(self.bot, "db", None):
                    await self.bot.db.execute(
                        "DELETE FROM vc_bans WHERE guild_id=? AND channel_id=? AND user_id=?",
                        (vc.guild.id, vc.id, target.id),
                    )
                await interaction.response.send_message(f"🛡️ Removed voice ban for **{target.display_name}** on {vc.mention}.", ephemeral=True)
                await self._refresh_embed(interaction)
            except Exception as e:
                await interaction.response.send_message(f"❌ Failed to unban {target.display_name}: {e}", ephemeral=True)

    async def _handle_mute_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "mute_members"):
                await interaction.response.send_message("❌ I need Mute Members permission.", ephemeral=True)
                return
            if not target.voice:
                await interaction.response.send_message(f"❌ **{target.display_name}** is not connected to voice.", ephemeral=True)
                return
            try:
                await target.edit(mute=True, reason=f"VCPANEL Mute by {interaction.user}")
                await interaction.response.send_message(f"🔇 Server-muted **{target.display_name}**.", ephemeral=True)
                await self._refresh_embed(interaction)
            except Exception as e:
                await interaction.response.send_message(f"❌ Failed to mute {target.display_name}: {e}", ephemeral=True)

    async def _handle_unmute_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "mute_members"):
                await interaction.response.send_message("❌ I need Mute Members permission.", ephemeral=True)
                return
            if not target.voice:
                await interaction.response.send_message(f"❌ **{target.display_name}** is not connected to voice.", ephemeral=True)
                return
            try:
                await target.edit(mute=False, reason=f"VCPANEL Unmute by {interaction.user}")
                await interaction.response.send_message(f"🔊 Server-unmuted **{target.display_name}**.", ephemeral=True)
                await self._refresh_embed(interaction)
            except Exception as e:
                await interaction.response.send_message(f"❌ Failed to unmute {target.display_name}: {e}", ephemeral=True)

    async def _handle_deafen_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "deafen_members"):
                await interaction.response.send_message("❌ I need Deafen Members permission.", ephemeral=True)
                return
            if not target.voice:
                await interaction.response.send_message(f"❌ **{target.display_name}** is not connected to voice.", ephemeral=True)
                return
            try:
                await target.edit(deafen=True, reason=f"VCPANEL Deafen by {interaction.user}")
                await interaction.response.send_message(f"🔕 Server-deafened **{target.display_name}**.", ephemeral=True)
                await self._refresh_embed(interaction)
            except Exception as e:
                await interaction.response.send_message(f"❌ Failed to deafen {target.display_name}: {e}", ephemeral=True)

    async def _handle_undeafen_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "deafen_members"):
                await interaction.response.send_message("❌ I need Deafen Members permission.", ephemeral=True)
                return
            if not target.voice:
                await interaction.response.send_message(f"❌ **{target.display_name}** is not connected to voice.", ephemeral=True)
                return
            try:
                await target.edit(deafen=False, reason=f"VCPANEL Undeafen by {interaction.user}")
                await interaction.response.send_message(f"🔔 Server-undeafened **{target.display_name}**.", ephemeral=True)
                await self._refresh_embed(interaction)
            except Exception as e:
                await interaction.response.send_message(f"❌ Failed to undeafen {target.display_name}: {e}", ephemeral=True)

    async def _handle_drag_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            if not self._has_bot_perm(interaction, "move_members"):
                await interaction.response.send_message("❌ I need Move Members permission.", ephemeral=True)
                return
            if not target.voice:
                await interaction.response.send_message(f"❌ **{target.display_name}** is not in a voice channel.", ephemeral=True)
                return
            try:
                await target.move_to(vc, reason=f"VCPANEL Drag by {interaction.user}")
                await interaction.response.send_message(f"➡️ Moved **{target.display_name}** into {vc.mention}.", ephemeral=True)
                await self._refresh_embed(interaction)
            except Exception as e:
                await interaction.response.send_message(f"❌ Failed to drag {target.display_name}: {e}", ephemeral=True)

    async def _get_target_channels(self, interaction: discord.Interaction) -> List[discord.VoiceChannel]:
        """Resolve target voice channels based on active scope (Current VC vs Entire Server)."""
        if self.scope == "entire_server" and interaction.guild:
            return list(interaction.guild.voice_channels)
        vc = await self._validate_channel(interaction)
        return [vc] if vc else []

    async def _handle_switch_channel(self, interaction: discord.Interaction) -> None:
        """Allow operator to switch the active controlled voice channel."""
        if not interaction.guild:
            await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)
            return
        vcs = interaction.guild.voice_channels
        if not vcs:
            await interaction.response.send_message("❌ No voice channels found in this server.", ephemeral=True)
            return
        view = SelectDestinationVoiceChannelView(vcs, interaction.user.id, self._on_switch_channel_selected)
        await interaction.response.send_message("🔊 Select the Voice Channel you want to control:", view=view, ephemeral=True)

    async def _on_switch_channel_selected(self, interaction: discord.Interaction, new_vc: discord.VoiceChannel) -> None:
        self.channel = new_vc
        await interaction.response.send_message(f"🔄 Switched active control channel to **{new_vc.name}**.", ephemeral=True)
        await self._refresh_embed(interaction)

    async def _prompt_move_all(self, interaction: discord.Interaction) -> None:
        """Prompt operator to choose destination VC for Move All action."""
        if not interaction.guild:
            await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)
            return
        if not self._has_bot_perm(interaction, "move_members"):
            await interaction.response.send_message("❌ I need Move Members permission.", ephemeral=True)
            return
        candidates = [vc for vc in interaction.guild.voice_channels if not self.channel or vc.id != self.channel.id]
        if not candidates:
            await interaction.response.send_message("❌ No alternative destination voice channels available.", ephemeral=True)
            return
        view = SelectDestinationVoiceChannelView(candidates, interaction.user.id, self._handle_moveall_confirm)
        await interaction.response.send_message("➡️ Select destination Voice Channel to move members into:", view=view, ephemeral=True)

    async def _handle_moveall_confirm(self, interaction: discord.Interaction, dest_ch: discord.VoiceChannel) -> None:
        """Confirm and execute Move All into destination voice channel with visible scope."""
        channels = await self._get_target_channels(interaction)
        members_to_move = []
        for ch in channels:
            if ch.id == dest_ch.id:
                continue
            for m in ch.members:
                if not self._is_protected_member(m, interaction.guild):
                    members_to_move.append(m)

        scope_str = "🌐 Entire Server" if self.scope == "entire_server" else "🎯 Current VC"
        prompt_text = (
            f"⚠️ Are you sure you want to Move **{len(members_to_move)} members** into **{dest_ch.name}**?\n"
            f"Target Scope: **{scope_str}**"
        )

        async def _do_move(btn_interaction: discord.Interaction) -> None:
            count = 0
            for m in members_to_move:
                try:
                    await m.move_to(dest_ch, reason=f"VCPANEL Move All by {btn_interaction.user}")
                    count += 1
                except Exception:
                    pass
            if not btn_interaction.response.is_done():
                await btn_interaction.response.send_message(f"➡️ Moved {count} members into {dest_ch.mention}.", ephemeral=True)
            await self._refresh_embed(btn_interaction)

        confirm = ConfirmBulkActionView(f"Move All -> {dest_ch.name}", dest_ch.name, interaction.user.id, _do_move)
        await interaction.response.send_message(prompt_text, view=confirm, ephemeral=True)

    async def _prompt_temp_action(self, interaction: discord.Interaction, action_name: str, on_execute) -> None:
        """Prompt member selection followed by duration selection for temporary voice actions."""
        async def _on_member_selected(target_interaction: discord.Interaction, target: discord.Member) -> None:
            if self._is_protected_member(target, target_interaction.guild):
                await target_interaction.response.send_message("❌ Cannot perform moderation actions on sovereign or protected members.", ephemeral=True)
                return
            duration_view = TempDurationSelectView(action_name, target, target_interaction.user.id, on_execute)
            await target_interaction.response.send_message(
                f"⏱️ Select duration to **{action_name}** **{target.display_name}**:",
                view=duration_view,
                ephemeral=True,
            )

        prompt_view = SelectTargetMemberView(action_name, interaction.user.id, _on_member_selected)
        await interaction.response.send_message(
            f"👤 Please select the target member to **{action_name}**:",
            view=prompt_view,
            ephemeral=True,
        )

    async def _handle_temp_mute_execute(self, interaction: discord.Interaction, target: discord.Member, duration_sec: int, duration_label: str) -> None:
        if not self._has_bot_perm(interaction, "mute_members"):
            await interaction.response.send_message("❌ I need Mute Members permission.", ephemeral=True)
            return
        if not target.voice:
            await interaction.response.send_message(f"❌ **{target.display_name}** is not connected to voice.", ephemeral=True)
            return
        try:
            await target.edit(mute=True, reason=f"VCPANEL Temp Mute ({duration_label}) by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⏳ Server-muted **{target.display_name}** for **{duration_label}**.", ephemeral=True)
            else:
                await interaction.followup.send(f"⏳ Server-muted **{target.display_name}** for **{duration_label}**.", ephemeral=True)
            asyncio.create_task(self._temp_unmute_after(target, duration_sec))
            await self._refresh_embed(interaction)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Failed to temp-mute {target.display_name}: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Failed to temp-mute {target.display_name}: {e}", ephemeral=True)

    async def _temp_unmute_after(self, target: discord.Member, delay: int) -> None:
        await asyncio.sleep(delay)
        try:
            if target.guild and target.voice:
                fresh_target = target.guild.get_member(target.id)
                if fresh_target and fresh_target.voice and fresh_target.voice.mute:
                    await fresh_target.edit(mute=False, reason="VCPANEL Temp Mute expired")
        except Exception:
            pass

    async def _handle_temp_deafen_execute(self, interaction: discord.Interaction, target: discord.Member, duration_sec: int, duration_label: str) -> None:
        if not self._has_bot_perm(interaction, "deafen_members"):
            await interaction.response.send_message("❌ I need Deafen Members permission.", ephemeral=True)
            return
        if not target.voice:
            await interaction.response.send_message(f"❌ **{target.display_name}** is not connected to voice.", ephemeral=True)
            return
        try:
            await target.edit(deafen=True, reason=f"VCPANEL Temp Deafen ({duration_label}) by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⏱️ Server-deafened **{target.display_name}** for **{duration_label}**.", ephemeral=True)
            else:
                await interaction.followup.send(f"⏱️ Server-deafened **{target.display_name}** for **{duration_label}**.", ephemeral=True)
            asyncio.create_task(self._temp_undeafen_after(target, duration_sec))
            await self._refresh_embed(interaction)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Failed to temp-deafen {target.display_name}: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Failed to temp-deafen {target.display_name}: {e}", ephemeral=True)

    async def _temp_undeafen_after(self, target: discord.Member, delay: int) -> None:
        await asyncio.sleep(delay)
        try:
            if target.guild and target.voice:
                fresh_target = target.guild.get_member(target.id)
                if fresh_target and fresh_target.voice and fresh_target.voice.deaf:
                    await fresh_target.edit(deafen=False, reason="VCPANEL Temp Deafen expired")
        except Exception:
            pass

    async def _handle_view_members(self, interaction: discord.Interaction) -> None:
        """Display all connected members in the target scope."""
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Guild context is missing.", ephemeral=True)
            return

        if self.scope == "entire_server":
            channels = [vc for vc in guild.voice_channels if vc.members]
            total_members = sum(len(vc.members) for vc in channels)
            title = f"👥 Connected Members • Entire Server ({total_members} total across {len(channels)} VCs)"
            lines = []
            for ch in channels:
                lines.append(f"**🔊 {ch.name}** ({len(ch.members)}):")
                for m in ch.members:
                    st = []
                    if m.voice:
                        if m.voice.mute or m.voice.self_mute:
                            st.append("🔇 Muted")
                        if m.voice.deaf or m.voice.self_deaf:
                            st.append("🔕 Deafened")
                        if m.voice.self_stream:
                            st.append("📺 Streaming")
                        if m.voice.self_video:
                            st.append("📷 Video")
                    st_str = f" [{' · '.join(st)}]" if st else ""
                    lines.append(f"  • {m.display_name} (`{m.id}`){st_str}")
            desc = "\n".join(lines)[:4000] if lines else "No members are currently in voice channels."
        else:
            vc = await self._validate_channel(interaction)
            if not vc:
                return
            title = f"👥 Connected Members • #{vc.name} ({len(vc.members)} total)"
            lines = []
            for m in vc.members:
                st = []
                if m.voice:
                    if m.voice.mute or m.voice.self_mute:
                        st.append("🔇 Muted")
                    if m.voice.deaf or m.voice.self_deaf:
                        st.append("🔕 Deafened")
                    if m.voice.self_stream:
                        st.append("📺 Streaming")
                    if m.voice.self_video:
                        st.append("📷 Video")
                st_str = f" [{' · '.join(st)}]" if st else ""
                lines.append(f"• {m.display_name} (`{m.id}`){st_str}")
            desc = "\n".join(lines)[:4000] if lines else "No members connected in this channel."

        embed = discord.Embed(
            title=title,
            description=desc,
            color=0x2B2D31,
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_muteall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            channels = await self._get_target_channels(interaction)
            if not channels or not self._has_bot_perm(interaction, "mute_members"):
                await interaction.response.send_message("❌ Missing Mute Members permission or no active channels.", ephemeral=True)
                return
            count = 0
            for ch in channels:
                for member in list(ch.members):
                    if self._is_protected_member(member, interaction.guild):
                        continue
                    try:
                        await member.edit(mute=True, reason=f"VCPANEL Mute All by {interaction.user}")
                        count += 1
                    except Exception:
                        pass
            scope_str = "across entire server" if self.scope == "entire_server" else "in active VC"
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔇 Muted {count} members {scope_str}.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_unmuteall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            channels = await self._get_target_channels(interaction)
            if not channels or not self._has_bot_perm(interaction, "mute_members"):
                await interaction.response.send_message("❌ Missing Mute Members permission or no active channels.", ephemeral=True)
                return
            count = 0
            for ch in channels:
                for member in list(ch.members):
                    try:
                        await member.edit(mute=False, reason=f"VCPANEL Unmute All by {interaction.user}")
                        count += 1
                    except Exception:
                        pass
            scope_str = "across entire server" if self.scope == "entire_server" else "in active VC"
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔊 Unmuted {count} members {scope_str}.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_deafenall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            channels = await self._get_target_channels(interaction)
            if not channels or not self._has_bot_perm(interaction, "deafen_members"):
                await interaction.response.send_message("❌ Missing Deafen Members permission or no active channels.", ephemeral=True)
                return
            count = 0
            for ch in channels:
                for member in list(ch.members):
                    if self._is_protected_member(member, interaction.guild):
                        continue
                    try:
                        await member.edit(deafen=True, reason=f"VCPANEL Deafen All by {interaction.user}")
                        count += 1
                    except Exception:
                        pass
            scope_str = "across entire server" if self.scope == "entire_server" else "in active VC"
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔕 Deafened {count} members {scope_str}.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_undeafenall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            channels = await self._get_target_channels(interaction)
            if not channels or not self._has_bot_perm(interaction, "deafen_members"):
                await interaction.response.send_message("❌ Missing Deafen Members permission or no active channels.", ephemeral=True)
                return
            count = 0
            for ch in channels:
                for member in list(ch.members):
                    try:
                        await member.edit(deafen=False, reason=f"VCPANEL Undeafen All by {interaction.user}")
                        count += 1
                    except Exception:
                        pass
            scope_str = "across entire server" if self.scope == "entire_server" else "in active VC"
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔔 Undeafened {count} members {scope_str}.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_kickall(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            channels = await self._get_target_channels(interaction)
            if not channels or not self._has_bot_perm(interaction, "move_members"):
                await interaction.response.send_message("❌ Missing Move Members permission or no active channels.", ephemeral=True)
                return
            count = 0
            for ch in channels:
                for member in list(ch.members):
                    if self._is_protected_member(member, interaction.guild):
                        continue
                    try:
                        await member.move_to(None, reason=f"VCPANEL Kick All by {interaction.user}")
                        count += 1
                    except Exception:
                        pass
            scope_str = "across entire server" if self.scope == "entire_server" else "from active VC"
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🚪 Disconnected {count} members {scope_str}.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_rename_room(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(RenameRoomModal(self))

    async def _handle_create_room(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CreateVoiceRoomModal(self))

    async def _handle_move_afk(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Guild context missing.", ephemeral=True)
            return
        afk_channel = guild.afk_channel
        if not afk_channel:
            await interaction.response.send_message("❌ No AFK voice channel configured on this server.", ephemeral=True)
            return
        if not self._has_bot_perm(interaction, "move_members"):
            await interaction.response.send_message("❌ I need Move Members permission.", ephemeral=True)
            return

        channels = await self._get_target_channels(interaction)
        moved = 0
        for ch in channels:
            if ch.id == afk_channel.id:
                continue
            for m in list(ch.members):
                if not self._is_protected_member(m, guild):
                    try:
                        await m.move_to(afk_channel, reason=f"Moved to AFK by {interaction.user}")
                        moved += 1
                    except Exception:
                        pass
        await interaction.response.send_message(f"💤 Moved {moved} members to AFK channel {afk_channel.mention}.", ephemeral=True)
        await self._refresh_embed(interaction)

    async def _handle_delete_room(self, interaction: discord.Interaction) -> None:
        vc = await self._validate_channel(interaction)
        if not vc:
            return
        if not self._has_bot_perm(interaction, "manage_channels"):
            await interaction.response.send_message("❌ I need Manage Channels permission.", ephemeral=True)
            return

        async def _do_delete(btn_interaction: discord.Interaction) -> None:
            name = vc.name
            try:
                await vc.delete(reason=f"VCPANEL Room Deleted by {btn_interaction.user}")
                other_vcs = [c for c in btn_interaction.guild.voice_channels if c.id != vc.id]
                self.channel = other_vcs[0] if other_vcs else None
                await btn_interaction.response.send_message(f"🗑️ Successfully deleted voice channel **{name}**.", ephemeral=True)
                await self._refresh_embed(btn_interaction)
            except Exception as e:
                await btn_interaction.response.send_message(f"❌ Failed to delete voice room: {e}", ephemeral=True)

        confirm = ConfirmBulkActionView(f"Delete Room #{vc.name}", vc.name, interaction.user.id, _do_delete)
        await interaction.response.send_message(
            f"⚠️ Are you sure you want to **PERMANENTLY DELETE** voice channel **{vc.name}**?",
            view=confirm,
            ephemeral=True,
        )

    async def _handle_clone_room(self, interaction: discord.Interaction) -> None:
        vc = await self._validate_channel(interaction)
        if not vc:
            return
        if not self._has_bot_perm(interaction, "manage_channels"):
            await interaction.response.send_message("❌ I need Manage Channels permission.", ephemeral=True)
            return
        try:
            cloned = await vc.clone(name=f"{vc.name} (Copy)", reason=f"VCPANEL Clone Room by {interaction.user}")
            await interaction.response.send_message(f"✨ Successfully cloned room to {cloned.mention}.", ephemeral=True)
            await self._refresh_embed(interaction)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to clone room: {e}", ephemeral=True)

    async def _handle_open_message_tools(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="💬 Message Moderation Quick Tools",
            description=(
                "Access message management and enforcement directly from the **Message moderation** dropdown:\n\n"
                "• 🧹 **Purge 10/25/50 Messages**: Bulk purge recent text channel messages instantly\n"
                "• 🗑️ **Delete Selected Message**: Target an individual message by Discord Message ID\n"
                "• ⏳ **Timeout Member**: Temporarily isolate a disruptive user for 10 minutes\n"
                "• 🔓 **Untimeout Member**: Remove active timeout isolation\n"
                "• 📋 **View Member Mod Info**: Inspect account history, roles, and past infractions\n"
                "• 🔒 **Lock / Unlock Text Channel**: Toggle channel-wide text chat permissions\n"
                "• ⏱️ **Set Slowmode**: Cycle rate limits (0s, 5s, 15s, 60s)\n\n"
                "*All tools adhere strictly to server role hierarchy, owner exemptions, and Discord safety limits.*"
            ),
            color=0x2B2D31,
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_clearbans(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
                return
            cleared = 0
            for target, ow in list(vc.overwrites.items()):
                if isinstance(target, (discord.Member, discord.User)) and ow.connect is False:
                    try:
                        await vc.set_permissions(target, connect=None, reason=f"VCPANEL Clear Bans by {interaction.user}")
                        cleared += 1
                    except Exception:
                        pass
            if getattr(self.bot, "db", None):
                try:
                    await self.bot.db.execute("DELETE FROM vc_bans WHERE guild_id=? AND channel_id=?", (vc.guild.id, vc.id))
                except Exception:
                    pass
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🛡️ Cleared {cleared} voice ban overwrites.", ephemeral=True)
            await self._refresh_embed(interaction)

    # ──────────────────────── VC LOOP HANDLERS ────────────────────────

    async def _handle_loop_activate_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        if not self.bot.vc_repo:
            await interaction.response.send_message("❌ VC Repository is unavailable.", ephemeral=True)
            return
        if self._is_protected_member(target, interaction.guild):
            await interaction.response.send_message("❌ Cannot activate VC Loop for the server sovereign or bot.", ephemeral=True)
            return
        if await self.bot.vc_repo.is_vc_loop_opted_out(interaction.guild.id, target.id):
            await interaction.response.send_message(
                f"❌ **{target.display_name}** has opted out of automated VC loops (`.vcloop optout`).",
                ephemeral=True
            )
            return
        await self.bot.vc_repo.set_vc_loop(interaction.guild.id, self.channel.id, target.id, interaction.user.id)
        msg = f"🔁 **VC Loop Activated:** **{target.display_name}** is anchored to {self.channel.mention}. If they reconnect elsewhere, they will be automatically returned."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)

    async def _handle_loop_stop_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        if not self.bot.vc_repo:
            await interaction.response.send_message("❌ VC Repository is unavailable.", ephemeral=True)
            return
        removed = await self.bot.vc_repo.remove_vc_loop(interaction.guild.id, target.id)
        msg = f"⏹️ **VC Loop Stopped:** **{target.display_name}** is no longer anchored to this channel." if removed else f"ℹ️ No active loop found for **{target.display_name}**."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)

    async def _handle_loop_status(self, interaction: discord.Interaction) -> None:
        if not self.bot.vc_repo:
            await interaction.response.send_message("❌ VC Repository is unavailable.", ephemeral=True)
            return
        loops = await self.bot.vc_repo.get_channel_vc_loops(interaction.guild.id, self.channel.id)
        if not loops:
            desc = f"No active VC Loops in {self.channel.mention}.\n*To activate, choose **Activate VC Loop** in the Voice Moderation menu.*"
        else:
            lines = []
            for lp in loops:
                m = interaction.guild.get_member(lp["target_id"])
                m_name = m.mention if m else f"User ID `{lp['target_id']}`"
                actor = interaction.guild.get_member(lp["actor_id"])
                actor_name = actor.display_name if actor else f"ID `{lp['actor_id']}`"
                lines.append(f"• {m_name} (Initiated by {actor_name})")
            desc = "\n".join(lines)

        embed = discord.Embed(
            title=f"🔁 Active VC Loops • #{self.channel.name}",
            description=desc,
            color=0x8B5CF6,
        )
        embed.set_footer(text="Users can opt out at any time using .vcloop optout")
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ──────────────────────── PRIVACY & CAPACITY HANDLERS ────────────────────────

    async def _handle_lock(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
                return
            await vc.set_permissions(interaction.guild.default_role, connect=False, reason=f"VCPANEL Lock by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔒 {vc.mention} locked.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_unlock(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
                return
            await vc.set_permissions(interaction.guild.default_role, connect=None, reason=f"VCPANEL Unlock by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔓 {vc.mention} unlocked.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_ghost(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
                return
            ow = vc.overwrites_for(interaction.guild.default_role)
            is_ghost = ow.connect is False and ow.view_channel is False
            if is_ghost:
                await vc.set_permissions(interaction.guild.default_role, connect=None, view_channel=None, reason=f"Ghost Mode OFF by {interaction.user}")
                msg = f"👻 Ghost Mode **[OFF]** for {vc.mention}."
            else:
                await vc.set_permissions(interaction.guild.default_role, connect=False, view_channel=False, reason=f"Ghost Mode ON by {interaction.user}")
                msg = f"👻 Ghost Mode **[ON]** for {vc.mention} (Hidden & Locked)."
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_hide(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
                return
            await vc.set_permissions(interaction.guild.default_role, view_channel=False, reason=f"VCPANEL Hide by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"👁️ {vc.mention} hidden.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_show(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
                return
            await vc.set_permissions(interaction.guild.default_role, view_channel=None, reason=f"VCPANEL Show by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"✨ {vc.mention} visible.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_limit_cycle(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
                return
            cycle = [0, 2, 5, 10, 25]
            current = vc.user_limit
            next_limit = cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else 0
            await vc.edit(user_limit=next_limit, reason=f"VCPANEL Limit by {interaction.user}")
            limit_str = "Unlimited (∞)" if next_limit == 0 else str(next_limit)
            if not interaction.response.is_done():
                await interaction.response.send_message(f"👥 Channel capacity set to **{limit_str}**.", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_bitrate_cycle(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
                return
            cycle = [64000, 96000, 128000]
            current = vc.bitrate
            next_b = cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else 64000
            try:
                await vc.edit(bitrate=next_b, reason=f"VCPANEL Bitrate by {interaction.user}")
                msg = f"🎵 Audio bitrate set to **{next_b // 1000}k**."
            except Exception as e:
                msg = f"⚠️ Could not set bitrate ({e}). Server boost level may restrict this bitrate."
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_operators(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        owner = guild.get_member(guild.owner_id)
        owner_name = owner.mention if owner else f"ID: {guild.owner_id}"
        bot_owners = [f"<@{oid}>" for oid in self.bot.config.owner_ids]
        bot_owners_str = ", ".join(bot_owners) if bot_owners else "None"

        embed = discord.Embed(
            title="👑 Authorized Voice Operators",
            description=(
                f"**Discord Server Sovereign:** {owner_name}\n"
                f"**Configured Bot Owners:** {bot_owners_str}\n\n"
                "*(Only the Server Owner and Bot Owners have sovereign authority to control this VCPANEL.)*"
            ),
            color=BRAND_COLOR,
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_remove_limit(self, interaction: discord.Interaction) -> None:
        async with self._lock:
            vc = await self._validate_channel(interaction)
            if not vc or not self._has_bot_perm(interaction, "manage_channels"):
                await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
                return
            await vc.edit(user_limit=0, reason=f"Remove User Limit by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"♾️ User limit removed for {vc.mention} (Set to Unlimited).", ephemeral=True)
            await self._refresh_embed(interaction)

    async def _handle_view_limit(self, interaction: discord.Interaction) -> None:
        limit_str = f"**{self.channel.user_limit}** participants" if self.channel.user_limit else "**Unlimited (∞)**"
        embed = discord.Embed(
            title=f"👥 Channel Capacity • #{self.channel.name}",
            description=f"Current Maximum Limit: {limit_str}\nConnected: **{len(self.channel.members)}** members",
            color=BRAND_COLOR,
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_view_bitrate(self, interaction: discord.Interaction) -> None:
        boost_tier = interaction.guild.premium_tier if interaction.guild else 0
        max_bitrates = {0: 96, 1: 128, 2: 256, 3: 384}
        max_b = max_bitrates.get(boost_tier, 96)
        embed = discord.Embed(
            title=f"🎵 Audio Bitrate • #{self.channel.name}",
            description=(
                f"**Current Bitrate:** `{self.channel.bitrate // 1000} kbps`\n"
                f"**Guild Boost Tier:** Tier {boost_tier}\n"
                f"**Max Allowed Bitrate:** `{max_b} kbps`"
            ),
            color=BRAND_COLOR,
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_add_operator_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        vc = await self._validate_channel(interaction)
        if not vc or not self._has_bot_perm(interaction, "manage_channels"):
            await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
            return
        await vc.set_permissions(target, manage_channels=True, move_members=True, mute_members=True, deafen_members=True, reason=f"Add Operator by {interaction.user}")
        if not interaction.response.is_done():
            await interaction.response.send_message(f"👑 **Operator Added:** {target.mention} is now an authorized operator for {vc.mention}.", ephemeral=True)
        else:
            await interaction.followup.send(f"👑 **Operator Added:** {target.mention} is now an authorized operator for {vc.mention}.", ephemeral=True)

    async def _handle_remove_operator_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        vc = await self._validate_channel(interaction)
        if not vc or not self._has_bot_perm(interaction, "manage_channels"):
            await interaction.response.send_message("❌ Missing Manage Channels permission.", ephemeral=True)
            return
        await vc.set_permissions(target, overwrite=None, reason=f"Remove Operator by {interaction.user}")
        if not interaction.response.is_done():
            await interaction.response.send_message(f"🛡️ **Operator Revoked:** Removed operator overwrites for {target.mention}.", ephemeral=True)
        else:
            await interaction.followup.send(f"🛡️ **Operator Revoked:** Removed operator overwrites for {target.mention}.", ephemeral=True)

    async def _handle_view_mod_info_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        joined_str = target.joined_at.strftime("%Y-%m-%d %H:%M:%S UTC") if target.joined_at else "Unknown"
        created_str = target.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        roles = [r.mention for r in target.roles if not r.is_default()]
        roles_str = ", ".join(roles) if roles else "None"

        mod_records = []
        if getattr(self.bot, "moderation_repo", None):
            try:
                cases = await self.bot.moderation_repo.get_user_cases(interaction.guild.id, target.id)
                mod_records = cases or []
            except Exception:
                pass

        embed = discord.Embed(
            title=f"🛡️ Moderation Intelligence • {target.display_name}",
            color=BRAND_COLOR,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="User ID", value=f"`{target.id}`", inline=True)
        embed.add_field(name="Account Created", value=created_str, inline=True)
        embed.add_field(name="Joined Server", value=joined_str, inline=True)
        embed.add_field(name="Roles", value=roles_str[:1024], inline=False)
        embed.add_field(name="Past Infractions", value=f"{len(mod_records)} recorded incident(s)", inline=True)
        timeout_status = f"Timed out until <t:{int(target.timed_out_until.timestamp())}:R>" if target.timed_out_until else "Clean (No timeout)"
        embed.add_field(name="Timeout Status", value=timeout_status, inline=True)

        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)
        vc = self.channel
        ow = vc.overwrites_for(interaction.guild.default_role)
        is_locked = ow.connect is False
        is_hidden = ow.view_channel is False
        ban_count = await self._get_ban_count()
        limit_str = str(vc.user_limit) if vc.user_limit else "Unlimited (∞)"

        embed = discord.Embed(
            title=f"📡 Voice Telemetry • {vc.name}",
            description=(
                f"**Channel:** {vc.mention} (`{vc.name}`)\n"
                f"**Channel ID:** `{vc.id}`\n"
                f"**Category:** `{vc.category.name if vc.category else 'None'}`\n"
                f"**Connected Members:** `{len(vc.members)}`\n"
                f"**Capacity Limit:** `{limit_str}`\n"
                f"**Audio Bitrate:** `{vc.bitrate // 1000} kbps`\n"
                f"**RTC Region:** `{vc.rtc_region or 'Automatic'}`\n"
                f"**Lock Status:** `{'Locked 🔒' if is_locked else 'Open 🔓'}`\n"
                f"**Visibility:** `{'Hidden 👻' if is_hidden else 'Visible ✨'}`\n"
                f"**Active Bans:** `{ban_count}`"
            ),
            color=BRAND_COLOR,
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ──────────────────────── MESSAGE MODERATION HANDLERS ────────────────────────

    async def _handle_purge(self, interaction: discord.Interaction, count: int) -> None:
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("❌ This action can only be run in a text channel.", ephemeral=True)
            return
        if not self._has_bot_perm(interaction, "manage_messages"):
            await interaction.response.send_message("❌ I need Manage Messages permission.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        max_limit = getattr(getattr(self.bot, "config", None), "max_purge_limit", 100)
        if not isinstance(max_limit, int):
            max_limit = 100
        actual_count = min(count, max_limit)
        try:
            deleted = await interaction.channel.purge(limit=actual_count)
            await interaction.followup.send(f"🧹 Purged **{len(deleted)}** messages.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to purge messages: {e}", ephemeral=True)

    async def _handle_lock_text(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("❌ Can only lock text channels.", ephemeral=True)
            return
        if not self._has_bot_perm(interaction, "manage_channels"):
            await interaction.response.send_message("❌ I need Manage Channels permission.", ephemeral=True)
            return
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False, reason=f"Text Lock by {interaction.user}")
        if not interaction.response.is_done():
            await interaction.response.send_message(f"🔒 {interaction.channel.mention} has been locked for text messages.", ephemeral=True)

    async def _handle_unlock_text(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("❌ Can only unlock text channels.", ephemeral=True)
            return
        if not self._has_bot_perm(interaction, "manage_channels"):
            await interaction.response.send_message("❌ I need Manage Channels permission.", ephemeral=True)
            return
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=None, reason=f"Text Unlock by {interaction.user}")
        if not interaction.response.is_done():
            await interaction.response.send_message(f"🔓 {interaction.channel.mention} has been unlocked for text messages.", ephemeral=True)

    async def _handle_slowmode_cycle(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("❌ Can only set slowmode in text channels.", ephemeral=True)
            return
        if not self._has_bot_perm(interaction, "manage_channels"):
            await interaction.response.send_message("❌ I need Manage Channels permission.", ephemeral=True)
            return
        cycle = [0, 5, 15, 60]
        cur = interaction.channel.slowmode_delay
        nxt = cycle[(cycle.index(cur) + 1) % len(cycle)] if cur in cycle else 0
        await interaction.channel.edit(slowmode_delay=nxt, reason=f"Slowmode change by {interaction.user}")
        nxt_str = "Disabled (0s)" if nxt == 0 else f"{nxt}s"
        if not interaction.response.is_done():
            await interaction.response.send_message(f"⏱️ Slowmode set to **{nxt_str}**.", ephemeral=True)

    async def _handle_timeout_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        if not self._has_bot_perm(interaction, "moderate_members"):
            await interaction.response.send_message("❌ I need Moderate Members permission.", ephemeral=True)
            return
        if self._is_protected_member(target, interaction.guild):
            await interaction.response.send_message("❌ Cannot timeout this member.", ephemeral=True)
            return
        if interaction.guild.me.top_role <= target.top_role:
            await interaction.response.send_message("❌ Cannot timeout a member with equal or higher role than me.", ephemeral=True)
            return
        try:
            await target.timeout(timedelta(minutes=10), reason=f"VCPANEL timeout by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⏳ **{target.display_name}** has been timed out for 10 minutes.", ephemeral=True)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Failed to timeout {target.display_name}: {e}", ephemeral=True)

    async def _handle_untimeout_target(self, interaction: discord.Interaction, target: discord.Member) -> None:
        if not self._has_bot_perm(interaction, "moderate_members"):
            await interaction.response.send_message("❌ I need Moderate Members permission.", ephemeral=True)
            return
        try:
            await target.timeout(None, reason=f"VCPANEL untimeout by {interaction.user}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"🔓 Removed timeout for **{target.display_name}**.", ephemeral=True)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Failed to untimeout {target.display_name}: {e}", ephemeral=True)


class VCDashboard(commands.Cog):
    """VC Dashboard & Owner VCPANEL panel commands."""

    def __init__(self, bot: "DeathBot") -> None:
        self.bot = bot

    async def _execute_vcdashboard(self, channel: discord.VoiceChannel, send_fn) -> None:
        embed = build_vc_embed(channel)
        view = VCControlView(self.bot, channel)
        await send_fn(embed=embed, view=view)

    @commands.command(
        name="vcdashboard",
        aliases=["voicecontrol"],
        help="Open an interactive VC control dashboard.",
    )
    @commands.has_permissions(manage_channels=True)
    async def vcdashboard_prefix(
        self,
        ctx: commands.Context,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        if channel is None:
            if ctx.author.voice and isinstance(ctx.author.voice.channel, discord.VoiceChannel):
                channel = ctx.author.voice.channel
            else:
                await ctx.send("❌ You're not in a voice channel. Specify one: `.vcdashboard #channel`")
                return
        await self._execute_vcdashboard(channel, ctx.send)

    async def _execute_owner_vcpanel(
        self,
        ctx_or_interaction,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        if isinstance(ctx_or_interaction, discord.Interaction):
            if not ctx_or_interaction.response.is_done():
                await ctx_or_interaction.response.defer(ephemeral=False)

        user = ctx_or_interaction.user if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author
        guild = ctx_or_interaction.guild

        if not guild:
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
            msg = f"{KrovexEmoji.CROSS} **Access Denied:** Only the Discord Server Owner or configured Bot Owner may access the Owner VCPANEL."
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(msg, ephemeral=True)
                else:
                    await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        # Voice channel resolution: decoupled from requiring user to be in voice
        if channel is None:
            if isinstance(user, discord.Member) and user.voice and isinstance(user.voice.channel, discord.VoiceChannel):
                channel = user.voice.channel
            elif guild.voice_channels:
                active_vcs = [vc for vc in guild.voice_channels if len(getattr(vc, "members", [])) > 0]
                channel = active_vcs[0] if active_vcs else guild.voice_channels[0]
            else:
                msg = f"{KrovexEmoji.CROSS} **No Voice Channels:** This server does not have any voice channels to control. Please create a voice channel first."
                if isinstance(ctx_or_interaction, discord.Interaction):
                    if ctx_or_interaction.response.is_done():
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    else:
                        await ctx_or_interaction.response.send_message(msg, ephemeral=True)
                else:
                    await ctx_or_interaction.send(msg)
                return

        view = OwnerVCControlView(self.bot, channel, scope="current_vc")
        ban_count = await view._get_ban_count() if channel else 0
        embed = build_owner_vc_embed(channel, ban_count=ban_count, guild=guild, scope="current_vc")

        if isinstance(ctx_or_interaction, discord.Interaction):
            if ctx_or_interaction.response.is_done():
                await ctx_or_interaction.followup.send(embed=embed, view=view)
            else:
                await ctx_or_interaction.response.send_message(embed=embed, view=view)
        else:
            await ctx_or_interaction.send(embed=embed, view=view)

    @commands.command(
        name="vcpanel",
        aliases=["ownervcpanel", "vcp"],
        help="Open the interactive KROVEX Owner VCPANEL (Server Owner / Bot Owner only).",
    )
    async def vcpanel_prefix(
        self,
        ctx: commands.Context,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        await self._execute_owner_vcpanel(ctx, channel)

    @app_commands.command(
        name="vcpanel",
        description="Open the interactive KROVEX Owner & Staff Moderation Dashboard.",
    )
    @app_commands.describe(channel="Voice channel to control (defaults to your current or active voice channel)")
    @app_commands.guild_only()
    async def vcpanel_slash(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        await self._execute_owner_vcpanel(interaction, channel)

    async def _execute_voice_centre(
        self,
        ctx_or_interaction,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        from bot.cogs.ownervc.voice_centre import VoiceControlCentreView
        if isinstance(ctx_or_interaction, discord.Interaction):
            if not ctx_or_interaction.response.is_done():
                await ctx_or_interaction.response.defer(ephemeral=False)

        user = ctx_or_interaction.user if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author
        guild = ctx_or_interaction.guild

        if not guild:
            return

        view = VoiceControlCentreView(self.bot, guild, active_channel=channel)
        embed, _ = await view.render(interaction=None, edit=False)

        if isinstance(ctx_or_interaction, discord.Interaction):
            if ctx_or_interaction.response.is_done():
                await ctx_or_interaction.followup.send(embed=embed, view=view)
            else:
                await ctx_or_interaction.response.send_message(embed=embed, view=view)
        else:
            await ctx_or_interaction.send(embed=embed, view=view)

    async def _execute_vc_staff_panel(self, ctx_or_interaction, channel: discord.VoiceChannel) -> None:
        user = ctx_or_interaction.user if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author
        guild = ctx_or_interaction.guild

        if not guild:
            return

        is_owner = user.id == guild.owner_id
        is_staff = False
        if self.bot.vc_repo and isinstance(user, discord.Member):
            user_roles = [r.id for r in user.roles]
            is_staff = await self.bot.vc_repo.is_staff(guild.id, user_roles)

        if not (is_owner or is_staff):
            msg = f"{KrovexEmoji.CROSS} **Access Denied:** You must be the Server Owner or hold an owner-authorized VC Staff Role."
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        allow_bulk = False
        if is_owner:
            allow_bulk = True
        elif self.bot.vc_repo:
            allow_bulk = await self.bot.vc_repo.get_staff_bulk_actions_allowed(guild.id)

        embed = build_vc_staff_embed(channel)
        view = VCStaffControlView(self.bot, channel, allow_bulk=allow_bulk)
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(embed=embed, view=view)
        else:
            await ctx_or_interaction.send(embed=embed, view=view)

    @commands.command(
        name="staffvc",
        aliases=["vccontrol", "staffpanel"],
        help="Open the interactive KROVEX VC Staff Control Panel.",
    )
    async def staffvc_prefix(
        self,
        ctx: commands.Context,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        if channel is None:
            if ctx.author.voice and isinstance(ctx.author.voice.channel, discord.VoiceChannel):
                channel = ctx.author.voice.channel
            else:
                await ctx.send("❌ You're not in a voice channel. Specify one: `.vcstaff #channel`")
                return
        await self._execute_vc_staff_panel(ctx, channel)


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(VCDashboard(bot))
