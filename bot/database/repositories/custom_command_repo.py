"""Custom Command Repository for SQLite storage.

Provides atomic, parameterized CRUD operations for guild-scoped custom commands
and command aliases with foreign key cascading and usage tracking.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bot.database.models import CustomCommandAliasModel, CustomCommandModel
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.utils.logger import get_logger

logger = get_logger("death_bot.database.custom_command_repo")


class CustomCommandRepository:
    """Repository handling custom commands and aliases in SQLite."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

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
    ) -> CustomCommandModel:
        """Create a new guild custom command."""
        normalized_name = name.strip().lower()
        embed_json = json.dumps(embed_data) if embed_data else None
        roles_json = json.dumps(required_role_ids or [])

        sql = """
            INSERT INTO custom_commands (
                guild_id, name, response_type, content, embed_data,
                permission_level, required_role_ids, cooldown_seconds,
                is_enabled, creator_id, uses, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
        await self.db.execute(
            sql,
            (
                guild_id,
                normalized_name,
                response_type,
                content,
                embed_json,
                permission_level,
                roles_json,
                cooldown_seconds,
                1 if is_enabled else 0,
                creator_id,
            ),
        )

        created = await self.get_command(guild_id, normalized_name, resolve_alias=False)
        if not created:
            raise RuntimeError(f"Failed to create custom command '{normalized_name}' for guild {guild_id}")
        return created

    async def get_command(
        self,
        guild_id: int,
        name: str,
        resolve_alias: bool = True,
    ) -> Optional[CustomCommandModel]:
        """Fetch a custom command by name or alias."""
        normalized_name = name.strip().lower()

        # 1. Direct command lookup
        row = await self.db.fetchone(
            "SELECT * FROM custom_commands WHERE guild_id = ? AND name = ?",
            (guild_id, normalized_name),
        )
        if row:
            return CustomCommandModel.from_row(row)

        # 2. Resolve alias if requested
        if resolve_alias:
            alias_row = await self.db.fetchone(
                "SELECT target_command FROM custom_command_aliases WHERE guild_id = ? AND alias = ?",
                (guild_id, normalized_name),
            )
            if alias_row:
                target = alias_row["target_command"]
                target_row = await self.db.fetchone(
                    "SELECT * FROM custom_commands WHERE guild_id = ? AND name = ?",
                    (guild_id, target),
                )
                if target_row:
                    return CustomCommandModel.from_row(target_row)

        return None

    async def list_commands(
        self,
        guild_id: int,
        enabled_only: bool = False,
    ) -> List[CustomCommandModel]:
        """List all custom commands for a guild."""
        if enabled_only:
            rows = await self.db.fetchall(
                "SELECT * FROM custom_commands WHERE guild_id = ? AND is_enabled = 1 ORDER BY name ASC",
                (guild_id,),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM custom_commands WHERE guild_id = ? ORDER BY name ASC",
                (guild_id,),
            )
        return [CustomCommandModel.from_row(r) for r in rows]

    async def update_command(
        self,
        guild_id: int,
        name: str,
        **kwargs: Any,
    ) -> Optional[CustomCommandModel]:
        """Update fields on an existing custom command."""
        normalized_name = name.strip().lower()
        existing = await self.get_command(guild_id, normalized_name, resolve_alias=False)
        if not existing:
            return None

        allowed_fields = {
            "response_type",
            "content",
            "embed_data",
            "permission_level",
            "required_role_ids",
            "cooldown_seconds",
            "is_enabled",
        }

        updates: List[str] = []
        params: List[Any] = []

        for key, value in kwargs.items():
            if key in allowed_fields:
                updates.append(f"{key} = ?")
                if key == "embed_data":
                    params.append(json.dumps(value) if value else None)
                elif key == "required_role_ids":
                    params.append(json.dumps(value or []))
                elif key == "is_enabled":
                    params.append(1 if value else 0)
                else:
                    params.append(value)

        if not updates:
            return existing

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.extend([guild_id, normalized_name])

        sql = f"UPDATE custom_commands SET {', '.join(updates)} WHERE guild_id = ? AND name = ?"
        await self.db.execute(sql, tuple(params))
        return await self.get_command(guild_id, normalized_name, resolve_alias=False)

    async def delete_command(self, guild_id: int, name: str) -> bool:
        """Delete a custom command and all its associated aliases via foreign keys."""
        normalized_name = name.strip().lower()
        cursor = await self.db.execute(
            "DELETE FROM custom_commands WHERE guild_id = ? AND name = ?",
            (guild_id, normalized_name),
        )
        return cursor.rowcount > 0

    async def create_alias(
        self,
        guild_id: int,
        alias: str,
        target_command: str,
    ) -> bool:
        """Create an alias pointing to a target custom command."""
        norm_alias = alias.strip().lower()
        norm_target = target_command.strip().lower()

        # Target command must exist
        target = await self.get_command(guild_id, norm_target, resolve_alias=False)
        if not target:
            return False

        sql = """
            INSERT INTO custom_command_aliases (guild_id, alias, target_command, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """
        try:
            await self.db.execute(sql, (guild_id, norm_alias, norm_target))
            return True
        except Exception as err:
            logger.warning("Failed to create alias '%s' for target '%s': %s", norm_alias, norm_target, err)
            return False

    async def delete_alias(self, guild_id: int, alias: str) -> bool:
        """Delete a single custom command alias."""
        norm_alias = alias.strip().lower()
        cursor = await self.db.execute(
            "DELETE FROM custom_command_aliases WHERE guild_id = ? AND alias = ?",
            (guild_id, norm_alias),
        )
        return cursor.rowcount > 0

    async def get_alias(self, guild_id: int, alias: str) -> Optional[CustomCommandAliasModel]:
        """Fetch alias details by alias name."""
        norm_alias = alias.strip().lower()
        row = await self.db.fetchone(
            "SELECT * FROM custom_command_aliases WHERE guild_id = ? AND alias = ?",
            (guild_id, norm_alias),
        )
        if row:
            return CustomCommandAliasModel.from_row(row)
        return None

    async def list_aliases(
        self,
        guild_id: int,
        target_command: Optional[str] = None,
    ) -> List[CustomCommandAliasModel]:
        """List all aliases for a guild, optionally filtered by target command."""
        if target_command:
            norm_target = target_command.strip().lower()
            rows = await self.db.fetchall(
                "SELECT * FROM custom_command_aliases WHERE guild_id = ? AND target_command = ? ORDER BY alias ASC",
                (guild_id, norm_target),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM custom_command_aliases WHERE guild_id = ? ORDER BY alias ASC",
                (guild_id,),
            )
        return [CustomCommandAliasModel.from_row(r) for r in rows]

    async def increment_uses(self, guild_id: int, name: str) -> bool:
        """Atomically increment the usage counter and update last_used_at."""
        norm_name = name.strip().lower()
        sql = """
            UPDATE custom_commands
            SET uses = uses + 1, last_used_at = CURRENT_TIMESTAMP
            WHERE guild_id = ? AND name = ?
        """
        cursor = await self.db.execute(sql, (guild_id, norm_name))
        return cursor.rowcount > 0
