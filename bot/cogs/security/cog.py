"""Advanced Security & Anti-Nuke cog for Death Bot."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.security")
BRAND_COLOR = 0x9D4EDD

# ── Confirm View ──────────────────────────────────────────────────────────────

class ConfirmView(discord.ui.View):
    """Simple Yes/No confirmation view."""

    def __init__(self, author_id: int) -> None:
        super().__init__(timeout=30)
        self.author_id = author_id
        self.confirmed: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Not your button.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = False
        await interaction.response.defer()
        self.stop()


# ── Security Cog ─────────────────────────────────────────────────────────────

class Security(commands.GroupCog, group_name="security", group_description="Advanced security and anti-nuke protection"):
    """Advanced security, anti-nuke, and anti-raid protection."""

    def __init__(self, bot: "DeathBot") -> None:
        super().__init__()
        self.bot = bot

    # ── DB Helpers ────────────────────────────────────────────────────────────

    async def _get_settings(self, guild_id: int) -> dict:
        if hasattr(self.bot, "security_repo"):
            return await self.bot.security_repo.get_settings(guild_id)
        row = await self.bot.db.fetchone(
            "SELECT * FROM security_settings WHERE guild_id=?", (guild_id,)
        )
        if not row:
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO security_settings (guild_id) VALUES (?)", (guild_id,)
            )
            row = await self.bot.db.fetchone(
                "SELECT * FROM security_settings WHERE guild_id=?", (guild_id,)
            )
        result = dict(row) if row else {}
        for field in ("whitelist_users", "whitelist_roles"):
            if field in result and isinstance(result[field], str):
                try:
                    result[field] = json.loads(result[field])
                except Exception:
                    result[field] = []
        return result

    async def _update_settings(self, guild_id: int, **kwargs) -> None:
        if not kwargs:
            return
        if hasattr(self.bot, "security_repo"):
            await self.bot.security_repo.update_settings(guild_id, **kwargs)
            return
        # Ensure row exists
        await self._get_settings(guild_id)
        set_parts: List[str] = []
        params: List = []
        for k, v in kwargs.items():
            set_parts.append(f"{k}=?")
            params.append(json.dumps(v) if isinstance(v, (list, dict)) else v)
        params.append(guild_id)
        await self.bot.db.execute(
            f"UPDATE security_settings SET {', '.join(set_parts)} WHERE guild_id=?",
            tuple(params),
        )

    @staticmethod
    def _bool_flag(value) -> bool:
        return bool(value)

    @staticmethod
    def _status_circle(enabled: bool) -> str:
        return "🟢" if enabled else "🔴"

    # ── Helper: permission guards ─────────────────────────────────────────────

    def _is_admin(self, ctx: UnifiedContext) -> bool:
        if not ctx.guild:
            return False
        user = ctx.interaction.user if ctx.is_interaction else ctx.author
        if not user:
            return False
        # 1. Discord Server Sovereign is always admin
        if user.id == ctx.guild.owner_id:
            return True
        # 2. Configured Bot Owner / Co-owner is always admin
        raw_owners = getattr(self.bot.config, "owner_ids", [])
        if user.id in raw_owners or str(user.id) in [str(x) for x in raw_owners]:
            return True
        if hasattr(self.bot, "is_owner_or_co_owner") and callable(self.bot.is_owner_or_co_owner):
            try:
                if self.bot.is_owner_or_co_owner(user, ctx.guild):
                    return True
            except Exception:
                pass
        # 3. Discord Administrator permission
        perms = getattr(user, "guild_permissions", None)
        return perms.administrator if perms else False

    def _is_owner(self, ctx: UnifiedContext) -> bool:
        if not ctx.guild:
            return False
        user = ctx.interaction.user if ctx.is_interaction else ctx.author
        if not user:
            return False
        # 1. Server Owner
        if user.id == ctx.guild.owner_id:
            return True
        # 2. Bot Owner
        raw_owners = getattr(self.bot.config, "owner_ids", [])
        if user.id in raw_owners or str(user.id) in [str(x) for x in raw_owners]:
            return True
        if hasattr(self.bot, "is_owner_or_co_owner") and callable(self.bot.is_owner_or_co_owner):
            try:
                if self.bot.is_owner_or_co_owner(user, ctx.guild):
                    return True
            except Exception:
                pass
        return False

    # ══════════════════════════════════════════════════════════════════════════
    # 1. securitystatus
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_securitystatus(self, uctx: UnifiedContext) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        s = await self._get_settings(uctx.guild.id)
        modules = {
            "Anti-Nuke": "anti_nuke",
            "Anti-Raid": "anti_raid",
            "Anti-Spam": "anti_spam",
            "Anti-Phishing": "anti_phishing",
            "Anti-Bot": "anti_bot",
            "Anti-Webhook": "anti_webhook",
            "Anti-Mention Spam": "anti_mention_spam",
        }
        lines = []
        for label, key in modules.items():
            state = self._bool_flag(s.get(key, True))
            lines.append(f"{self._status_circle(state)} **{label}** — {'Enabled' if state else 'Disabled'}")

        event_punishments = s.get("event_punishments") or {}
        if isinstance(event_punishments, str):
            try:
                event_punishments = json.loads(event_punishments)
            except Exception:
                event_punishments = {}
        configured_events = [f"`{k}`: {v}" for k, v in event_punishments.items() if v not in ("not_configured", "none")]
        custom_str = ", ".join(configured_events) if configured_events else "None (All Unconfigured = Log Only)"

        thresholds = (
            f"⚔️ Mass Ban Threshold: **{s.get('mass_ban_threshold', 3)}**\n"
            f"👢 Mass Kick Threshold: **{s.get('mass_kick_threshold', 3)}**\n"
            f"📛 Channel Del Threshold: **{s.get('channel_del_threshold', 3)}**\n"
            f"🎭 Role Del Threshold: **{s.get('role_del_threshold', 3)}**\n"
            f"⏱️ Time Window: **{s.get('time_window_seconds', 15)}s**\n"
            f"⚖️ Default Punishment: **{s.get('punishment', 'none')}**\n"
            f"📋 Custom Policies: {custom_str}"
        )

        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.SHIELD_CROWN} Security Status",
            description="\n".join(lines),
            color=BRAND_COLOR,
        )
        embed.add_field(name="Thresholds", value=thresholds, inline=False)
        log_ch = s.get("log_channel_id")
        embed.add_field(
            name="Log Channel",
            value=f"<#{log_ch}>" if log_ch else "Not set",
            inline=True,
        )
        await uctx.send(embed=embed)

    @commands.command(name="securitystatus", help="Show all security module states.")
    @commands.has_permissions(administrator=True)
    async def securitystatus_prefix(self, ctx: commands.Context) -> None:
        await self._execute_securitystatus(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="status", description="Show all security module states.")
    @app_commands.default_permissions(administrator=True)
    async def securitystatus_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_securitystatus(UnifiedContext.from_interaction(interaction))

    # ══════════════════════════════════════════════════════════════════════════
    # 2. antinuke
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_antinuke(self, uctx: UnifiedContext, action: Optional[str]) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        s = await self._get_settings(uctx.guild.id)
        current = self._bool_flag(s.get("anti_nuke", True))

        if action is None:
            embed = EmbedBuilder.base(
                title="🛡️ Anti-Nuke",
                description=f"Anti-Nuke is currently {self._status_circle(current)} **{'Enabled' if current else 'Disabled'}**.",
                color=BRAND_COLOR,
            )
            await uctx.send(embed=embed)
            return

        action = action.lower()
        if action not in ("enable", "disable"):
            await uctx.send_error("Invalid Argument", "Use `enable` or `disable`.")
            return

        new_val = 1 if action == "enable" else 0
        await self._update_settings(uctx.guild.id, anti_nuke=new_val)
        await uctx.send_success("Anti-Nuke Updated", f"Anti-Nuke has been **{action}d**.")

    @commands.command(name="antinuke", help="Toggle anti-nuke protection on/off.")
    @commands.has_permissions(administrator=True)
    async def antinuke_prefix(self, ctx: commands.Context, action: Optional[str] = None) -> None:
        await self._execute_antinuke(UnifiedContext.from_prefix(ctx), action)

    @app_commands.command(name="antinuke", description="Toggle anti-nuke protection on/off.")
    @app_commands.describe(action="enable or disable (omit to check status)")
    @app_commands.default_permissions(administrator=True)
    async def antinuke_slash(self, interaction: discord.Interaction, action: Optional[str] = None) -> None:
        await self._execute_antinuke(UnifiedContext.from_interaction(interaction), action)

    # ══════════════════════════════════════════════════════════════════════════
    # 3. antiraid
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_antiraid(self, uctx: UnifiedContext, action: Optional[str]) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        s = await self._get_settings(uctx.guild.id)
        current = self._bool_flag(s.get("anti_raid", True))

        if action is None:
            embed = EmbedBuilder.base(
                title="🚨 Anti-Raid",
                description=f"Anti-Raid is currently {self._status_circle(current)} **{'Enabled' if current else 'Disabled'}**.",
                color=BRAND_COLOR,
            )
            await uctx.send(embed=embed)
            return

        action = action.lower()
        if action not in ("enable", "disable"):
            await uctx.send_error("Invalid Argument", "Use `enable` or `disable`.")
            return

        await self._update_settings(uctx.guild.id, anti_raid=1 if action == "enable" else 0)
        await uctx.send_success("Anti-Raid Updated", f"Anti-Raid has been **{action}d**.")

    @commands.command(name="antiraid", help="Toggle anti-raid protection on/off.")
    @commands.has_permissions(administrator=True)
    async def antiraid_prefix(self, ctx: commands.Context, action: Optional[str] = None) -> None:
        await self._execute_antiraid(UnifiedContext.from_prefix(ctx), action)

    @app_commands.command(name="antiraid", description="Toggle anti-raid protection on/off.")
    @app_commands.describe(action="enable or disable (omit to check status)")
    @app_commands.default_permissions(administrator=True)
    async def antiraid_slash(self, interaction: discord.Interaction, action: Optional[str] = None) -> None:
        await self._execute_antiraid(UnifiedContext.from_interaction(interaction), action)

    # ══════════════════════════════════════════════════════════════════════════
    # 4. antispam
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_antispam(self, uctx: UnifiedContext, action: Optional[str]) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        s = await self._get_settings(uctx.guild.id)
        current = self._bool_flag(s.get("anti_spam", True))

        if action is None:
            embed = EmbedBuilder.base(
                title="📵 Anti-Spam",
                description=f"Anti-Spam is currently {self._status_circle(current)} **{'Enabled' if current else 'Disabled'}**.",
                color=BRAND_COLOR,
            )
            await uctx.send(embed=embed)
            return

        action = action.lower()
        if action not in ("enable", "disable"):
            await uctx.send_error("Invalid Argument", "Use `enable` or `disable`.")
            return

        await self._update_settings(uctx.guild.id, anti_spam=1 if action == "enable" else 0)
        await uctx.send_success("Anti-Spam Updated", f"Anti-Spam has been **{action}d**.")

    @commands.command(name="antispam", help="Toggle anti-spam protection on/off.")
    @commands.has_permissions(administrator=True)
    async def antispam_prefix(self, ctx: commands.Context, action: Optional[str] = None) -> None:
        await self._execute_antispam(UnifiedContext.from_prefix(ctx), action)

    @app_commands.command(name="antispam", description="Toggle anti-spam protection on/off.")
    @app_commands.describe(action="enable or disable (omit to check status)")
    @app_commands.default_permissions(administrator=True)
    async def antispam_slash(self, interaction: discord.Interaction, action: Optional[str] = None) -> None:
        await self._execute_antispam(UnifiedContext.from_interaction(interaction), action)

    # ══════════════════════════════════════════════════════════════════════════
    # 5. antiphishing
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_antiphishing(self, uctx: UnifiedContext, action: Optional[str]) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        s = await self._get_settings(uctx.guild.id)
        current = self._bool_flag(s.get("anti_phishing", True))

        if action is None:
            embed = EmbedBuilder.base(
                title="🎣 Anti-Phishing",
                description=f"Anti-Phishing is currently {self._status_circle(current)} **{'Enabled' if current else 'Disabled'}**.",
                color=BRAND_COLOR,
            )
            await uctx.send(embed=embed)
            return

        action = action.lower()
        if action not in ("enable", "disable"):
            await uctx.send_error("Invalid Argument", "Use `enable` or `disable`.")
            return

        await self._update_settings(uctx.guild.id, anti_phishing=1 if action == "enable" else 0)
        await uctx.send_success("Anti-Phishing Updated", f"Anti-Phishing has been **{action}d**.")

    @commands.command(name="antiphishing", help="Toggle anti-phishing protection on/off.")
    @commands.has_permissions(administrator=True)
    async def antiphishing_prefix(self, ctx: commands.Context, action: Optional[str] = None) -> None:
        await self._execute_antiphishing(UnifiedContext.from_prefix(ctx), action)

    @app_commands.command(name="antiphishing", description="Toggle anti-phishing protection on/off.")
    @app_commands.describe(action="enable or disable (omit to check status)")
    @app_commands.default_permissions(administrator=True)
    async def antiphishing_slash(self, interaction: discord.Interaction, action: Optional[str] = None) -> None:
        await self._execute_antiphishing(UnifiedContext.from_interaction(interaction), action)

    # ══════════════════════════════════════════════════════════════════════════
    # 6. antibot
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_antibot(self, uctx: UnifiedContext, action: Optional[str]) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        s = await self._get_settings(uctx.guild.id)
        current = self._bool_flag(s.get("anti_bot", True))

        if action is None:
            embed = EmbedBuilder.base(
                title="🤖 Anti-Bot",
                description=f"Anti-Bot is currently {self._status_circle(current)} **{'Enabled' if current else 'Disabled'}**.",
                color=BRAND_COLOR,
            )
            await uctx.send(embed=embed)
            return

        action = action.lower()
        if action not in ("enable", "disable"):
            await uctx.send_error("Invalid Argument", "Use `enable` or `disable`.")
            return

        await self._update_settings(uctx.guild.id, anti_bot=1 if action == "enable" else 0)
        await uctx.send_success("Anti-Bot Updated", f"Anti-Bot has been **{action}d**.")

    @commands.command(name="antibot", help="Toggle anti-bot protection on/off.")
    @commands.has_permissions(administrator=True)
    async def antibot_prefix(self, ctx: commands.Context, action: Optional[str] = None) -> None:
        await self._execute_antibot(UnifiedContext.from_prefix(ctx), action)

    @app_commands.command(name="antibot", description="Toggle anti-bot protection on/off.")
    @app_commands.describe(action="enable or disable (omit to check status)")
    @app_commands.default_permissions(administrator=True)
    async def antibot_slash(self, interaction: discord.Interaction, action: Optional[str] = None) -> None:
        await self._execute_antibot(UnifiedContext.from_interaction(interaction), action)

    # ══════════════════════════════════════════════════════════════════════════
    # 7. antibanthreshold
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_antibanthreshold(self, uctx: UnifiedContext, number: int) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return
        if not (1 <= number <= 10):
            await uctx.send_error("Invalid Range", "Threshold must be between 1 and 10.")
            return

        await self._update_settings(uctx.guild.id, mass_ban_threshold=number)
        await uctx.send_success("Ban Threshold Set", f"Mass ban threshold set to **{number}**.")

    @commands.command(name="antibanthreshold", help="Set mass ban detection threshold (1-10).")
    @commands.has_permissions(administrator=True)
    async def antibanthreshold_prefix(self, ctx: commands.Context, number: int) -> None:
        await self._execute_antibanthreshold(UnifiedContext.from_prefix(ctx), number)

    @app_commands.command(name="antibanthreshold", description="Set mass ban detection threshold (1-10).")
    @app_commands.describe(number="Threshold value between 1 and 10")
    @app_commands.default_permissions(administrator=True)
    async def antibanthreshold_slash(self, interaction: discord.Interaction, number: int) -> None:
        await self._execute_antibanthreshold(UnifiedContext.from_interaction(interaction), number)

    # ══════════════════════════════════════════════════════════════════════════
    # 8. antikickthreshold
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_antikickthreshold(self, uctx: UnifiedContext, number: int) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return
        if not (1 <= number <= 10):
            await uctx.send_error("Invalid Range", "Threshold must be between 1 and 10.")
            return

        await self._update_settings(uctx.guild.id, mass_kick_threshold=number)
        await uctx.send_success("Kick Threshold Set", f"Mass kick threshold set to **{number}**.")

    @commands.command(name="antikickthreshold", help="Set mass kick detection threshold (1-10).")
    @commands.has_permissions(administrator=True)
    async def antikickthreshold_prefix(self, ctx: commands.Context, number: int) -> None:
        await self._execute_antikickthreshold(UnifiedContext.from_prefix(ctx), number)

    @app_commands.command(name="antikickthreshold", description="Set mass kick detection threshold (1-10).")
    @app_commands.describe(number="Threshold value between 1 and 10")
    @app_commands.default_permissions(administrator=True)
    async def antikickthreshold_slash(self, interaction: discord.Interaction, number: int) -> None:
        await self._execute_antikickthreshold(UnifiedContext.from_interaction(interaction), number)

    # ══════════════════════════════════════════════════════════════════════════
    # 9. antichannelthreshold
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_antichannelthreshold(self, uctx: UnifiedContext, number: int) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return
        if not (1 <= number <= 10):
            await uctx.send_error("Invalid Range", "Threshold must be between 1 and 10.")
            return

        await self._update_settings(uctx.guild.id, channel_del_threshold=number)
        await uctx.send_success("Channel Threshold Set", f"Channel deletion threshold set to **{number}**.")

    @commands.command(name="antichannelthreshold", help="Set channel deletion detection threshold (1-10).")
    @commands.has_permissions(administrator=True)
    async def antichannelthreshold_prefix(self, ctx: commands.Context, number: int) -> None:
        await self._execute_antichannelthreshold(UnifiedContext.from_prefix(ctx), number)

    @app_commands.command(name="antichannelthreshold", description="Set channel deletion detection threshold (1-10).")
    @app_commands.describe(number="Threshold value between 1 and 10")
    @app_commands.default_permissions(administrator=True)
    async def antichannelthreshold_slash(self, interaction: discord.Interaction, number: int) -> None:
        await self._execute_antichannelthreshold(UnifiedContext.from_interaction(interaction), number)

    # ══════════════════════════════════════════════════════════════════════════
    # 10. antirolethreshold
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_antirolethreshold(self, uctx: UnifiedContext, number: int) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return
        if not (1 <= number <= 10):
            await uctx.send_error("Invalid Range", "Threshold must be between 1 and 10.")
            return

        await self._update_settings(uctx.guild.id, role_del_threshold=number)
        await uctx.send_success("Role Threshold Set", f"Role deletion threshold set to **{number}**.")

    @commands.command(name="antirolethreshold", help="Set role deletion detection threshold (1-10).")
    @commands.has_permissions(administrator=True)
    async def antirolethreshold_prefix(self, ctx: commands.Context, number: int) -> None:
        await self._execute_antirolethreshold(UnifiedContext.from_prefix(ctx), number)

    @app_commands.command(name="antirolethreshold", description="Set role deletion detection threshold (1-10).")
    @app_commands.describe(number="Threshold value between 1 and 10")
    @app_commands.default_permissions(administrator=True)
    async def antirolethreshold_slash(self, interaction: discord.Interaction, number: int) -> None:
        await self._execute_antirolethreshold(UnifiedContext.from_interaction(interaction), number)

    # ══════════════════════════════════════════════════════════════════════════
    # 11. securitywindow
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_securitywindow(self, uctx: UnifiedContext, seconds: int) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return
        if not (5 <= seconds <= 120):
            await uctx.send_error("Invalid Range", "Window must be between 5 and 120 seconds.")
            return

        await self._update_settings(uctx.guild.id, time_window_seconds=seconds)
        await uctx.send_success("Time Window Set", f"Detection time window set to **{seconds}s**.")

    @commands.command(name="securitywindow", help="Set the detection time window in seconds (5-120).")
    @commands.has_permissions(administrator=True)
    async def securitywindow_prefix(self, ctx: commands.Context, seconds: int) -> None:
        await self._execute_securitywindow(UnifiedContext.from_prefix(ctx), seconds)

    @app_commands.command(name="window", description="Set the detection time window in seconds (5-120).")
    @app_commands.describe(seconds="Window duration between 5 and 120 seconds")
    @app_commands.default_permissions(administrator=True)
    async def securitywindow_slash(self, interaction: discord.Interaction, seconds: int) -> None:
        await self._execute_securitywindow(UnifiedContext.from_interaction(interaction), seconds)

    # ══════════════════════════════════════════════════════════════════════════
    # 12. securitypunish
    # ══════════════════════════════════════════════════════════════════════════

    VALID_PUNISHMENTS = ("not_configured", "log_only", "none", "warn", "timeout", "quarantine", "kick", "ban")
    SUPPORTED_EVENTS = (
        "anti_nuke",
        "channel_delete",
        "role_delete",
        "mass_ban",
        "mass_kick",
        "anti_bot",
        "anti_webhook",
        "anti_raid",
        "anti_spam",
        "anti_phishing",
        "anti_mention_spam",
        "account_age",
    )

    async def _execute_securitypunish(
        self, uctx: UnifiedContext, action: str, event: Optional[str] = None
    ) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        action = action.lower()
        if action not in self.VALID_PUNISHMENTS:
            await uctx.send_error(
                "Invalid Punishment",
                f"Valid options: {', '.join(f'`{p}`' for p in self.VALID_PUNISHMENTS)}",
            )
            return

        if event:
            event = event.lower()
            if event not in self.SUPPORTED_EVENTS:
                await uctx.send_error(
                    "Invalid Event",
                    f"Valid security events: {', '.join(f'`{e}`' for e in self.SUPPORTED_EVENTS)}",
                )
                return

            if hasattr(self.bot, "security_repo") and self.bot.security_repo:
                await self.bot.security_repo.set_event_punishment(uctx.guild.id, event, action)
            else:
                s = await self._get_settings(uctx.guild.id)
                ep = s.get("event_punishments") or {}
                if isinstance(ep, str):
                    try:
                        ep = json.loads(ep)
                    except Exception:
                        ep = {}
                if action in ("not_configured", "none"):
                    ep.pop(event, None)
                else:
                    ep[event] = action
                await self._update_settings(uctx.guild.id, event_punishments=ep)

            display_act = "Not Configured (Log Only)" if action in ("not_configured", "none") else action.capitalize()
            await uctx.send_success("Event Policy Updated", f"Punishment for **{event}** is now set to **{display_act}**.")
        else:
            await self._update_settings(uctx.guild.id, punishment=action)
            display_act = "Not Configured (Log Only)" if action in ("not_configured", "none") else action.capitalize()
            await uctx.send_success("Default Punishment Set", f"Default fallback security punishment set to **{display_act}**.")

    @commands.command(name="securitypunish", help="Set punishment for security violations (optionally specify event).")
    @commands.has_permissions(administrator=True)
    async def securitypunish_prefix(self, ctx: commands.Context, action: str, event: Optional[str] = None) -> None:
        await self._execute_securitypunish(UnifiedContext.from_prefix(ctx), action, event)

    @app_commands.command(name="punish", description="Configure punishment policy for security violations.")
    @app_commands.describe(
        action="not_configured, log_only, warn, timeout, quarantine, kick, or ban",
        event="Optional: specific security event to configure independently",
    )
    @app_commands.default_permissions(administrator=True)
    async def securitypunish_slash(
        self, interaction: discord.Interaction, action: str, event: Optional[str] = None
    ) -> None:
        await self._execute_securitypunish(UnifiedContext.from_interaction(interaction), action, event)

    # ══════════════════════════════════════════════════════════════════════════
    # 13. securitylogchannel
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_securitylogchannel(
        self, uctx: UnifiedContext, channel: Optional[discord.TextChannel]
    ) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        if channel is None:
            await self._update_settings(uctx.guild.id, log_channel_id=None)
            await uctx.send_success("Log Channel Cleared", "Security log channel has been cleared.")
        else:
            await self._update_settings(uctx.guild.id, log_channel_id=channel.id)
            await uctx.send_success("Log Channel Set", f"Security logs will be sent to {channel.mention}.")

    @commands.command(name="securitylogchannel", help="Set or clear the security log channel.")
    @commands.has_permissions(administrator=True)
    async def securitylogchannel_prefix(
        self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None
    ) -> None:
        await self._execute_securitylogchannel(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="logchannel", description="Set or clear the security log channel.")
    @app_commands.describe(channel="Text channel for security logs (omit to clear)")
    @app_commands.default_permissions(administrator=True)
    async def securitylogchannel_slash(
        self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None
    ) -> None:
        await self._execute_securitylogchannel(UnifiedContext.from_interaction(interaction), channel)

    # ══════════════════════════════════════════════════════════════════════════
    # 14. trustedadd
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_trustedadd(self, uctx: UnifiedContext, user: discord.Member) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_owner(uctx):
            await uctx.send_error("Owner Only", "Only the server owner can manage trusted users.")
            return

        author_id = uctx.interaction.user.id if uctx.is_interaction else uctx.author.id  # type: ignore[union-attr]

        # Insert into trusted_users table
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO trusted_users (guild_id, user_id, added_by) VALUES (?, ?, ?)",
            (uctx.guild.id, user.id, author_id),
        )

        # Update whitelist_users JSON in settings
        s = await self._get_settings(uctx.guild.id)
        whitelist = s.get("whitelist_users", [])
        if isinstance(whitelist, str):
            try:
                whitelist = json.loads(whitelist)
            except Exception:
                whitelist = []
        if user.id not in whitelist:
            whitelist.append(user.id)
            await self._update_settings(uctx.guild.id, whitelist_users=whitelist)

        await uctx.send_success("Trusted User Added", f"{user.mention} has been added to the trusted whitelist.")

    @commands.command(name="trustedadd", help="Add a user to the trusted whitelist. Owner only.")
    @commands.check(lambda ctx: ctx.guild is not None and ctx.author.id == ctx.guild.owner_id)
    async def trustedadd_prefix(self, ctx: commands.Context, user: discord.Member) -> None:
        await self._execute_trustedadd(UnifiedContext.from_prefix(ctx), user)

    @app_commands.command(name="trustedadd", description="Add a user to the trusted whitelist. Owner only.")
    @app_commands.describe(user="The user to add to the trusted whitelist")
    async def trustedadd_slash(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await self._execute_trustedadd(UnifiedContext.from_interaction(interaction), user)

    # ══════════════════════════════════════════════════════════════════════════
    # 15. trustedremove
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_trustedremove(self, uctx: UnifiedContext, user: discord.Member) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_owner(uctx):
            await uctx.send_error("Owner Only", "Only the server owner can manage trusted users.")
            return

        await self.bot.db.execute(
            "DELETE FROM trusted_users WHERE guild_id=? AND user_id=?",
            (uctx.guild.id, user.id),
        )

        # Update whitelist_users JSON in settings
        s = await self._get_settings(uctx.guild.id)
        whitelist = s.get("whitelist_users", [])
        if isinstance(whitelist, str):
            try:
                whitelist = json.loads(whitelist)
            except Exception:
                whitelist = []
        if user.id in whitelist:
            whitelist.remove(user.id)
            await self._update_settings(uctx.guild.id, whitelist_users=whitelist)

        await uctx.send_success("Trusted User Removed", f"{user.mention} has been removed from the trusted whitelist.")

    @commands.command(name="trustedremove", help="Remove a user from the trusted whitelist. Owner only.")
    @commands.check(lambda ctx: ctx.guild is not None and ctx.author.id == ctx.guild.owner_id)
    async def trustedremove_prefix(self, ctx: commands.Context, user: discord.Member) -> None:
        await self._execute_trustedremove(UnifiedContext.from_prefix(ctx), user)

    @app_commands.command(name="trustedremove", description="Remove a user from the trusted whitelist. Owner only.")
    @app_commands.describe(user="The user to remove from the trusted whitelist")
    async def trustedremove_slash(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await self._execute_trustedremove(UnifiedContext.from_interaction(interaction), user)

    # ══════════════════════════════════════════════════════════════════════════
    # 16. trustedlist
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_trustedlist(self, uctx: UnifiedContext) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        rows = await self.bot.db.fetchall(
            "SELECT user_id, added_by, added_at FROM trusted_users WHERE guild_id=? ORDER BY added_at DESC",
            (uctx.guild.id,),
        )

        if not rows:
            embed = EmbedBuilder.base(
                title="🛡️ Trusted Users",
                description="No trusted users found for this server.",
                color=BRAND_COLOR,
            )
            await uctx.send(embed=embed)
            return

        # Paginate at 10 per embed field (show first page only here)
        lines = []
        for row in rows[:25]:
            row = dict(row) if hasattr(row, "keys") else {"user_id": row[0], "added_by": row[1], "added_at": row[2]}
            lines.append(f"<@{row['user_id']}> — added by <@{row['added_by']}> on {row['added_at']}")

        embed = EmbedBuilder.base(
            title=f"🛡️ Trusted Users ({len(rows)} total)",
            description="\n".join(lines),
            color=BRAND_COLOR,
        )
        await uctx.send(embed=embed)

    @commands.command(name="trustedlist", help="List all trusted/whitelisted users.")
    @commands.has_permissions(administrator=True)
    async def trustedlist_prefix(self, ctx: commands.Context) -> None:
        await self._execute_trustedlist(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="trustedlist", description="List all trusted/whitelisted users.")
    @app_commands.default_permissions(administrator=True)
    async def trustedlist_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_trustedlist(UnifiedContext.from_interaction(interaction))

    # ══════════════════════════════════════════════════════════════════════════
    # 17. lockdown
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_lockdown(self, uctx: UnifiedContext, reason: Optional[str]) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        reason = reason or "Emergency lockdown initiated by admin."
        failed = []

        for channel in uctx.guild.text_channels:
            try:
                overwrite = channel.overwrites_for(uctx.guild.default_role)
                overwrite.send_messages = False
                await channel.set_permissions(uctx.guild.default_role, overwrite=overwrite, reason=reason)
            except discord.Forbidden:
                failed.append(channel.name)
            except Exception as exc:
                logger.warning("Lockdown failed for #%s: %s", channel.name, exc)
                failed.append(channel.name)

        s = await self._get_settings(uctx.guild.id)
        log_ch_id = s.get("log_channel_id")
        if log_ch_id:
            log_ch = uctx.guild.get_channel(log_ch_id)
            if log_ch:
                author = uctx.interaction.user if uctx.is_interaction else uctx.author
                log_embed = EmbedBuilder.base(
                    title="🔒 Server Lockdown",
                    description=f"Lockdown initiated by {author.mention}\n**Reason:** {reason}",
                    color=0xFF3366,
                )
                try:
                    await log_ch.send(embed=log_embed)  # type: ignore[union-attr]
                except Exception:
                    pass

        desc = f"🔒 All text channels have been locked.\n**Reason:** {reason}"
        if failed:
            desc += f"\n\n⚠️ Failed channels: {', '.join(f'#{n}' for n in failed[:10])}"
        await uctx.send_success("Server Locked Down", desc)

    @commands.command(name="lockdown", help="Emergency lockdown: lock all text channels for @everyone.")
    @commands.has_permissions(administrator=True)
    async def lockdown_prefix(self, ctx: commands.Context, *, reason: Optional[str] = None) -> None:
        await self._execute_lockdown(UnifiedContext.from_prefix(ctx), reason)

    @app_commands.command(name="lockdown", description="Emergency lockdown: lock all text channels for @everyone.")
    @app_commands.describe(reason="Reason for the lockdown")
    @app_commands.default_permissions(administrator=True)
    async def lockdown_slash(self, interaction: discord.Interaction, reason: Optional[str] = None) -> None:
        await self._execute_lockdown(UnifiedContext.from_interaction(interaction), reason)

    # ══════════════════════════════════════════════════════════════════════════
    # 18. unlockdown
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_unlockdown(self, uctx: UnifiedContext, reason: Optional[str]) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        reason = reason or "Lockdown lifted by admin."
        failed = []

        for channel in uctx.guild.text_channels:
            try:
                overwrite = channel.overwrites_for(uctx.guild.default_role)
                overwrite.send_messages = None  # Reset to inherit
                await channel.set_permissions(uctx.guild.default_role, overwrite=overwrite, reason=reason)
            except discord.Forbidden:
                failed.append(channel.name)
            except Exception as exc:
                logger.warning("Unlockdown failed for #%s: %s", channel.name, exc)
                failed.append(channel.name)

        s = await self._get_settings(uctx.guild.id)
        log_ch_id = s.get("log_channel_id")
        if log_ch_id:
            log_ch = uctx.guild.get_channel(log_ch_id)
            if log_ch:
                author = uctx.interaction.user if uctx.is_interaction else uctx.author
                log_embed = EmbedBuilder.base(
                    title="🔓 Server Unlocked",
                    description=f"Lockdown lifted by {author.mention}\n**Reason:** {reason}",
                    color=0x00F5A0,
                )
                try:
                    await log_ch.send(embed=log_embed)  # type: ignore[union-attr]
                except Exception:
                    pass

        desc = f"🔓 All text channels have been unlocked.\n**Reason:** {reason}"
        if failed:
            desc += f"\n\n⚠️ Failed channels: {', '.join(f'#{n}' for n in failed[:10])}"
        await uctx.send_success("Server Unlocked", desc)

    @commands.command(name="unlockdown", help="Restore channel permissions after lockdown.")
    @commands.has_permissions(administrator=True)
    async def unlockdown_prefix(self, ctx: commands.Context, *, reason: Optional[str] = None) -> None:
        await self._execute_unlockdown(UnifiedContext.from_prefix(ctx), reason)

    @app_commands.command(name="unlockdown", description="Restore channel permissions after lockdown.")
    @app_commands.describe(reason="Reason for lifting the lockdown")
    @app_commands.default_permissions(administrator=True)
    async def unlockdown_slash(self, interaction: discord.Interaction, reason: Optional[str] = None) -> None:
        await self._execute_unlockdown(UnifiedContext.from_interaction(interaction), reason)

    # ══════════════════════════════════════════════════════════════════════════
    # 19. securityreset
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_securityreset(self, uctx: UnifiedContext) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_owner(uctx):
            await uctx.send_error("Owner Only", "Only the server owner can reset security settings.")
            return

        # Send confirmation
        view = ConfirmView(
            uctx.interaction.user.id if uctx.is_interaction else uctx.author.id  # type: ignore[union-attr]
        )
        confirm_embed = EmbedBuilder.base(
            title="⚠️ Confirm Security Reset",
            description=(
                "This will reset **all** security settings to their defaults for this server.\n\n"
                "Press **Confirm** to proceed or **Cancel** to abort."
            ),
            color=0xF59E0B,
        )

        if uctx.is_interaction:
            await uctx.interaction.response.send_message(embed=confirm_embed, view=view, ephemeral=True)  # type: ignore[union-attr]
        else:
            msg = await uctx.prefix_ctx.send(embed=confirm_embed, view=view)  # type: ignore[union-attr]

        await view.wait()

        if not view.confirmed:
            cancel_embed = EmbedBuilder.base(
                title="Cancelled",
                description="Security reset has been cancelled.",
                color=0x3B82F6,
            )
            if uctx.is_interaction:
                await uctx.interaction.edit_original_response(embed=cancel_embed, view=None)  # type: ignore[union-attr]
            else:
                await msg.edit(embed=cancel_embed, view=None)
            return

        # Delete and reinsert defaults
        await self.bot.db.execute(
            "DELETE FROM security_settings WHERE guild_id=?", (uctx.guild.id,)
        )
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO security_settings (guild_id) VALUES (?)", (uctx.guild.id,)
        )
        await self.bot.db.execute(
            "DELETE FROM trusted_users WHERE guild_id=?", (uctx.guild.id,)
        )

        done_embed = EmbedBuilder.base(
            title="✅ Security Reset Complete",
            description="All security settings have been reset to defaults.",
            color=0x00F5A0,
        )
        if uctx.is_interaction:
            await uctx.interaction.edit_original_response(embed=done_embed, view=None)  # type: ignore[union-attr]
        else:
            await msg.edit(embed=done_embed, view=None)

    @commands.command(name="securityreset", help="Reset all security settings to defaults. Owner only.")
    @commands.check(lambda ctx: ctx.guild is not None and ctx.author.id == ctx.guild.owner_id)
    async def securityreset_prefix(self, ctx: commands.Context) -> None:
        await self._execute_securityreset(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="reset", description="Reset all security settings to defaults. Owner only.")
    async def securityreset_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_securityreset(UnifiedContext.from_interaction(interaction))

    # ══════════════════════════════════════════════════════════════════════════
    # 20. securitylogs
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_securitylogs(self, uctx: UnifiedContext, limit: int) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        limit = max(1, min(limit, 25))

        # Try security_incidents first, fall back to security_logs
        try:
            rows = await self.bot.db.fetchall(
                "SELECT * FROM security_incidents WHERE guild_id=? ORDER BY timestamp DESC LIMIT ?",
                (uctx.guild.id, limit),
            )
            table = "security_incidents"
        except Exception:
            try:
                rows = await self.bot.db.fetchall(
                    "SELECT * FROM security_logs WHERE guild_id=? ORDER BY timestamp DESC LIMIT ?",
                    (uctx.guild.id, limit),
                )
                table = "security_logs"
            except Exception:
                rows = []

        if not rows:
            embed = EmbedBuilder.base(
                title="📋 Security Logs",
                description="No security incidents recorded for this server.",
                color=BRAND_COLOR,
            )
            await uctx.send(embed=embed)
            return

        lines = []
        for row in rows:
            row = dict(row) if hasattr(row, "keys") else row
            if table == "security_incidents":
                actor = row.get("actor_id", "?")
                action = row.get("action_type", "?")
                details = row.get("details", "")
                ts = row.get("timestamp", "?")
                lines.append(f"**{action}** — <@{actor}> — `{ts}`\n> {details[:80]}")
            else:
                actor = row.get("actor_id", "?")
                action = row.get("action_type", "?")
                ts = row.get("timestamp", "?")
                lines.append(f"**{action}** — <@{actor}> — `{ts}`")

        embed = EmbedBuilder.base(
            title=f"📋 Security Logs (last {len(rows)})",
            description="\n\n".join(lines),
            color=BRAND_COLOR,
        )
        await uctx.send(embed=embed)

    @commands.command(name="securitylogs", help="Show last N security incidents (default 10, max 25).")
    @commands.has_permissions(administrator=True)
    async def securitylogs_prefix(self, ctx: commands.Context, limit: int = 10) -> None:
        await self._execute_securitylogs(UnifiedContext.from_prefix(ctx), limit)

    @app_commands.command(name="logs", description="Show last N security incidents (default 10, max 25).")
    @app_commands.describe(limit="Number of incidents to show (1-25)")
    @app_commands.default_permissions(administrator=True)
    async def securitylogs_slash(self, interaction: discord.Interaction, limit: int = 10) -> None:
        await self._execute_securitylogs(UnifiedContext.from_interaction(interaction), limit)

    # ══════════════════════════════════════════════════════════════════════════
    # 21. securityaudit
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_securityaudit(self, uctx: UnifiedContext) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        guild = uctx.guild
        me = guild.me
        issues: List[str] = []
        good: List[str] = []

        # 1. Bot permissions
        required_perms = {
            "ban_members": "Ban Members",
            "kick_members": "Kick Members",
            "manage_roles": "Manage Roles",
            "manage_channels": "Manage Channels",
            "view_audit_log": "View Audit Log",
            "moderate_members": "Timeout Members",
        }
        bot_perms = me.guild_permissions
        for perm, label in required_perms.items():
            if getattr(bot_perms, perm, False):
                good.append(f"✅ **{label}**")
            else:
                issues.append(f"❌ Missing: **{label}**")

        # 2. Role hierarchy
        if me.top_role.position > 1:
            good.append(f"✅ Role hierarchy OK (position {me.top_role.position})")
        else:
            issues.append("❌ Bot role is too low in the hierarchy.")

        # 3. 2FA / verification level
        if guild.verification_level.value >= 2:
            good.append(f"✅ Verification level: **{guild.verification_level.name}**")
        else:
            issues.append(f"⚠️ Low verification level: **{guild.verification_level.name}** (consider raising it)")

        # 4. Admin-less check (non-bot admins)
        admin_members = [
            m for m in guild.members
            if m.guild_permissions.administrator and not m.bot and m.id != guild.owner_id
        ]
        if len(admin_members) > 5:
            issues.append(f"⚠️ {len(admin_members)} non-owner members have Administrator — consider reducing.")
        else:
            good.append(f"✅ Admin count: **{len(admin_members)}** non-owner admins")

        all_lines = good + issues
        embed = EmbedBuilder.base(
            title="🔍 Security Audit Report",
            description="\n".join(all_lines) if all_lines else "Nothing to report.",
            color=BRAND_COLOR if not issues else 0xF59E0B,
        )
        embed.add_field(
            name="Summary",
            value=f"✅ **{len(good)}** checks passed | ❌ **{len(issues)}** issues found",
            inline=False,
        )
        await uctx.send(embed=embed)

    @commands.command(name="securityaudit", help="Run a quick security audit of bot permissions and role hierarchy.")
    @commands.has_permissions(administrator=True)
    async def securityaudit_prefix(self, ctx: commands.Context) -> None:
        await self._execute_securityaudit(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="audit", description="Run a quick security audit of bot permissions and role hierarchy.")
    @app_commands.default_permissions(administrator=True)
    async def securityaudit_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_securityaudit(UnifiedContext.from_interaction(interaction))

    # ══════════════════════════════════════════════════════════════════════════
    # 22. securitywhitelist
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_securitywhitelist(self, uctx: UnifiedContext) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        s = await self._get_settings(uctx.guild.id)
        whitelist_users = s.get("whitelist_users", [])
        whitelist_roles = s.get("whitelist_roles", [])

        if isinstance(whitelist_users, str):
            try:
                whitelist_users = json.loads(whitelist_users)
            except Exception:
                whitelist_users = []
        if isinstance(whitelist_roles, str):
            try:
                whitelist_roles = json.loads(whitelist_roles)
            except Exception:
                whitelist_roles = []

        from bot.cogs.security.panel import SecurityWhitelistView
        view = SecurityWhitelistView(self.bot, uctx.guild, whitelist_users, whitelist_roles)
        embed = view._build_embed()
        await uctx.send(embed=embed, view=view)

    @commands.command(name="securitywhitelist", help="List whitelisted users and roles.")
    @commands.has_permissions(administrator=True)
    async def securitywhitelist_prefix(self, ctx: commands.Context) -> None:
        await self._execute_securitywhitelist(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="whitelist", description="List whitelisted users and roles.")
    @app_commands.default_permissions(administrator=True)
    async def securitywhitelist_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_securitywhitelist(UnifiedContext.from_interaction(interaction))

    # ══════════════════════════════════════════════════════════════════════════
    # 23. antinukeconfig
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_antinukeconfig(self, uctx: UnifiedContext) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return

        s = await self._get_settings(uctx.guild.id)
        nuke_enabled = self._bool_flag(s.get("anti_nuke", True))

        embed = EmbedBuilder.base(
            title="🛡️ Anti-Nuke Configuration",
            description=f"Status: {self._status_circle(nuke_enabled)} **{'Enabled' if nuke_enabled else 'Disabled'}**",
            color=BRAND_COLOR,
        )
        embed.add_field(
            name="⚔️ Thresholds",
            value=(
                f"Mass Ban: **{s.get('mass_ban_threshold', 3)}** bans\n"
                f"Mass Kick: **{s.get('mass_kick_threshold', 3)}** kicks\n"
                f"Channel Deletions: **{s.get('channel_del_threshold', 3)}** deletions\n"
                f"Role Deletions: **{s.get('role_del_threshold', 3)}** deletions"
            ),
            inline=True,
        )
        embed.add_field(
            name="⏱️ Timing",
            value=(
                f"Time Window: **{s.get('time_window_seconds', 15)}s**"
            ),
            inline=True,
        )
        embed.add_field(
            name="⚖️ Response",
            value=(
                f"Punishment: **{s.get('punishment', 'quarantine')}**\n"
                f"Anti-Raid: {self._status_circle(self._bool_flag(s.get('anti_raid', True)))}\n"
                f"Anti-Bot: {self._status_circle(self._bool_flag(s.get('anti_bot', True)))}\n"
                f"Anti-Webhook: {self._status_circle(self._bool_flag(s.get('anti_webhook', True)))}"
            ),
            inline=True,
        )
        await uctx.send(embed=embed)

    @commands.command(name="antinukeconfig", help="Show all anti-nuke thresholds and current values.")
    @commands.has_permissions(administrator=True)
    async def antinukeconfig_prefix(self, ctx: commands.Context) -> None:
        await self._execute_antinukeconfig(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="antinukeconfig", description="Show all anti-nuke thresholds and current values.")
    @app_commands.default_permissions(administrator=True)
    async def antinukeconfig_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_antinukeconfig(UnifiedContext.from_interaction(interaction))

    # ══════════════════════════════════════════════════════════════════════════
    # 24. joinratelimit
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_joinratelimit(self, uctx: UnifiedContext, max_joins: int, seconds: int) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return
        if max_joins < 1:
            await uctx.send_error("Invalid Value", "Max joins must be at least 1.")
            return
        if seconds < 1:
            await uctx.send_error("Invalid Value", "Seconds must be at least 1.")
            return

        await self._update_settings(uctx.guild.id, join_rate_max=max_joins, join_rate_seconds=seconds)
        await uctx.send_success(
            "Join Rate Limit Set",
            f"Anti-raid join rate set to **{max_joins}** joins per **{seconds}s**.",
        )

    @commands.command(name="joinratelimit", help="Set anti-raid join rate limit (max joins in X seconds).")
    @commands.has_permissions(administrator=True)
    async def joinratelimit_prefix(self, ctx: commands.Context, max_joins: int, seconds: int) -> None:
        await self._execute_joinratelimit(UnifiedContext.from_prefix(ctx), max_joins, seconds)

    @app_commands.command(name="joinratelimit", description="Set anti-raid join rate limit (max joins in X seconds).")
    @app_commands.describe(
        max_joins="Maximum number of joins allowed in the time window",
        seconds="Time window in seconds",
    )
    @app_commands.default_permissions(administrator=True)
    async def joinratelimit_slash(self, interaction: discord.Interaction, max_joins: int, seconds: int) -> None:
        await self._execute_joinratelimit(UnifiedContext.from_interaction(interaction), max_joins, seconds)

    # ══════════════════════════════════════════════════════════════════════════
    # 25. accountage
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_accountage(self, uctx: UnifiedContext, hours: int) -> None:
        if not uctx.guild:
            await uctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not self._is_admin(uctx):
            await uctx.send_error("Permission Denied", "Administrator permission required.")
            return
        if not (0 <= hours <= 720):
            await uctx.send_error("Invalid Range", "Account age must be between 0 (disabled) and 720 hours (30 days).")
            return

        await self._update_settings(uctx.guild.id, account_age_threshold_hours=hours)
        if hours == 0:
            await uctx.send_success("Account Age Disabled", "No minimum account age requirement.")
        else:
            days = hours // 24
            remaining_hours = hours % 24
            age_str = f"{days}d {remaining_hours}h" if days else f"{hours}h"
            await uctx.send_success(
                "Account Age Set",
                f"Minimum account age set to **{age_str}** ({hours} hours).",
            )

    @commands.command(name="accountage", help="Set minimum account age in hours (0 = disabled, 1-720).")
    @commands.has_permissions(administrator=True)
    async def accountage_prefix(self, ctx: commands.Context, hours: int) -> None:
        await self._execute_accountage(UnifiedContext.from_prefix(ctx), hours)

    @app_commands.command(name="accountage", description="Set minimum account age requirement in hours (0 = disabled).")
    @app_commands.describe(hours="Minimum account age in hours (0 to disable, max 720)")
    @app_commands.default_permissions(administrator=True)
    async def accountage_slash(self, interaction: discord.Interaction, hours: int) -> None:
        await self._execute_accountage(UnifiedContext.from_interaction(interaction), hours)


# ── Setup ─────────────────────────────────────────────────────────────────────

async def setup(bot: "DeathBot") -> None:
    """Setup hook to register the Security cog."""
    await bot.add_cog(Security(bot))
