"""Guild settings repository."""

from __future__ import annotations

from typing import Any, Dict, Optional
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from bot.database.models import GuildSettings, utc_now
from bot.database.repositories.base import BaseRepository


class GuildRepository(BaseRepository):
    """Repository handling guild-specific configuration and prefix overrides."""

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        super().__init__(collection)
        # Fast in-memory cache for prefixes to avoid constant DB queries on every message
        self._prefix_cache: Dict[int, str] = {}

    async def get_or_create(self, guild_id: int, default_prefix: str = "!") -> GuildSettings:
        """Fetch existing settings or create default settings for the guild."""
        doc = await self.find_one({"guild_id": guild_id})
        if doc:
            settings = GuildSettings.from_dict(doc)
            self._prefix_cache[guild_id] = settings.prefix
            return settings

        # Create new settings with duplicate race condition protection
        new_settings = GuildSettings(guild_id=guild_id, prefix=default_prefix)
        try:
            await self.insert_one(new_settings.to_dict())
            self._prefix_cache[guild_id] = default_prefix
            return new_settings
        except DuplicateKeyError:
            doc = await self.find_one({"guild_id": guild_id})
            if doc:
                settings = GuildSettings.from_dict(doc)
                self._prefix_cache[guild_id] = settings.prefix
                return settings
            return new_settings

    async def get_prefix(self, guild_id: int, default_prefix: str = "!") -> str:
        """Get guild prefix with in-memory caching."""
        if guild_id in self._prefix_cache:
            return self._prefix_cache[guild_id]

        settings = await self.get_or_create(guild_id, default_prefix=default_prefix)
        return settings.prefix

    async def set_prefix(self, guild_id: int, prefix: str) -> bool:
        """Update guild prefix and synchronize cache."""
        updated = await self.update_one(
            {"guild_id": guild_id},
            {
                "$set": {
                    "prefix": prefix,
                    "updated_at": utc_now(),
                }
            },
            upsert=True,
        )
        self._prefix_cache[guild_id] = prefix
        return updated

