"""Command usage analytics repository."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorCollection

from bot.database.models import CommandUsage
from bot.database.repositories.base import BaseRepository


class CommandUsageRepository(BaseRepository):
    """Repository handling telemetry on command invocations."""

    async def log_usage(self, usage: CommandUsage) -> None:
        """Record a single command execution event."""
        await self.insert_one(usage.to_dict())

    async def get_top_commands(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get the most frequently used commands across all guilds."""
        pipeline = [
            {"$group": {"_id": "$command_name", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": limit},
        ]
        cursor = self.collection.aggregate(pipeline)
        return await cursor.to_list(length=limit)

