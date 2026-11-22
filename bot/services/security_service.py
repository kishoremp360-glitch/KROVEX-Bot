"""Security service: event-driven anti-nuke, anti-raid, and incident tracking."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import discord
from discord.ext import commands

from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.security")

QUARANTINE_ROLE_NAME = "⚠️ Quarantined"


class SecurityService(commands.Cog):
    """Monitors guild events and enforces anti-nuke / anti-raid protection."""

    def __init__(self, bot: "DeathBot") -> None:
        self.bot = bot
        # guild_id → list of (actor_id, action_type, timestamp)
        self._action_log: Dict[int, List[Tuple[int, str, datetime]]] = defaultdict(list)

    # ─── Internal Helpers ───────────────────────────────────────────────────

    def _prune_window(self, guild_id: int, window_seconds: int) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        self._action_log[guild_id] = [
            e for e in self._action_log[guild_id] if e[2] > cutoff
        ]

    def _track(self, guild_id: int, actor_id: int, action_type: str, window_seconds: int) -> int:
        self._action_log[guild_id].append((actor_id, action_type, datetime.now(timezone.utc)))
        self._prune_window(guild_id, window_seconds)
        return sum(
            1 for e in self._action_log[guild_id]
            if e[0] == actor_id and e[1] == action_type
        )

    def _is_bot_owner(self, user_id: int) -> bool:
        """Helper to determine whether a user ID belongs to a configured bot owner."""
        raw_owners = getattr(getattr(self.bot, "config", None), "owner_ids", []) or []
        try:
            if user_id in raw_owners or str(user_id) in [str(x) for x in raw_owners]:
                return True
        except Exception:
            pass

        bot_owners = getattr(self.bot, "owner_ids", None) or []
        try:
            if user_id in bot_owners or str(user_id) in [str(x) for x in bot_owners]:
                return True
        except Exception:
            pass

        return False

    def _is_whitelisted(
        self,
        actor_id: int,
        guild: discord.Guild,
        whitelist_users: Any = None,
        whitelist_roles: Any = None,
        member: Optional[discord.Member] = None,
    ) -> bool:
        """Evaluate if an actor ID or member bypasses security thresholds via ownership or whitelist.

        Order of precedence:
        1. Server Sovereign (guild owner)
        2. Bot Owner (listed in config.owner_ids)
        3. Direct User Whitelist (whitelist_users)
        4. Role-based Whitelist (whitelist_roles)
        """
        # 1. Server Owner Immunity
        if guild and actor_id == getattr(guild, "owner_id", None):
            return True

        # 2. Bot Owner Immunity
        if self._is_bot_owner(actor_id):
            return True

        # 3. Direct user whitelist
        whitelist_u = set()
        if isinstance(whitelist_users, (list, set, tuple)):
            for u in whitelist_users:
                try:
                    whitelist_u.add(int(u))
                except (ValueError, TypeError):
                    pass
        elif isinstance(whitelist_users, str) and whitelist_users.strip():
            try:
                parsed = json.loads(whitelist_users)
                if isinstance(parsed, list):
                    for u in parsed:
                        try:
                            whitelist_u.add(int(u))
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass

        if actor_id in whitelist_u:
            return True

        # 4. Role-Based Whitelist
        whitelist_r = set()
        if isinstance(whitelist_roles, (list, set, tuple)):
            for r in whitelist_roles:
                try:
                    whitelist_r.add(int(r))
                except (ValueError, TypeError):
                    pass
        elif isinstance(whitelist_roles, str) and whitelist_roles.strip():
            try:
                parsed = json.loads(whitelist_roles)
                if isinstance(parsed, list):
                    for r in parsed:
                        try:
                            whitelist_r.add(int(r))
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass

        if whitelist_r:
            if member is None and guild and hasattr(guild, "get_member"):
                try:
                    member = guild.get_member(actor_id)
                except Exception:
                    member = None

            if member and hasattr(member, "roles"):
                for role in getattr(member, "roles", []):
                    role_id = getattr(role, "id", None)
                    if role_id is not None:
                        try:
                            if int(role_id) in whitelist_r:
                                return True
                        except (ValueError, TypeError):
                            pass

        return False

    async def _get_quarantine_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        role = discord.utils.get(guild.roles, name=QUARANTINE_ROLE_NAME)
        if not role:
            try:
                role = await guild.create_role(
                    name=QUARANTINE_ROLE_NAME,
                    permissions=discord.Permissions.none(),
                    color=discord.Color.red(),
                    reason="Death Bot: Quarantine role auto-created",
                )
                # Deny send/view in all channels
                for channel in guild.channels:
                    try:
                        await channel.set_permissions(
                            role,
                            send_messages=False,
                            view_channel=False,
                            reason="Death Bot: Quarantine lock",
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.error("Could not create quarantine role in %s: %s", guild.id, e)
        return role

    async def _apply_punishment(
        self,
        guild: discord.Guild,
        member: Optional[discord.Member],
        punishment: str,
        reason: str,
    ) -> None:
        if not member:
            return

        norm_punishment = (punishment or "not_configured").lower()

        # 1. Server Owner Sovereign Immunity
        if member.id == getattr(guild, "owner_id", None):
            logger.info(
                "Server Sovereign immunity safeguard active: Skipped punishment '%s' for owner %s (%s) in '%s'.",
                norm_punishment,
                getattr(member, "name", member.id),
                member.id,
                getattr(guild, "name", guild.id),
            )
            return

        # 2. Bot Owner Immunity
        if self._is_bot_owner(member.id):
            logger.info(
                "Bot Owner immunity safeguard active: Skipped punishment '%s' for owner %s (%s) in '%s'.",
                norm_punishment,
                getattr(member, "name", member.id),
                member.id,
                getattr(guild, "name", guild.id),
            )
            return

        if norm_punishment in ("not_configured", "log_only", "none"):
            logger.info(
                "Security policy for %s in '%s' is '%s': Logged without destructive action.",
                member.id, guild.name, norm_punishment,
            )
            return

        # Check role hierarchy: bot must be strictly above the member to execute actions
        me = getattr(guild, "me", None)
        if me and hasattr(member, "top_role") and hasattr(me, "top_role"):
            pos_me = getattr(getattr(me, "top_role", None), "position", 0)
            pos_member = getattr(getattr(member, "top_role", None), "position", 0)
            if isinstance(pos_me, (int, float)) and isinstance(pos_member, (int, float)):
                if pos_member >= pos_me:
                    logger.warning(
                        "Cannot execute %s on %s in '%s': Member's top role (pos %d) >= bot's top role (pos %d).",
                        norm_punishment, member.id, guild.name, pos_member, pos_me,
                    )
                    return

        try:
            if norm_punishment == "warn":
                try:
                    await member.send(
                        f"⚠️ **Security Warning ({guild.name}):** Your recent actions triggered server security thresholds ({reason}). Further unauthorized activity may result in moderation action."
                    )
                except Exception:
                    pass
            elif norm_punishment == "ban":
                if me and hasattr(me, "guild_permissions") and not me.guild_permissions.ban_members:
                    logger.warning("Missing permissions to ban %s in %s", member.id, guild.id)
                    return
                await guild.ban(member, reason=f"KROVEX Security: {reason}", delete_message_days=0)
            elif norm_punishment == "kick":
                if me and hasattr(me, "guild_permissions") and not me.guild_permissions.kick_members:
                    logger.warning("Missing permissions to kick %s in %s", member.id, guild.id)
                    return
                await guild.kick(member, reason=f"KROVEX Security: {reason}")
            elif norm_punishment == "timeout":
                if me and hasattr(me, "guild_permissions") and not me.guild_permissions.moderate_members:
                    logger.warning("Missing permissions to timeout %s in %s", member.id, guild.id)
                    return
                until = datetime.now(timezone.utc) + timedelta(minutes=10)
                await member.timeout(until, reason=f"KROVEX Security: {reason}")
            elif norm_punishment == "quarantine":
                if me and hasattr(me, "guild_permissions") and not me.guild_permissions.manage_roles:
                    logger.warning("Missing permissions to quarantine %s in %s", member.id, guild.id)
                    return
                role = await self._get_quarantine_role(guild)
                if role:
                    await member.add_roles(role, reason=f"KROVEX Security: {reason}")
        except discord.Forbidden:
            logger.warning("Missing permissions to execute %s on %s in %s", norm_punishment, member.id, guild.id)
        except Exception as e:
            logger.error(
                "Punishment error (%s) for %s: %s",
                norm_punishment,
                member.id if member else "?",
                e,
            )

    async def _handle_nuke_action(
        self,
        guild: discord.Guild,
        actor_id: int,
        action_type: str,
        detail: str,
        threshold: int,
    ) -> None:
        if not hasattr(self.bot, "security_repo"):
            return
        settings = await self.bot.security_repo.get_or_create_settings(guild.id)
        if not settings.get("enabled") or not settings.get("anti_nuke"):
            return
        window = settings.get("time_window_seconds", 15)
        whitelist_raw = settings.get("whitelist_users", "[]")
        roles_raw = settings.get("whitelist_roles", "[]")
        member = guild.get_member(actor_id)
        if self._is_whitelisted(actor_id, guild, whitelist_raw, roles_raw, member=member):
            return
        count = self._track(guild.id, actor_id, action_type, window)
        if count >= threshold:
            event_punishments = settings.get("event_punishments") or {}
            if isinstance(event_punishments, str):
                try:
                    event_punishments = json.loads(event_punishments)
                except Exception:
                    event_punishments = {}

            # Specific event policy -> anti_nuke general policy -> fallback (default: not_configured)
            punishment = (
                event_punishments.get(action_type)
                or event_punishments.get("anti_nuke")
                or settings.get("punishment")
                or "not_configured"
            )
            # Default policy: Never force a destructive default if not configured
            if punishment in ("none", None):
                punishment = "not_configured"

            member = guild.get_member(actor_id)
            await self._apply_punishment(guild, member, punishment, f"{action_type} threshold exceeded")
            await self.bot.security_repo.log_incident(
                guild.id,
                actor_id,
                action_type,
                f"{detail} (count={count}, threshold={threshold})",
                punishment,
            )
            log_ch_id = settings.get("log_channel_id")
            if log_ch_id:
                ch = guild.get_channel(log_ch_id)
                if ch:
                    embed = discord.Embed(
                        title=f"{KrovexEmoji.SECURITY} Security Alert",
                        description=(
                            f"**Action:** {action_type}\n"
                            f"**Actor:** <@{actor_id}>\n"
                            f"**Detail:** {detail}\n"
                            f"**Count:** {count}/{threshold}\n"
                            f"**Punishment Policy:** {punishment}"
                        ),
                        color=0xFF0000,
                        timestamp=datetime.now(timezone.utc),
                    )
                    try:
                        await ch.send(embed=embed)
                    except Exception:
                        pass

    # ─── Event Listeners ────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        if not hasattr(self.bot, "security_repo"):
            return
        settings = await self.bot.security_repo.get_or_create_settings(guild.id)
        threshold = settings.get("mass_ban_threshold", 3)
        actor_id = guild.owner_id
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
                actor_id = entry.user.id
                break
        except Exception:
            pass
        await self._handle_nuke_action(guild, actor_id, "mass_ban", f"Banned {user}", threshold)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        guild = member.guild
        if not hasattr(self.bot, "security_repo"):
            return
        settings = await self.bot.security_repo.get_or_create_settings(guild.id)
        threshold = settings.get("mass_kick_threshold", 3)
        actor_id = guild.owner_id
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
                if entry.target and entry.target.id == member.id:
                    actor_id = entry.user.id
                    break
        except Exception:
            pass
        await self._handle_nuke_action(guild, actor_id, "mass_kick", f"Kicked {member}", threshold)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        guild = channel.guild
        if not hasattr(self.bot, "security_repo"):
            return
        settings = await self.bot.security_repo.get_or_create_settings(guild.id)
        threshold = settings.get("channel_del_threshold", 3)
        actor_id = guild.owner_id
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
                actor_id = entry.user.id
                break
        except Exception:
            pass
        await self._handle_nuke_action(guild, actor_id, "channel_delete", f"Deleted #{channel.name}", threshold)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        guild = role.guild
        if not hasattr(self.bot, "security_repo"):
            return
        settings = await self.bot.security_repo.get_or_create_settings(guild.id)
        threshold = settings.get("role_del_threshold", 3)
        actor_id = guild.owner_id
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
                actor_id = entry.user.id
                break
        except Exception:
            pass
        await self._handle_nuke_action(guild, actor_id, "role_delete", f"Deleted @{role.name}", threshold)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel) -> None:
        """Trigger anti-nuke threshold and auto-deletion on unauthorized webhook creation."""
        guild = channel.guild
        if not hasattr(self.bot, "security_repo"):
            return
        settings = await self.bot.security_repo.get_or_create_settings(guild.id)
        if not settings.get("enabled") or not settings.get("anti_webhook"):
            return
        actor_id = guild.owner_id
        webhook_target = None
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_create):
                actor_id = entry.user.id
                webhook_target = entry.target
                break
        except Exception:
            pass
        await self._handle_nuke_action(guild, actor_id, "webhook_create", f"Created webhook in #{channel.name}", 1)
        # Delete unauthorized webhook if created by non-whitelisted user
        if webhook_target and hasattr(webhook_target, "delete"):
            whitelist_raw = settings.get("whitelist_users", "[]")
            roles_raw = settings.get("whitelist_roles", "[]")
            member = guild.get_member(actor_id)
            if not self._is_whitelisted(actor_id, guild, whitelist_raw, roles_raw, member=member):
                try:
                    await webhook_target.delete(reason="Death Bot: Unauthorized webhook creation deleted")
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        if not hasattr(self.bot, "security_repo"):
            return
        settings = await self.bot.security_repo.get_or_create_settings(guild.id)
        if not settings.get("enabled"):
            return

        whitelist_raw = settings.get("whitelist_users", "[]")
        roles_raw = settings.get("whitelist_roles", "[]")

        event_punishments = settings.get("event_punishments") or {}
        if isinstance(event_punishments, str):
            try:
                event_punishments = json.loads(event_punishments)
            except Exception:
                event_punishments = {}

        # Account age check
        if settings.get("anti_raid") or settings.get("anti_bot"):
            age_threshold_hours = settings.get("account_age_threshold_hours", 24)
            account_age = datetime.now(timezone.utc) - member.created_at
            if account_age < timedelta(hours=age_threshold_hours):
                if not self._is_whitelisted(member.id, guild, whitelist_raw, roles_raw, member=member):
                    punishment = event_punishments.get("account_age") or "not_configured"
                    await self._apply_punishment(guild, member, punishment, "Account too new")
                    await self.bot.security_repo.log_incident(
                        guild.id,
                        member.id,
                        "new_account",
                        f"Account age {account_age} < {age_threshold_hours}h",
                        punishment,
                    )
                    return

        # Anti-bot check
        if settings.get("anti_bot") and member.bot:
            if not self._is_whitelisted(member.id, guild, whitelist_raw, roles_raw, member=member):
                try:
                    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
                        adder_id = entry.user.id
                        await self._handle_nuke_action(guild, adder_id, "bot_add", f"Added bot {member}", 1)
                        break
                except Exception:
                    pass

        # Anti-raid: join rate tracking
        if settings.get("anti_raid"):
            join_rate_max = settings.get("join_rate_max", 5)
            join_rate_window = settings.get("join_rate_seconds", 10)
            self._action_log[guild.id].append((member.id, "join", datetime.now(timezone.utc)))
            self._prune_window(guild.id, join_rate_window)
            join_count = sum(1 for e in self._action_log[guild.id] if e[1] == "join")
            if join_count >= join_rate_max:
                if self._is_whitelisted(member.id, guild, whitelist_raw, roles_raw, member=member):
                    return
                punishment = event_punishments.get("anti_raid") or "not_configured"
                await self.bot.security_repo.log_incident(
                    guild.id,
                    member.id,
                    "raid_detected",
                    f"Join rate {join_count}/{join_rate_max} in {join_rate_window}s",
                    punishment,
                )
                await self._apply_punishment(guild, member, punishment, "Anti-raid join rate exceeded")


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(SecurityService(bot))
