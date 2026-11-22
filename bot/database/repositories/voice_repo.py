"""Voice status and voice session tracking repository."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from bot.database.models import VoiceSession, VoiceSettings, utc_now
from bot.database.repositories.base import BaseRepository


class VoiceRepository(BaseRepository):
    """Repository handling voice activity settings and session histories."""

    def __init__(self, settings_coll: AsyncIOMotorCollection, sessions_coll: AsyncIOMotorCollection) -> None:
        super().__init__(settings_coll)
        self.sessions_coll = sessions_coll

    async def get_or_create_settings(self, guild_id: int) -> VoiceSettings:
        """Fetch existing settings or initialize defaults with race protection."""
        doc = await self.find_one({"guild_id": guild_id})
        if doc:
            return VoiceSettings.from_dict(doc)

        new_settings = VoiceSettings(guild_id=guild_id)
        try:
            await self.insert_one(new_settings.to_dict())
            return new_settings
        except DuplicateKeyError:
            doc = await self.find_one({"guild_id": guild_id})
            return VoiceSettings.from_dict(doc) if doc else new_settings

    async def update_settings(self, guild_id: int, update_data: Dict[str, Any]) -> bool:
        """Update voice tracking settings for a guild."""
        update_data["updated_at"] = utc_now()
        return await self.update_one({"guild_id": guild_id}, {"$set": update_data}, upsert=True)

    async def start_session(self, guild_id: int, user_id: int, channel_id: int) -> VoiceSession:
        """Record the start of a voice channel session after closing any dangling sessions."""
        await self.end_session(guild_id, user_id)

        session = VoiceSession(
            guild_id=guild_id,
            user_id=user_id,
            channel_id=channel_id,
            joined_at=utc_now(),
        )
        await self.sessions_coll.insert_one(session.to_dict())
        return session

    async def end_session(self, guild_id: int, user_id: int) -> Optional[VoiceSession]:
        """Close the active voice session and calculate duration."""
        # Find the latest open session for this user in this guild
        doc = await self.sessions_coll.find_one(
            {"guild_id": guild_id, "user_id": user_id, "left_at": None},
            sort=[("joined_at", -1)],
        )
        if not doc:
            return None

        now = utc_now()
        joined_at = doc.get("joined_at")
        if isinstance(joined_at, datetime):
            if joined_at.tzinfo is None:
                joined_at = joined_at.replace(tzinfo=timezone.utc)
            duration = int((now - joined_at).total_seconds())
        else:
            duration = 0

        await self.sessions_coll.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "left_at": now,
                    "duration_seconds": max(0, duration),
                }
            },
        )
        doc["left_at"] = now
        doc["duration_seconds"] = max(0, duration)
        return VoiceSession.from_dict(doc)

    async def get_total_voice_time(self, guild_id: int, user_id: int) -> int:
        """Calculate total historical seconds spent in voice channels for a user."""
        pipeline = [
            {"$match": {"guild_id": guild_id, "user_id": user_id, "duration_seconds": {"$gt": 0}}},
            {"$group": {"_id": None, "total_seconds": {"$sum": "$duration_seconds"}}},
        ]
        cursor = self.sessions_coll.aggregate(pipeline)
        result = await cursor.to_list(length=1)
        return result[0]["total_seconds"] if result else 0

