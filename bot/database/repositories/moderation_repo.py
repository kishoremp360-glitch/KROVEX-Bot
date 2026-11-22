"""Moderation audit logging repository."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorCollection

from bot.database.models import ModerationLog
from bot.database.repositories.base import BaseRepository


class ModerationRepository(BaseRepository):
    """Repository handling moderation cases, warnings, and audit logs."""

    async def get_next_case_id(self, guild_id: int) -> int:
        """Get the incremental case ID for a guild."""
        last_case = await self.collection.find_one(
            {"guild_id": guild_id},
            sort=[("case_id", -1)],
        )
        return (last_case["case_id"] + 1) if last_case else 1

    async def add_case(self, case: ModerationLog) -> int:
        """Insert a new moderation case and return the case ID."""
        if case.case_id <= 0:
            case.case_id = await self.get_next_case_id(case.guild_id)
        await self.insert_one(case.to_dict())
        return case.case_id

    async def get_user_cases(self, guild_id: int, user_id: int) -> List[ModerationLog]:
        """Fetch all infractions recorded against a user in a guild."""
        docs = await self.find_many(
            {"guild_id": guild_id, "user_id": user_id},
            sort_field="case_id",
            sort_direction=-1,
        )
        return [
            ModerationLog(
                guild_id=int(d["guild_id"]),
                case_id=int(d["case_id"]),
                user_id=int(d["user_id"]),
                moderator_id=int(d["moderator_id"]),
                action=str(d["action"]),
                reason=str(d.get("reason", "No reason provided")),
                timestamp=d.get("timestamp"),
            )
            for d in docs
        ]

