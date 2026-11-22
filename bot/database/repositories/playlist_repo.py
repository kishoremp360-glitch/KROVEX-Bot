"""Playlist repository for saving, loading, and modifying custom music playlists."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from bot.database.models import utc_now
from bot.database.repositories.base import BaseRepository
from bot.utils.logger import get_logger

logger = get_logger("death_bot.database.playlist")


class PlaylistRepository(BaseRepository):
    """Repository handling per-user and per-guild saved track playlists."""

    async def create_playlist(self, guild_id: int, user_id: int, name: str) -> bool:
        """Create a new empty playlist."""
        clean_name = name.strip().lower()
        doc = {
            "guild_id": guild_id,
            "user_id": user_id,
            "name": clean_name,
            "tracks": [],
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        try:
            await self.insert_one(doc)
            return True
        except DuplicateKeyError:
            return False

    async def get_playlist(self, guild_id: int, user_id: int, name: str) -> Optional[Dict[str, Any]]:
        """Fetch a specific playlist by name."""
        clean_name = name.strip().lower()
        return await self.find_one({"guild_id": guild_id, "user_id": user_id, "name": clean_name})

    async def list_playlists(self, guild_id: int, user_id: int) -> List[Dict[str, Any]]:
        """List all playlists owned by a user in a guild."""
        return await self.find_many({"guild_id": guild_id, "user_id": user_id}, sort_field="name")

    async def add_track(self, guild_id: int, user_id: int, name: str, track_data: Dict[str, Any], max_tracks: int = 100) -> bool:
        """Add a track to an existing playlist."""
        clean_name = name.strip().lower()
        pl = await self.get_playlist(guild_id, user_id, clean_name)
        if not pl:
            return False
        if len(pl.get("tracks", [])) >= max_tracks:
            return False

        return await self.update_one(
            {"guild_id": guild_id, "user_id": user_id, "name": clean_name},
            {
                "$push": {"tracks": track_data},
                "$set": {"updated_at": utc_now()},
            },
        )

    async def remove_track(self, guild_id: int, user_id: int, name: str, index: int) -> bool:
        """Remove a track from a playlist by 1-based index."""
        clean_name = name.strip().lower()
        pl = await self.get_playlist(guild_id, user_id, clean_name)
        if not pl:
            return False
        tracks = pl.get("tracks", [])
        idx = index - 1
        if 0 <= idx < len(tracks):
            tracks.pop(idx)
            return await self.update_one(
                {"guild_id": guild_id, "user_id": user_id, "name": clean_name},
                {"$set": {"tracks": tracks, "updated_at": utc_now()}},
            )
        return False

    async def delete_playlist(self, guild_id: int, user_id: int, name: str) -> bool:
        """Delete an existing playlist."""
        clean_name = name.strip().lower()
        return await self.delete_one({"guild_id": guild_id, "user_id": user_id, "name": clean_name})

