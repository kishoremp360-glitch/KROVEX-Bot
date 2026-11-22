"""Custom Command Service layer for Death Bot.

Orchestrates custom command and alias lifecycle, permission evaluation,
cooldown enforcement, template rendering, and telemetry accounting.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

import discord

from bot.database.models import CustomCommandAliasModel, CustomCommandModel
from bot.database.repositories.custom_command_repo import CustomCommandRepository
from bot.utils.custom_commands import (
    ALLOWED_TEMPLATE_VARS,
    normalize_command_name,
    render_safe_template,
    validate_command_collision,
    validate_command_name_format,
    validate_template_variables,
)
from bot.utils.logger import get_logger

logger = get_logger("death_bot.services.custom_command")


class CustomCommandService:
    """Core domain service for custom commands."""

    def __init__(self, repo: CustomCommandRepository, bot: Optional[Any] = None) -> None:
        self.repo = repo
        self.bot = bot
        # Sliding-window cooldown tracking: (guild_id, command_name, user_id) -> expiry_monotonic
        self._cooldowns: Dict[Tuple[int, str, int], float] = {}

    async def validate_command(
        self,
        guild_id: int,
        name: str,
        content: Optional[str] = None,
        embed_data: Optional[Dict[str, Any]] = None,
        cooldown_seconds: int = 0,
        permission_level: str = "everyone",
        is_alias: bool = False,
        existing_command_name: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Validate command name format, collisions, permissions, cooldown, and content."""
        # 1. Format validation
        valid_format, format_err = validate_command_name_format(name)
        if not valid_format:
            return False, format_err

        # 2. Collision validation
        valid_collision, collision_err = await validate_command_collision(
            name=name,
            guild_id=guild_id,
            bot=self.bot,
            repo=self.repo,
            is_alias=is_alias,
            existing_command_name=existing_command_name,
        )
        if not valid_collision:
            return False, collision_err

        if is_alias:
            return True, ""

        # 3. Content or Embed validation
        has_content = bool(content and content.strip())
        has_embed = bool(embed_data)
        if not has_content and not has_embed:
            return False, "Custom command must provide either text content or embed data."

        # 4. Template validation on text content
        if has_content and content:
            valid_template, template_err = validate_template_variables(content)
            if not valid_template:
                return False, template_err

        # 5. Template validation on embed fields
        if has_embed and embed_data:
            embed_texts = [
                embed_data.get("title", ""),
                embed_data.get("description", ""),
                embed_data.get("footer_text", ""),
            ]
            for field in embed_data.get("fields", []):
                embed_texts.append(field.get("name", ""))
                embed_texts.append(field.get("value", ""))

            for txt in embed_texts:
                if txt:
                    valid_t, err_t = validate_template_variables(txt)
                    if not valid_t:
                        return False, err_t

        # 6. Cooldown range validation (0 - 3600 seconds)
        if not (0 <= cooldown_seconds <= 3600):
            return False, "Cooldown must be between 0 and 3600 seconds (1 hour)."

        # 7. Permission level validation
        if permission_level not in {"everyone", "moderator", "administrator"}:
            return False, f"Invalid permission level '{permission_level}'. Allowed: everyone, moderator, administrator."

        return True, ""

    async def create_command(
        self,
        guild_id: int,
        name: str,
        response_type: str = "text",
        content: Optional[str] = None,
        embed_data: Optional[Dict[str, Any]] = None,
        permission_level: str = "everyone",
        required_role_ids: Optional[List[int]] = None,
        cooldown_seconds: int = 0,
        is_enabled: bool = True,
        creator_id: int = 0,
    ) -> Tuple[Optional[CustomCommandModel], Optional[str]]:
        """Validate and create a new custom command."""
        valid, error_msg = await self.validate_command(
            guild_id=guild_id,
            name=name,
            content=content,
            embed_data=embed_data,
            cooldown_seconds=cooldown_seconds,
            permission_level=permission_level,
            is_alias=False,
        )
        if not valid:
            return None, error_msg

        cmd = await self.repo.create_command(
            guild_id=guild_id,
            name=name,
            response_type=response_type,
            content=content,
            embed_data=embed_data,
            permission_level=permission_level,
            required_role_ids=required_role_ids,
            cooldown_seconds=cooldown_seconds,
            is_enabled=is_enabled,
            creator_id=creator_id,
        )
        return cmd, None

    async def edit_command(
        self,
        guild_id: int,
        name: str,
        **kwargs: Any,
    ) -> Tuple[Optional[CustomCommandModel], Optional[str]]:
        """Edit an existing custom command."""
        existing = await self.repo.get_command(guild_id, name, resolve_alias=False)
        if not existing:
            return None, f"Custom command '{name}' was not found in this server."

        # Merge existing with updates for validation
        new_content = kwargs.get("content", existing.content)
        new_embed = kwargs.get("embed_data", existing.embed_data)
        new_cooldown = kwargs.get("cooldown_seconds", existing.cooldown_seconds)
        new_perm = kwargs.get("permission_level", existing.permission_level)

        valid, error_msg = await self.validate_command(
            guild_id=guild_id,
            name=name,
            content=new_content,
            embed_data=new_embed,
            cooldown_seconds=new_cooldown,
            permission_level=new_perm,
            is_alias=False,
            existing_command_name=existing.name,
        )
        if not valid:
            return None, error_msg

        updated = await self.repo.update_command(guild_id, name, **kwargs)
        return updated, None

    async def delete_command(self, guild_id: int, name: str) -> bool:
        """Delete a custom command and purge any in-memory cooldown state."""
        norm_name = normalize_command_name(name)
        deleted = await self.repo.delete_command(guild_id, norm_name)
        if deleted:
            # Clean up active cooldowns for this command
            to_remove = [k for k in self._cooldowns if k[0] == guild_id and k[1] == norm_name]
            for k in to_remove:
                self._cooldowns.pop(k, None)
        return deleted

    async def get_command(
        self,
        guild_id: int,
        name: str,
        resolve_alias: bool = True,
    ) -> Optional[CustomCommandModel]:
        """Retrieve a command by name or alias."""
        return await self.repo.get_command(guild_id, name, resolve_alias=resolve_alias)

    async def list_commands(
        self,
        guild_id: int,
        enabled_only: bool = False,
    ) -> List[CustomCommandModel]:
        """List all custom commands for a guild."""
        return await self.repo.list_commands(guild_id, enabled_only=enabled_only)

    async def create_alias(
        self,
        guild_id: int,
        alias: str,
        target_command: str,
    ) -> Tuple[bool, Optional[str]]:
        """Validate and create a command alias."""
        norm_target = normalize_command_name(target_command)
        target = await self.repo.get_command(guild_id, norm_target, resolve_alias=False)
        if not target:
            return False, f"Target custom command '{norm_target}' does not exist in this server."

        valid, error_msg = await self.validate_command(
            guild_id=guild_id,
            name=alias,
            is_alias=True,
        )
        if not valid:
            return False, error_msg

        success = await self.repo.create_alias(guild_id, alias, norm_target)
        if not success:
            return False, f"Failed to create alias '{alias}'."
        return True, None

    async def delete_alias(self, guild_id: int, alias: str) -> bool:
        """Delete a command alias."""
        return await self.repo.delete_alias(guild_id, alias)

    def render_template(
        self,
        template: str,
        context: Dict[str, Any],
    ) -> Tuple[str, Optional[str]]:
        """Render safe template string with allowlist placeholders."""
        return render_safe_template(template, context)

    def check_permission(
        self,
        member: Any,
        command: CustomCommandModel,
        mod_role_ids: Optional[List[int]] = None,
    ) -> Tuple[bool, str]:
        """Evaluate member permissions against command requirements."""
        if not command.is_enabled:
            return False, f"Custom command '{command.name}' is currently disabled in this server."

        # Server administrators or guild owners always pass
        guild = getattr(member, "guild", None)
        owner_id = getattr(guild, "owner_id", None)
        member_id = getattr(member, "id", None)
        if owner_id is not None and member_id is not None and owner_id == member_id:
            return True, ""

        guild_perms = getattr(member, "guild_permissions", None)
        if guild_perms and getattr(guild_perms, "administrator", False):
            return True, ""

        level = command.permission_level.lower()

        # Administrator level check
        if level == "administrator":
            return False, "This command requires Administrator permissions."

        # Moderator level check
        if level == "moderator":
            is_mod = False
            if guild_perms:
                is_mod = (
                    getattr(guild_perms, "manage_messages", False)
                    or getattr(guild_perms, "kick_members", False)
                    or getattr(guild_perms, "ban_members", False)
                    or getattr(guild_perms, "manage_guild", False)
                )

            # Check mod role IDs
            member_role_ids = {r.id for r in getattr(member, "roles", [])}
            if mod_role_ids and any(r_id in member_role_ids for r_id in mod_role_ids):
                is_mod = True

            if not is_mod:
                return False, "This command requires Moderator permissions."

        # Required role IDs check (applies across levels if configured)
        if command.required_role_ids:
            member_role_ids = {r.id for r in getattr(member, "roles", [])}
            has_role = any(r_id in member_role_ids for r_id in command.required_role_ids)
            if not has_role:
                return False, "You do not have the required role to use this command."

        return True, ""

    def check_cooldown(
        self,
        guild_id: int,
        command_name: str,
        user_id: int,
        cooldown_seconds: int,
    ) -> Tuple[bool, float]:
        """Check if command is on cooldown for this user. Returns (can_run, retry_after)."""
        if cooldown_seconds <= 0:
            return True, 0.0

        norm_name = normalize_command_name(command_name)
        key = (guild_id, norm_name, user_id)
        now = time.monotonic()
        expiry = self._cooldowns.get(key, 0.0)

        if now < expiry:
            retry_after = round(expiry - now, 1)
            return False, max(retry_after, 0.1)

        return True, 0.0

    def apply_cooldown(
        self,
        guild_id: int,
        command_name: str,
        user_id: int,
        cooldown_seconds: int,
    ) -> None:
        """Apply active cooldown timestamp for user."""
        if cooldown_seconds > 0:
            norm_name = normalize_command_name(command_name)
            key = (guild_id, norm_name, user_id)
            self._cooldowns[key] = time.monotonic() + cooldown_seconds

    async def record_usage(self, guild_id: int, name: str) -> bool:
        """Atomically record command execution usage."""
        norm_name = normalize_command_name(name)
        return await self.repo.increment_uses(guild_id, norm_name)

    @staticmethod
    def get_safe_allowed_mentions() -> discord.AllowedMentions:
        """Return restrictive AllowedMentions policy to prevent mass-ping abuse."""
        return discord.AllowedMentions.none()
