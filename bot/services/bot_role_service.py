"""KROVEX Automatic Bot Dedicated Role Management Service.

Provisions and maintains KROVEX's dedicated security, protection, enforcement,
and optimization roles across Discord guilds. Ensures roles match branding,
have appropriate granular permissions without Administrator, and prevents duplicates.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.services.bot_roles")

# Dedicated Bot Role Specifications in exact creation order
KROVEX_ROLE_SPECS: List[Dict[str, Any]] = [
    {
        "name": "KROVEX",
        "color": discord.Color(0xB0B3B8),  # Silver Gray (#B0B3B8)
        "permissions": discord.Permissions(administrator=True),
        "hoist": True,
        "reason": "KROVEX Core Administrative Authority",
    },
    {
        "name": "KROVEX Prime Security™",
        "color": discord.Color(0xF4A6C0),  # Sakura Pink (#F4A6C0)
        "permissions": discord.Permissions(administrator=True),
        "hoist": True,
        "reason": "KROVEX Prime Security Architecture",
    },
    {
        "name": "KROVEX Unbypassable Security™",
        "color": discord.Color(0xF4A6C0),  # Sakura Pink (#F4A6C0)
        "permissions": discord.Permissions(administrator=True),
        "hoist": True,
        "reason": "KROVEX Unbypassable High-Hierarchy Barrier",
    },
]

# Legacy / alternate role name migration mapping
LEGACY_ROLE_MAPPING: Dict[str, str] = {
    "zynrax": "KROVEX",
    "zynrax prime security™": "KROVEX Prime Security™",
    "zynrax unbypassable security™": "KROVEX Unbypassable Security™",
    ". krovexsecured": "KROVEX",
    ". krovexunbypassable": "KROVEX Unbypassable Security™",
    ". krovexprotected": "KROVEX Prime Security™",
    ". krovex optimiser": "KROVEX",
}


class BotRoleService(commands.Cog, name="Bot Role Management"):
    """Service managing the creation, assignment, and persistence of KROVEX dedicated roles."""

    def __init__(self, bot: "DeathBot") -> None:
        self.bot = bot
        self._guild_locks: Dict[int, asyncio.Lock] = {}
        self._pruning_role_ids: Set[int] = set()

    def _get_guild_lock(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self._guild_locks:
            self._guild_locks[guild_id] = asyncio.Lock()
        return self._guild_locks[guild_id]

    async def setup_bot_roles(
        self,
        guild: discord.Guild,
    ) -> Tuple[List[discord.Role], List[str], Optional[str]]:
        """Provision or synchronize KROVEX dedicated roles in the guild with concurrency protection."""
        lock = self._get_guild_lock(guild.id)
        async with lock:
            return await self._setup_bot_roles_internal(guild)

    async def _setup_bot_roles_internal(
        self,
        guild: discord.Guild,
    ) -> Tuple[List[discord.Role], List[str], Optional[str]]:
        """Internal implementation of KROVEX dedicated roles provisioning."""
        me = guild.me
        if not me:
            return [], [], "Bot member instance not found in guild."

        # Check Manage Roles permission
        if not me.guild_permissions.manage_roles:
            logger.warning(
                "Cannot provision KROVEX bot roles in '%s' (ID: %s): Missing Manage Roles permission.",
                guild.name,
                guild.id,
            )
            return (
                [],
                [spec["name"] for spec in KROVEX_ROLE_SPECS],
                "Missing 'Manage Roles' permission to create or assign dedicated roles.",
            )

        active_roles: List[discord.Role] = []
        failed_roles: List[str] = []

        for spec in KROVEX_ROLE_SPECS:
            role_name = spec["name"]
            # 1. Find all matching custom roles (ignoring managed integration roles)
            all_matching = [
                r for r in guild.roles
                if r.name.lower() == role_name.lower() and getattr(r, "managed", False) is not True
            ]
            if len(all_matching) > 1:
                # Deduplicate: Keep highest positioned role (or oldest ID), prune extra duplicates
                all_matching.sort(key=lambda r: (getattr(r, "position", 0), -getattr(r, "id", 0)), reverse=True)
                existing_role = all_matching[0]
                for extra in all_matching[1:]:
                    self._pruning_role_ids.add(extra.id)
                    try:
                        # If bot currently has the extra role, remove it first
                        if me and extra in getattr(me, "roles", []):
                            try:
                                await me.remove_roles(extra, reason="Pruning duplicate KROVEX dedicated role from bot")
                            except Exception:
                                pass
                        top_pos = getattr(getattr(me, "top_role", None), "position", 0)
                        extra_pos = getattr(extra, "position", 0)
                        if top_pos > extra_pos:
                            await extra.delete(reason="Pruning duplicate KROVEX dedicated role")
                            logger.info("Pruned duplicate role '%s' (ID: %s) in '%s'.", extra.name, extra.id, guild.name)
                        else:
                            self._pruning_role_ids.discard(extra.id)
                            logger.warning(
                                "Cannot delete duplicate role '%s' (ID: %s) in '%s': Position %d >= bot top role %d.",
                                extra.name, extra.id, guild.name, extra_pos, top_pos
                            )
                    except Exception as del_err:
                        self._pruning_role_ids.discard(extra.id)
                        logger.debug("Could not prune duplicate role %s: %s", getattr(extra, "id", None), del_err)
            elif len(all_matching) == 1:
                existing_role = all_matching[0]
            else:
                existing_role = None

            if existing_role is None:
                for old_name, target_name in LEGACY_ROLE_MAPPING.items():
                    if target_name.lower() == role_name.lower():
                        legacy = discord.utils.find(
                            lambda r: r.name.lower() == old_name and getattr(r, "managed", False) is not True,
                            guild.roles,
                        )
                        if legacy:
                            # Verify role hierarchy before attempting edit
                            top_pos = getattr(getattr(me, "top_role", None), "position", 0)
                            legacy_pos = getattr(legacy, "position", 0)
                            if legacy_pos >= top_pos:
                                logger.warning(
                                    "Cannot migrate legacy role '%s' (pos %d) in '%s': Position is higher than or equal to bot top role (pos %d). Drag KROVEX role above it in Server Settings -> Roles.",
                                    legacy.name,
                                    legacy_pos,
                                    guild.name,
                                    top_pos,
                                )
                                continue

                            try:
                                await legacy.edit(
                                    name=role_name,
                                    color=spec["color"],
                                    permissions=spec["permissions"],
                                    hoist=spec.get("hoist", True),
                                    reason="Migrating legacy security role to official KROVEX role specification",
                                )
                                existing_role = legacy
                                logger.info("Migrated legacy role to '%s'.", role_name)
                                break
                            except (discord.Forbidden, discord.HTTPException) as mig_err:
                                logger.warning(
                                    "Could not rename legacy role '%s' with admin permissions (%s). Attempting rename without permission escalation...",
                                    legacy.name,
                                    mig_err,
                                )
                                try:
                                    await legacy.edit(
                                        name=role_name,
                                        color=spec["color"],
                                        hoist=spec.get("hoist", True),
                                        reason="Migrating legacy security role name and appearance",
                                    )
                                    existing_role = legacy
                                    logger.info("Migrated legacy role name to '%s' (appearance-only fallback).", role_name)
                                    break
                                except Exception as fallback_err:
                                    logger.warning("Could not rename legacy role '%s': %s", legacy.name, fallback_err)

            if existing_role is not None:
                logger.info("Found pre-existing KROVEX role '%s' in guild '%s'. Reusing.", role_name, guild.name)
                role = existing_role
                edit_kwargs = {}
                if not role.permissions.administrator:
                    edit_kwargs["permissions"] = spec["permissions"]
                if role.color != spec["color"]:
                    edit_kwargs["color"] = spec["color"]
                if not getattr(role, "hoist", False):
                    edit_kwargs["hoist"] = spec.get("hoist", True)
                if edit_kwargs:
                    try:
                        await role.edit(**edit_kwargs, reason="Updating KROVEX role specifications")
                    except Exception as ed_err:
                        logger.debug("Could not edit role %s: %s", role.name, ed_err)
            else:
                # 2. Create the role with exact spec and hoisted to display separately at the top
                try:
                    role = await guild.create_role(
                        name=role_name,
                        color=spec["color"],
                        permissions=spec["permissions"],
                        hoist=spec.get("hoist", True),
                        mentionable=False,
                        reason=spec["reason"],
                    )
                    logger.info("Created KROVEX dedicated hoisted role '%s' in guild '%s'.", role_name, guild.name)
                except (discord.Forbidden, discord.HTTPException) as err:
                    logger.warning("Could not create role '%s' with Administrator; attempting safe granular fallback: %s", role_name, err)
                    try:
                        role = await guild.create_role(
                            name=role_name,
                            color=spec["color"],
                            permissions=discord.Permissions(
                                manage_roles=True,
                                manage_channels=True,
                                kick_members=True,
                                ban_members=True,
                                manage_messages=True,
                                mute_members=True,
                                deafen_members=True,
                                move_members=True,
                                view_audit_log=True,
                                view_channel=True,
                                send_messages=True,
                                embed_links=True,
                                attach_files=True,
                            ),
                            hoist=spec.get("hoist", True),
                            mentionable=False,
                            reason=f"{spec['reason']} (Granular permissions)",
                        )
                        logger.info("Created KROVEX dedicated hoisted role '%s' with granular permissions.", role_name)
                    except Exception as fallback_err:
                        logger.error("Failed to create role '%s' in guild '%s': %s", role_name, guild.name, fallback_err)
                        failed_roles.append(role_name)
                        continue

            # 3. Elevate role position as high as possible at top of server (below bot's top role)
            if hasattr(me, "top_role") and me.top_role is not None and role is not None:
                try:
                    target_pos = max(1, getattr(me.top_role, "position", 1) - 1)
                    curr_pos = getattr(role, "position", 0)
                    if curr_pos < target_pos:
                        await role.edit(position=target_pos, reason="Elevating KROVEX security role to top of server")
                except (discord.Forbidden, discord.HTTPException):
                    pass

            # 4. Assign role to KROVEX bot if not already assigned
            if role not in me.roles:
                try:
                    # Check hierarchy: role must be lower than bot's highest role
                    can_assign = True
                    top_pos = getattr(me.top_role, "position", 0) if hasattr(me, "top_role") and me.top_role is not None else 0
                    role_pos = getattr(role, "position", 0)
                    if hasattr(me, "top_role") and me.top_role is not None:
                        try:
                            can_assign = me.top_role > role
                        except TypeError:
                            can_assign = top_pos > role_pos

                    if can_assign:
                        await me.add_roles(role, reason="Assigning KROVEX dedicated bot role")
                        logger.info("Assigned role '%s' to KROVEX in guild '%s'.", role_name, guild.name)
                    else:
                        logger.info(
                            "Role hierarchy hold in '%s': Role '%s' (pos %d) >= bot top role (pos %d). Drag the bot's managed role above it in Server Settings -> Roles to enable full assignment.",
                            guild.name,
                            role_name,
                            role_pos,
                            top_pos,
                        )
                except (discord.Forbidden, discord.HTTPException) as err:
                    logger.debug("Could not assign role '%s' to KROVEX in '%s': %s", role_name, guild.name, err)

            active_roles.append(role)

        # 5. Position roles at the top of the server hierarchy beneath bot's highest role
        if active_roles and hasattr(me, "top_role") and me.top_role is not None and me.guild_permissions.manage_roles:
            try:
                top_pos = max(1, getattr(me.top_role, "position", 1) - 1)
                pos_map = {}
                for idx, r in enumerate(reversed(active_roles)):
                    pos_map[r] = max(1, top_pos - idx)
                if hasattr(guild, "edit_role_positions") and pos_map:
                    await guild.edit_role_positions(positions=pos_map, reason="Positioning KROVEX dedicated security roles at top of server")
            except Exception as pos_err:
                logger.debug("Could not bulk adjust role positions: %s", pos_err)
                for idx, r in enumerate(reversed(active_roles)):
                    try:
                        target_p = max(1, getattr(me.top_role, "position", 1) - 1 - idx)
                        if getattr(r, "position", 0) != target_p:
                            await r.edit(position=target_p, reason="Positioning KROVEX role at top")
                    except Exception:
                        pass

        return active_roles, failed_roles, None

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Automatically provision dedicated roles when KROVEX joins a server."""
        try:
            await self.setup_bot_roles(guild)
        except Exception as e:
            logger.warning("Auto role setup on_guild_join failed for guild %s: %s", guild.id, e)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Automatically provision dedicated roles when KROVEX itself joins a server."""
        if self.bot.user and member.id == self.bot.user.id:
            try:
                await self.setup_bot_roles(member.guild)
            except Exception as e:
                logger.warning("Auto role setup on_member_join failed for guild %s: %s", member.guild.id, e)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Enforce unremovable protection: instantly restore any KROVEX dedicated roles removed from the bot."""
        if not self.bot.user or after.id != self.bot.user.id:
            return

        # Check if any dedicated role was removed from the bot
        removed_roles = [r for r in before.roles if r not in after.roles]
        if not removed_roles:
            return

        spec_names = {spec["name"].lower() for spec in KROVEX_ROLE_SPECS}
        to_restore = [
            r for r in removed_roles
            if r.name.lower() in spec_names
            and not getattr(r, "managed", False)
            and r.id not in self._pruning_role_ids
        ]

        if to_restore and after.guild.me and after.guild.me.guild_permissions.manage_roles:
            try:
                await after.add_roles(*to_restore, reason="Unremovable KROVEX Security Architecture: Re-applying dedicated role")
                logger.info("Restored unremovable role(s) %s to KROVEX in '%s'.", [r.name for r in to_restore], after.guild.name)
            except Exception as re_err:
                logger.warning("Could not restore removed role to KROVEX: %s", re_err)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        """Automatically complete role assignment when an admin elevates the bot's role hierarchy in Server Settings."""
        guild = after.guild
        me = getattr(guild, "me", None)
        if not me:
            return

        # If a role belonging to the bot had its position elevated
        if after in getattr(me, "roles", []) and after.position > before.position:
            logger.info("Bot role '%s' position elevated to %d in '%s'. Re-checking dedicated roles...", after.name, after.position, guild.name)
            try:
                await self.setup_bot_roles(guild)
            except Exception as e:
                logger.debug("Failed auto-sync on role elevation in %s: %s", guild.id, e)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        """Enforce auto-recreate protection: if a KROVEX dedicated role is deleted, recreate it immediately."""
        if role.id in self._pruning_role_ids:
            self._pruning_role_ids.discard(role.id)
            return

        spec_names = {spec["name"].lower() for spec in KROVEX_ROLE_SPECS}
        if role.name.lower() in spec_names and not getattr(role, "managed", False):
            # Check if another canonical role for this spec already exists in guild
            still_exists = any(
                r.name.lower() == role.name.lower()
                and getattr(r, "managed", False) is not True
                for r in getattr(role.guild, "roles", [])
            )
            if still_exists:
                logger.info("KROVEX dedicated role '%s' deleted, but another instance exists in '%s'. Skipping recreate.", role.name, role.guild.name)
                return

            logger.warning("KROVEX dedicated role '%s' was deleted in guild '%s'. Auto-recreating...", role.name, role.guild.name)
            try:
                await self.setup_bot_roles(role.guild)
            except Exception as rec_err:
                logger.error("Failed to auto-recreate deleted KROVEX role '%s': %s", role.name, rec_err)

    async def _execute_setupbotroles(self, ctx: UnifiedContext, target_guild: Optional[discord.Guild] = None) -> None:
        await ctx.defer(ephemeral=True)
        guild = target_guild or ctx.guild
        if not guild:
            await ctx.send_error("Server Only", "This command can only be used in a server or with a valid guild ID.")
            return

        active_roles, failed_roles, err_msg = await self.setup_bot_roles(guild)
        if err_msg:
            await ctx.send_error("Role Setup Incomplete", err_msg)
            return

        role_lines = "\n".join(f"• {r.mention} (`{r.name}`)" for r in active_roles)
        desc = f"Successfully provisioned/synchronized **{len(active_roles)}** KROVEX dedicated roles in **{guild.name}** (`{guild.id}`):\n\n{role_lines}"
        if failed_roles:
            desc += f"\n\n⚠️ Could not create: {', '.join(failed_roles)}"

        await ctx.send_success("KROVEX Dedicated Roles Ready", desc)

    @commands.command(name="setupbotroles", aliases=["krovexroles", "botroles", "rolesetup"], help="Provision or synchronize KROVEX dedicated server roles.")
    @commands.has_permissions(administrator=True)
    async def setupbotroles_prefix(self, ctx: commands.Context, guild_id: Optional[int] = None) -> None:
        target_g = None
        if guild_id:
            target_g = self.bot.get_guild(guild_id)
        await self._execute_setupbotroles(UnifiedContext.from_prefix(ctx), target_guild=target_g)


async def setup(bot: "DeathBot") -> None:
    """Extension entry point for BotRoleService."""
    bot.bot_role_service = BotRoleService(bot)  # type: ignore
    await bot.add_cog(bot.bot_role_service)
