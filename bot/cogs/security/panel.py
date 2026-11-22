"""Security Control Panel — interactive UI for toggling security shields,
managing whitelist members/roles, and configuring per-event punishment policies.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.security.panel")
BRAND_COLOR = 0x9D4EDD

SECURITY_FEATURES: List[Tuple[str, str]] = [
    ("anti_nuke", "Anti-Nuke"),
    ("anti_raid", "Anti-Raid"),
    ("anti_spam", "Anti-Spam"),
    ("anti_phishing", "Anti-Phishing"),
    ("anti_bot", "Anti-Bot"),
    ("anti_webhook", "Anti-Webhook"),
    ("anti_mention_spam", "Anti-Mention Spam"),
]

SECURITY_EVENTS_MAP: Dict[str, str] = {
    "anti_nuke": "Anti-Nuke Global Policy",
    "channel_delete": "Channel Deletion Limit",
    "role_delete": "Role Deletion Limit",
    "mass_ban": "Mass Ban Threshold",
    "mass_kick": "Mass Kick Threshold",
    "anti_bot": "Unauthorized Bot Addition",
    "anti_webhook": "Rogue Webhook Creation",
    "anti_raid": "Anti-Raid & Mass Joins",
    "anti_spam": "Anti-Spam Flooding",
    "anti_phishing": "Phishing & Malicious Links",
    "anti_mention_spam": "Mass Mention Spam",
    "account_age": "Account Age Requirement",
}

PUNISHMENT_OPTIONS: List[Tuple[str, str, str]] = [
    ("not_configured", "Not Configured (Log Only)", "⚪"),
    ("warn", "Warning (Direct Message)", "⚠️"),
    ("timeout", "Timeout (10 Minutes)", "⏳"),
    ("quarantine", "Quarantine (Restricted Role)", "🛡️"),
    ("kick", "Kick from Server", "👢"),
    ("ban", "Permanent Ban", "🔨"),
]


def _check_admin_or_owner(bot: "DeathBot", user: Union[discord.User, discord.Member], guild: Optional[discord.Guild]) -> bool:
    """Helper ensuring server owner and bot owners always have administrative control."""
    if not user:
        return False
    if guild and user.id == guild.owner_id:
        return True
    raw_owners = getattr(bot.config, "owner_ids", [])
    if user.id in raw_owners or str(user.id) in [str(x) for x in raw_owners]:
        return True
    if hasattr(bot, "is_owner_or_co_owner") and callable(bot.is_owner_or_co_owner):
        try:
            if bot.is_owner_or_co_owner(user, guild):
                return True
        except Exception:
            pass
    perms = getattr(user, "guild_permissions", None)
    return perms.administrator if perms else False


# ═════════════════════════════════════════════════════════════════════════════
# 1. Interactive Security Whitelist Management View
# ═════════════════════════════════════════════════════════════════════════════

class WhitelistUserSelect(discord.ui.UserSelect):
    """Select menu to pick members to add to the security whitelist."""

    def __init__(self) -> None:
        super().__init__(
            placeholder="Select a member to add to security whitelist...",
            min_values=1,
            max_values=1,
            custom_id="sec_wl_add_user_select",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SecurityWhitelistView = self.view  # type: ignore
        member = self.values[0]
        if member.id in view.whitelist_users:
            await interaction.response.send_message(f"ℹ️ {member.mention} is already whitelisted.", ephemeral=True)
            return

        view.whitelist_users.append(member.id)
        bot: "DeathBot" = interaction.client  # type: ignore
        if bot.db_manager:
            await bot.db_manager.execute(
                "UPDATE security_settings SET whitelist_users=? WHERE guild_id=?",
                (json.dumps(view.whitelist_users), interaction.guild.id),
            )
            await bot.db_manager.execute(
                "INSERT OR IGNORE INTO trusted_users (guild_id, user_id, added_by) VALUES (?,?,?)",
                (interaction.guild.id, member.id, interaction.user.id),
            )

        await interaction.response.send_message(
            f"✅ **Member Whitelisted:** {member.mention} (`{member.id}`) will now bypass anti-nuke thresholds.",
            ephemeral=True,
        )
        await view._refresh(interaction)


class WhitelistRoleSelect(discord.ui.RoleSelect):
    """Select menu to pick roles to add to the security whitelist."""

    def __init__(self) -> None:
        super().__init__(
            placeholder="Select a role to add to security whitelist...",
            min_values=1,
            max_values=1,
            custom_id="sec_wl_add_role_select",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SecurityWhitelistView = self.view  # type: ignore
        role = self.values[0]
        if role.id in view.whitelist_roles:
            await interaction.response.send_message(f"ℹ️ {role.mention} is already whitelisted.", ephemeral=True)
            return

        view.whitelist_roles.append(role.id)
        bot: "DeathBot" = interaction.client  # type: ignore
        if bot.db_manager:
            await bot.db_manager.execute(
                "UPDATE security_settings SET whitelist_roles=? WHERE guild_id=?",
                (json.dumps(view.whitelist_roles), interaction.guild.id),
            )

        await interaction.response.send_message(
            f"✅ **Role Whitelisted:** {role.mention} will now bypass anti-nuke thresholds.",
            ephemeral=True,
        )
        await view._refresh(interaction)


class WhitelistRemoveUserSelect(discord.ui.Select):
    """Select menu to pick members to remove from the security whitelist."""

    def __init__(self, guild: discord.Guild, user_ids: List[int]) -> None:
        options = []
        for uid in user_ids[:25]:
            m = guild.get_member(uid)
            label = f"{m.name}" if m else f"User ID: {uid}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(uid),
                    description=f"ID: {uid}",
                    emoji="🗑️",
                )
            )
        if not options:
            options = [discord.SelectOption(label="No whitelisted members to remove", value="none", emoji="ℹ️")]

        super().__init__(
            placeholder="Select a member to remove from whitelist...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="sec_wl_remove_user_select",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        val = self.values[0]
        if val == "none":
            await interaction.response.send_message("ℹ️ No eligible members to remove.", ephemeral=True)
            return

        uid = int(val)
        view: SecurityWhitelistView = self.view  # type: ignore
        if uid in view.whitelist_users:
            view.whitelist_users.remove(uid)

        bot: "DeathBot" = interaction.client  # type: ignore
        if bot.db_manager:
            await bot.db_manager.execute(
                "UPDATE security_settings SET whitelist_users=? WHERE guild_id=?",
                (json.dumps(view.whitelist_users), interaction.guild.id),
            )
            await bot.db_manager.execute(
                "DELETE FROM trusted_users WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, uid),
            )

        await interaction.response.send_message(
            f"🗑️ **Member Removed:** `<@{uid}>` was removed from the security whitelist.",
            ephemeral=True,
        )
        await view._refresh(interaction)


class WhitelistRemoveRoleSelect(discord.ui.Select):
    """Select menu to pick roles to remove from the security whitelist."""

    def __init__(self, guild: discord.Guild, role_ids: List[int]) -> None:
        options = []
        for rid in role_ids[:25]:
            r = guild.get_role(rid)
            label = f"@{r.name}" if r else f"Role ID: {rid}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(rid),
                    description=f"ID: {rid}",
                    emoji="🗑️",
                )
            )
        if not options:
            options = [discord.SelectOption(label="No whitelisted roles to remove", value="none", emoji="ℹ️")]

        super().__init__(
            placeholder="Select a role to remove from whitelist...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="sec_wl_remove_role_select",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        val = self.values[0]
        if val == "none":
            await interaction.response.send_message("ℹ️ No eligible roles to remove.", ephemeral=True)
            return

        rid = int(val)
        view: SecurityWhitelistView = self.view  # type: ignore
        if rid in view.whitelist_roles:
            view.whitelist_roles.remove(rid)

        bot: "DeathBot" = interaction.client  # type: ignore
        if bot.db_manager:
            await bot.db_manager.execute(
                "UPDATE security_settings SET whitelist_roles=? WHERE guild_id=?",
                (json.dumps(view.whitelist_roles), interaction.guild.id),
            )

        await interaction.response.send_message(
            f"🗑️ **Role Removed:** `<@&{rid}>` was removed from the security whitelist.",
            ephemeral=True,
        )
        await view._refresh(interaction)


class SecurityWhitelistView(discord.ui.View):
    """Interactive management view for the security whitelist (users & roles)."""

    def __init__(
        self,
        bot: "DeathBot",
        guild: discord.Guild,
        whitelist_users: List[int],
        whitelist_roles: List[int],
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild = guild
        self.whitelist_users = list(whitelist_users)
        self.whitelist_roles = list(whitelist_roles)
        self.mode = "view"  # "view", "add_user", "remove_user", "add_role", "remove_role"
        self._rebuild_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not _check_admin_or_owner(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} Administrators only.", ephemeral=True)
            return False
        return True

    def _rebuild_components(self) -> None:
        self.clear_items()
        if self.mode == "add_user":
            self.add_item(WhitelistUserSelect())
        elif self.mode == "remove_user":
            self.add_item(WhitelistRemoveUserSelect(self.guild, self.whitelist_users))
        elif self.mode == "add_role":
            self.add_item(WhitelistRoleSelect())
        elif self.mode == "remove_role":
            self.add_item(WhitelistRemoveRoleSelect(self.guild, self.whitelist_roles))

        # Action Buttons (Row 2 & 3)
        add_u_btn = discord.ui.Button(
            label="Add Member",
            emoji="➕",
            style=discord.ButtonStyle.success if self.mode == "add_user" else discord.ButtonStyle.secondary,
            row=2,
        )
        add_u_btn.callback = self._btn_add_user
        self.add_item(add_u_btn)

        rem_u_btn = discord.ui.Button(
            label="Remove Member",
            emoji="➖",
            style=discord.ButtonStyle.danger if self.mode == "remove_user" else discord.ButtonStyle.secondary,
            row=2,
        )
        rem_u_btn.callback = self._btn_remove_user
        self.add_item(rem_u_btn)

        add_r_btn = discord.ui.Button(
            label="Add Role",
            emoji="🛡️",
            style=discord.ButtonStyle.primary if self.mode == "add_role" else discord.ButtonStyle.secondary,
            row=2,
        )
        add_r_btn.callback = self._btn_add_role
        self.add_item(add_r_btn)

        rem_r_btn = discord.ui.Button(
            label="Remove Role",
            emoji="❌",
            style=discord.ButtonStyle.danger if self.mode == "remove_role" else discord.ButtonStyle.secondary,
            row=2,
        )
        rem_r_btn.callback = self._btn_remove_role
        self.add_item(rem_r_btn)

        refresh_btn = discord.ui.Button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=3)
        refresh_btn.callback = self._btn_refresh
        self.add_item(refresh_btn)

    async def _btn_add_user(self, interaction: discord.Interaction) -> None:
        self.mode = "view" if self.mode == "add_user" else "add_user"
        await self._refresh(interaction)

    async def _btn_remove_user(self, interaction: discord.Interaction) -> None:
        self.mode = "view" if self.mode == "remove_user" else "remove_user"
        await self._refresh(interaction)

    async def _btn_add_role(self, interaction: discord.Interaction) -> None:
        self.mode = "view" if self.mode == "add_role" else "add_role"
        await self._refresh(interaction)

    async def _btn_remove_role(self, interaction: discord.Interaction) -> None:
        self.mode = "view" if self.mode == "remove_role" else "remove_role"
        await self._refresh(interaction)

    async def _btn_refresh(self, interaction: discord.Interaction) -> None:
        row = await self.bot.db_manager.fetchone(
            "SELECT whitelist_users, whitelist_roles FROM security_settings WHERE guild_id=?",
            (self.guild.id,),
        )
        if row:
            try:
                self.whitelist_users = json.loads(row["whitelist_users"] or "[]")
                self.whitelist_roles = json.loads(row["whitelist_roles"] or "[]")
            except Exception:
                pass
        self.mode = "view"
        await self._refresh(interaction)

    async def _refresh(self, interaction: discord.Interaction) -> None:
        self._rebuild_components()
        embed = self._build_embed()
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        elif interaction.message:
            await interaction.message.edit(embed=embed, view=self)

    def _build_embed(self) -> discord.Embed:
        users_str = "\n".join(f"• <@{uid}> (`{uid}`)" for uid in self.whitelist_users) if self.whitelist_users else "*No members whitelisted*"
        roles_str = "\n".join(f"• <@&{rid}> (`{rid}`)" for rid in self.whitelist_roles) if self.whitelist_roles else "*No roles whitelisted*"

        embed = discord.Embed(
            title=f"{KrovexEmoji.SECURITY} Security Whitelist Matrix • {self.guild.name}",
            description=(
                "Whitelisted members and roles bypass all anti-nuke threshold limits.\n"
                "**Server Sovereign:** <@" + str(self.guild.owner_id) + "> *(Always Protected)*\n\n"
                "### 👥 Whitelisted Members\n" + users_str + "\n\n"
                "### 🛡️ Whitelisted Roles\n" + roles_str
            ),
            color=BRAND_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="KROVEX Security • Use buttons below to authorize or revoke bypass status")
        return embed


# ═════════════════════════════════════════════════════════════════════════════
# 2. Interactive Per-Event Punishment Configuration View
# ═════════════════════════════════════════════════════════════════════════════

class SecurityEventSelect(discord.ui.Select):
    """Dropdown allowing server owner to pick which security event to configure."""

    def __init__(self, current_event: str) -> None:
        options = [
            discord.SelectOption(
                label=display_name[:100],
                value=ev_key,
                description=f"Configure punishment for {ev_key}",
                default=(ev_key == current_event),
                emoji="⚙️",
            )
            for ev_key, display_name in SECURITY_EVENTS_MAP.items()
        ]
        super().__init__(
            placeholder="Select a security event to configure...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
            custom_id="sec_cfg_event_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SecurityPunishmentConfigView = self.view  # type: ignore
        view.selected_event = self.values[0]
        view._rebuild_components()
        embed = view._build_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class PunishmentOptionSelect(discord.ui.Select):
    """Dropdown to select the punishment policy for the currently chosen event."""

    def __init__(self, current_punishment: str) -> None:
        options = [
            discord.SelectOption(
                label=label[:100],
                value=val,
                description=f"Action: {val}",
                default=(val == current_punishment),
                emoji=emoji,
            )
            for val, label, emoji in PUNISHMENT_OPTIONS
        ]
        super().__init__(
            placeholder="Select punishment policy for this event...",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
            custom_id="sec_cfg_punish_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SecurityPunishmentConfigView = self.view  # type: ignore
        view.selected_punishment = self.values[0]
        view._rebuild_components()
        embed = view._build_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class SecurityPunishmentConfigView(discord.ui.View):
    """Interactive per-guild, per-event punishment configuration dashboard."""

    def __init__(
        self,
        bot: "DeathBot",
        guild: discord.Guild,
        settings: dict,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild = guild
        self.settings = dict(settings)
        self.event_punishments = dict(self.settings.get("event_punishments") or {})
        if isinstance(self.event_punishments, str):
            try:
                self.event_punishments = json.loads(self.event_punishments)
            except Exception:
                self.event_punishments = {}

        self.selected_event = "anti_nuke"
        self.selected_punishment = self.event_punishments.get(self.selected_event, "not_configured")
        self._rebuild_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not _check_admin_or_owner(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} Server Sovereign / Administrators only.", ephemeral=True)
            return False
        return True

    def _rebuild_components(self) -> None:
        self.clear_items()
        # Row 0: Event Select
        self.add_item(SecurityEventSelect(self.selected_event))
        # Row 1: Punishment Select
        curr_pun = self.event_punishments.get(self.selected_event, "not_configured")
        self.add_item(PunishmentOptionSelect(self.selected_punishment or curr_pun))

        # Row 2: Actions
        save_btn = discord.ui.Button(label="Save Policy", emoji="💾", style=discord.ButtonStyle.success, row=2)
        save_btn.callback = self._handle_save
        self.add_item(save_btn)

        reset_btn = discord.ui.Button(label="Reset to Not Configured", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
        reset_btn.callback = self._handle_reset
        self.add_item(reset_btn)

    async def _handle_save(self, interaction: discord.Interaction) -> None:
        if self.selected_punishment in ("not_configured", "none"):
            self.event_punishments.pop(self.selected_event, None)
        else:
            self.event_punishments[self.selected_event] = self.selected_punishment

        if self.bot.db_manager:
            await self.bot.db_manager.execute(
                "UPDATE security_settings SET event_punishments=? WHERE guild_id=?",
                (json.dumps(self.event_punishments), self.guild.id),
            )
        self.selected_punishment = self.event_punishments.get(self.selected_event, "not_configured")
        self._rebuild_components()
        embed = self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
        disp_name = SECURITY_EVENTS_MAP.get(self.selected_event, self.selected_event)
        await interaction.followup.send(
            f"✅ **Policy Saved:** `{disp_name}` is now set to **{self.selected_punishment}**.",
            ephemeral=True,
        )

    async def _handle_reset(self, interaction: discord.Interaction) -> None:
        self.event_punishments.pop(self.selected_event, None)
        if self.bot.db_manager:
            await self.bot.db_manager.execute(
                "UPDATE security_settings SET event_punishments=? WHERE guild_id=?",
                (json.dumps(self.event_punishments), self.guild.id),
            )
        self.selected_punishment = "not_configured"
        self._rebuild_components()
        embed = self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
        disp_name = SECURITY_EVENTS_MAP.get(self.selected_event, self.selected_event)
        await interaction.followup.send(
            f"🔄 **Policy Reset:** `{disp_name}` reset to **Not Configured (Log Only)**.",
            ephemeral=True,
        )

    def _build_embed(self) -> discord.Embed:
        curr_p = self.event_punishments.get(self.selected_event, "not_configured")
        selected_display = SECURITY_EVENTS_MAP.get(self.selected_event, self.selected_event)

        table_lines = []
        for ev_k, ev_name in SECURITY_EVENTS_MAP.items():
            p_val = self.event_punishments.get(ev_k, "not_configured")
            icon = "⚪" if p_val in ("not_configured", "none") else "🔨"
            table_lines.append(f"{icon} **{ev_name}:** `{p_val}`")

        embed = discord.Embed(
            title=f"⚖️ Per-Server Security Punishment Matrix • {self.guild.name}",
            description=(
                "Configure independent punishment policies for every security event.\n"
                "**Non-Destructive Guarantee:** Unconfigured events default to **Log Only**.\n\n"
                f"### Currently Selected Event: **{selected_display}**\n"
                f"• Active Punishment: `{curr_p}`\n"
                f"• Staged Selection: `{self.selected_punishment}`\n\n"
                "### 📋 Configured Server Policies\n" + "\n".join(table_lines)
            ),
            color=BRAND_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="KROVEX Security Architecture • Select event and punishment, then click Save")
        return embed


# ═════════════════════════════════════════════════════════════════════════════
# 3. Main Security Control Panel View
# ═════════════════════════════════════════════════════════════════════════════

class SecurityPanelView(discord.ui.View):
    """Interactive security control panel with toggle buttons and management menus."""

    def __init__(self, bot: "DeathBot", guild_id: int, settings: dict) -> None:
        super().__init__(timeout=300.0)
        self.bot = bot
        self.guild_id = guild_id
        self.settings = dict(settings)
        self._rebuild_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not _check_admin_or_owner(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} Administrators only.", ephemeral=True)
            return False
        return True

    def _rebuild_buttons(self) -> None:
        self.clear_items()
        for idx, (field, label) in enumerate(SECURITY_FEATURES):
            enabled = bool(self.settings.get(field, True))
            row_idx = idx // 4
            btn = discord.ui.Button(
                label=f"{'ON' if enabled else 'OFF'} {label}",
                emoji=KrovexEmoji.SECURITY.partial if enabled else KrovexEmoji.CROSS.partial,
                style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger,
                custom_id=f"sec_toggle_{field}",
                row=row_idx,
            )
            btn.callback = self._make_toggle_cb(field)
            self.add_item(btn)

        # Row 2: Management sub-views
        punish_cfg_btn = discord.ui.Button(
            label="Configure Punishments",
            emoji="⚖️",
            style=discord.ButtonStyle.primary,
            custom_id="sec_open_punish_cfg",
            row=2,
        )
        punish_cfg_btn.callback = self._open_punish_config_cb
        self.add_item(punish_cfg_btn)

        whitelist_btn = discord.ui.Button(
            label="Manage Whitelist",
            emoji="🛡️",
            style=discord.ButtonStyle.secondary,
            custom_id="sec_open_whitelist",
            row=2,
        )
        whitelist_btn.callback = self._open_whitelist_cb
        self.add_item(whitelist_btn)

        refresh_btn = discord.ui.Button(
            label="Refresh",
            emoji="🔄",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        refresh_btn.callback = self._refresh_cb
        self.add_item(refresh_btn)

    def _make_toggle_cb(self, field: str):
        async def _callback(interaction: discord.Interaction) -> None:
            new_val = not bool(self.settings.get(field, True))
            await self.bot.db_manager.execute(
                f"UPDATE security_settings SET {field}=? WHERE guild_id=?",
                (1 if new_val else 0, self.guild_id),
            )
            self.settings[field] = 1 if new_val else 0
            self._rebuild_buttons()
            embed = build_security_embed(self.settings, interaction.guild)
            await interaction.response.edit_message(embed=embed, view=self)

        return _callback

    async def _open_punish_config_cb(self, interaction: discord.Interaction) -> None:
        view = SecurityPunishmentConfigView(self.bot, interaction.guild, self.settings)
        embed = view._build_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _open_whitelist_cb(self, interaction: discord.Interaction) -> None:
        wl_users = self.settings.get("whitelist_users", [])
        wl_roles = self.settings.get("whitelist_roles", [])
        if isinstance(wl_users, str):
            try:
                wl_users = json.loads(wl_users)
            except Exception:
                wl_users = []
        if isinstance(wl_roles, str):
            try:
                wl_roles = json.loads(wl_roles)
            except Exception:
                wl_roles = []
        view = SecurityWhitelistView(self.bot, interaction.guild, wl_users, wl_roles)
        embed = view._build_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _refresh_cb(self, interaction: discord.Interaction) -> None:
        row = await self.bot.db_manager.fetchone(
            "SELECT * FROM security_settings WHERE guild_id=?", (self.guild_id,)
        )
        if row:
            self.settings = dict(row)
        self._rebuild_buttons()
        embed = build_security_embed(self.settings, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True


def build_security_embed(settings: dict, guild: discord.Guild) -> discord.Embed:
    lines = []
    for field, label in SECURITY_FEATURES:
        enabled = bool(settings.get(field, True))
        status = "🟢 `ENABLED`" if enabled else "🔴 `DISABLED`"
        lines.append(f"{status} **{label}**")

    event_punishments = settings.get("event_punishments") or {}
    if isinstance(event_punishments, str):
        try:
            event_punishments = json.loads(event_punishments)
        except Exception:
            event_punishments = {}

    configured_count = len([v for v in event_punishments.values() if v not in ("not_configured", "none")])

    embed = discord.Embed(
        title=f"{KrovexEmoji.SECURITY} Security Control Panel • {guild.name}",
        description="\n".join(lines),
        color=BRAND_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="⚙️ Thresholds",
        value=(
            f"Mass Ban: `{settings.get('mass_ban_threshold', 3)}`\n"
            f"Mass Kick: `{settings.get('mass_kick_threshold', 3)}`\n"
            f"Channel Del: `{settings.get('channel_del_threshold', 3)}`\n"
            f"Role Del: `{settings.get('role_del_threshold', 3)}`\n"
            f"Time Window: `{settings.get('time_window_seconds', 15)}s`"
        ),
        inline=True,
    )
    embed.add_field(
        name="⚖️ Punishment Matrix",
        value=(
            f"Default Policy: `{settings.get('punishment', 'none')}`\n"
            f"Custom Policies: **{configured_count}** configured\n"
            "*(Unconfigured = Log Only)*"
        ),
        inline=True,
    )
    embed.add_field(
        name="👥 Account Age Requirement",
        value=f"`{settings.get('account_age_threshold_hours', 24)}h`",
        inline=True,
    )
    embed.set_footer(text=f"KROVEX Security • Use buttons below to configure policies or toggle shields")
    return embed


class SecurityPanel(commands.Cog):
    """Security control panel command."""

    def __init__(self, bot: "DeathBot") -> None:
        self.bot = bot

    async def _get_or_create_settings(self, guild_id: int) -> dict:
        row = await self.bot.db_manager.fetchone(
            "SELECT * FROM security_settings WHERE guild_id=?", (guild_id,)
        )
        if not row:
            await self.bot.db_manager.execute(
                "INSERT OR IGNORE INTO security_settings (guild_id) VALUES (?)", (guild_id,)
            )
            row = await self.bot.db_manager.fetchone(
                "SELECT * FROM security_settings WHERE guild_id=?", (guild_id,)
            )
        return dict(row) if row else {}

    @commands.command(
        name="securitypanel",
        aliases=["secpanel"],
        help="Open an interactive security control panel.",
    )
    @commands.has_permissions(administrator=True)
    async def securitypanel_prefix(self, ctx: commands.Context) -> None:
        settings = await self._get_or_create_settings(ctx.guild.id)
        embed = build_security_embed(settings, ctx.guild)
        view = SecurityPanelView(self.bot, ctx.guild.id, settings)
        await ctx.send(embed=embed, view=view)


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(SecurityPanel(bot))
