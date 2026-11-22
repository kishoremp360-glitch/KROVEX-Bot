"""Music configuration settings repository."""

from __future__ import annotations

from typing import Any, Dict, Optional
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from bot.database.models import MusicSettings, utc_now
from bot.database.repositories.base import BaseRepository


class MusicRepository(BaseRepository):
    """Repository handling persistent music settings per guild (volume, 24/7 mode, loop)."""

    async def get_or_create(self, guild_id: int) -> MusicSettings:
        """Fetch guild music settings or initialize defaults with race protection."""
        doc = await self.find_one({"guild_id": guild_id})
        if doc:
            return MusicSettings.from_dict(doc)

        new_settings = MusicSettings(guild_id=guild_id)
        try:
            await self.insert_one(new_settings.to_dict())
            return new_settings
        except DuplicateKeyError:
            doc = await self.find_one({"guild_id": guild_id})
            return MusicSettings.from_dict(doc) if doc else new_settings

    async def update_settings(self, guild_id: int, update_data: Dict[str, Any]) -> bool:
        """Update music configuration for a guild."""
        update_data["updated_at"] = utc_now()
        return await self.update_one({"guild_id": guild_id}, {"$set": update_data}, upsert=True)

