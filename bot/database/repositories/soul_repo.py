"""KROVEX SOUL Conversation Memory Repository.

Provides multi-tenant, guild/channel/user-isolated ephemeral conversation storage
with automated sliding-window history limits, TTL expiration, and privacy deletion.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional

from bot.database.models import SoulGuildSettingsModel, SoulMessageModel, SoulSessionModel
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.utils.logger import get_logger

logger = get_logger("death_bot.database.soul_repo")


class SoulRepository:
    """Repository handling KROVEX SOUL sessions, history, and settings."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    @staticmethod
    def generate_session_id(guild_id: int, channel_id: int, user_id: int) -> str:
        """Construct deterministic session identifier for multi-tenant isolation."""
        return f"{guild_id}:{channel_id}:{user_id}"

    async def get_or_create_session(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
    ) -> SoulSessionModel:
        """Retrieve existing conversation session or initialize a new one."""
        session_id = self.generate_session_id(guild_id, channel_id, user_id)

        row = await self.db.fetchone(
            "SELECT * FROM soul_sessions WHERE session_id = ?",
            (session_id,),
        )
        if row:
            return SoulSessionModel.from_row(row)

        await self.db.execute(
            """
            INSERT INTO soul_sessions (session_id, guild_id, channel_id, user_id, last_activity_at, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id) DO UPDATE SET last_activity_at = CURRENT_TIMESTAMP
            """,
            (session_id, guild_id, channel_id, user_id),
        )

        created_row = await self.db.fetchone(
            "SELECT * FROM soul_sessions WHERE session_id = ?",
            (session_id,),
        )
        if not created_row:
            raise RuntimeError(f"Failed to create soul session {session_id}")
        return SoulSessionModel.from_row(created_row)

    async def touch_session(self, session_id: str) -> None:
        """Update last_activity_at timestamp to current UTC time."""
        await self.db.execute(
            "UPDATE soul_sessions SET last_activity_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (session_id,),
        )

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> SoulMessageModel:
        """Append a conversational turn (user or model) to session history."""
        if role not in ("user", "model", "system"):
            raise ValueError(f"Invalid message role '{role}'. Must be user, model, or system.")

        cursor = await self.db.execute(
            """
            INSERT INTO soul_messages (session_id, role, content, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (session_id, role, content),
        )
        await self.touch_session(session_id)

        msg_id = cursor.lastrowid
        row = await self.db.fetchone(
            "SELECT * FROM soul_messages WHERE id = ?",
            (msg_id,),
        )
        if not row:
            return SoulMessageModel(id=msg_id, session_id=session_id, role=role, content=content)
        return SoulMessageModel.from_row(row)

    async def delete_message(self, message_id: int) -> bool:
        """Delete a single specific message turn by its primary key ID."""
        cursor = await self.db.execute(
            "DELETE FROM soul_messages WHERE id = ?",
            (message_id,),
        )
        return cursor.rowcount > 0

    async def get_recent_messages(
        self,
        session_id: str,
        limit: int = 10,
    ) -> List[SoulMessageModel]:
        """Fetch the most recent N conversational messages in chronological order."""
        rows = await self.db.fetchall(
            """
            SELECT * FROM (
                SELECT * FROM soul_messages
                WHERE session_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
            ) ORDER BY created_at ASC, id ASC
            """,
            (session_id, limit),
        )
        return [SoulMessageModel.from_row(r) for r in rows]

    async def prune_session_history(
        self,
        session_id: str,
        keep_latest: int = 10,
    ) -> int:
        """Enforce sliding window by deleting turns exceeding keep_latest."""
        cursor = await self.db.execute(
            """
            DELETE FROM soul_messages
            WHERE session_id = ?
              AND id NOT IN (
                  SELECT id FROM soul_messages
                  WHERE session_id = ?
                  ORDER BY created_at DESC, id DESC
                  LIMIT ?
              )
            """,
            (session_id, session_id, keep_latest),
        )
        return cursor.rowcount

    async def clear_session_messages(self, session_id: str) -> int:
        """Purge all conversation turns for a session while retaining session metadata."""
        cursor = await self.db.execute(
            "DELETE FROM soul_messages WHERE session_id = ?",
            (session_id,),
        )
        await self.touch_session(session_id)
        return cursor.rowcount

    async def is_session_expired(
        self,
        session: SoulSessionModel,
        timeout_minutes: int = 30,
    ) -> bool:
        """Check if session inactivity exceeds timeout_minutes."""
        row = await self.db.fetchone(
            """
            SELECT (strftime('%s', 'now') - strftime('%s', last_activity_at)) > (? * 60) AS is_expired
            FROM soul_sessions
            WHERE session_id = ?
            """,
            (timeout_minutes, session.session_id),
        )
        if not row:
            return True
        return bool(row["is_expired"])

    async def delete_user_session(
        self,
        guild_id: int,
        user_id: int,
        channel_id: Optional[int] = None,
    ) -> int:
        """Delete conversation sessions and cascade messages for a user (Privacy Wipe)."""
        if channel_id:
            session_id = self.generate_session_id(guild_id, channel_id, user_id)
            cursor = await self.db.execute(
                "DELETE FROM soul_sessions WHERE session_id = ?",
                (session_id,),
            )
        else:
            cursor = await self.db.execute(
                "DELETE FROM soul_sessions WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
        return cursor.rowcount

    async def delete_guild_sessions(self, guild_id: int) -> int:
        """Delete all conversation sessions and messages for an entire guild (Admin Reset)."""
        cursor = await self.db.execute(
            "DELETE FROM soul_sessions WHERE guild_id = ?",
            (guild_id,),
        )
        return cursor.rowcount

    async def purge_expired_sessions(self, max_age_hours: int = 24) -> int:
        """Purge inactive sessions older than max_age_hours."""
        cursor = await self.db.execute(
            """
            DELETE FROM soul_sessions
            WHERE strftime('%s', 'now') - strftime('%s', last_activity_at) > (? * 3600)
            """,
            (max_age_hours,),
        )
        return cursor.rowcount

    async def get_guild_settings(self, guild_id: int) -> SoulGuildSettingsModel:
        """Retrieve guild AI configuration or insert default settings."""
        row = await self.db.fetchone(
            "SELECT * FROM soul_guild_settings WHERE guild_id = ?",
            (guild_id,),
        )
        if row:
            return SoulGuildSettingsModel.from_row(row)

        await self.db.execute(
            """
            INSERT INTO soul_guild_settings (
                guild_id, enabled, allowed_channels, personality_style,
                cooldown_seconds, max_history_turns, daily_quota_limit, updated_at
            ) VALUES (?, 1, '[]', 'tanglish_bro', 3.0, 10, 500, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id) DO NOTHING
            """,
            (guild_id,),
        )
        created = await self.db.fetchone(
            "SELECT * FROM soul_guild_settings WHERE guild_id = ?",
            (guild_id,),
        )
        if not created:
            return SoulGuildSettingsModel(guild_id=guild_id)
        return SoulGuildSettingsModel.from_row(created)

    async def update_guild_settings(
        self,
        guild_id: int,
        **kwargs: Any,
    ) -> SoulGuildSettingsModel:
        """Update configurable fields for a guild's AI settings."""
        allowed_fields = {
            "enabled",
            "allowed_channels",
            "personality_style",
            "cooldown_seconds",
            "max_history_turns",
            "daily_quota_limit",
        }

        updates: List[str] = []
        params: List[Any] = []

        for key, value in kwargs.items():
            if key in allowed_fields:
                updates.append(f"{key} = ?")
                if key == "allowed_channels":
                    params.append(json.dumps(value or []))
                elif key == "enabled":
                    params.append(1 if value else 0)
                else:
                    params.append(value)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(guild_id)
            sql = f"UPDATE soul_guild_settings SET {', '.join(updates)} WHERE guild_id = ?"
            await self.db.execute(sql, tuple(params))

        return await self.get_guild_settings(guild_id)
