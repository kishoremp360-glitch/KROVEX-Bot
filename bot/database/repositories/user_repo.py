"""User profile and economy repository."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from bot.database.models import UserProfile, utc_now
from bot.database.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    """Repository handling persistent user profiles, XP, and balances."""

    async def get_or_create(self, user_id: int) -> UserProfile:
        """Fetch user profile or initialize a new profile with race protection."""
        doc = await self.find_one({"user_id": user_id})
        if doc:
            return UserProfile.from_dict(doc)

        new_profile = UserProfile(user_id=user_id)
        try:
            await self.insert_one(new_profile.to_dict())
            return new_profile
        except DuplicateKeyError:
            doc = await self.find_one({"user_id": user_id})
            return UserProfile.from_dict(doc) if doc else new_profile

    async def add_xp(self, user_id: int, xp_amount: int) -> UserProfile:
        """Atomically add XP and recalculate level."""
        await self.get_or_create(user_id)
        await self.update_one(
            {"user_id": user_id},
            {
                "$inc": {"xp": xp_amount},
                "$set": {"updated_at": utc_now()},
            },
        )
        updated_doc = await self.find_one({"user_id": user_id})
        new_xp = updated_doc.get("xp", 0) if updated_doc else xp_amount
        new_level = int((new_xp / 100) ** 0.5) + 1
        await self.update_one(
            {"user_id": user_id},
            {"$set": {"level": new_level}},
        )
        if updated_doc:
            updated_doc["level"] = new_level
            return UserProfile.from_dict(updated_doc)
        return UserProfile(user_id=user_id, xp=new_xp, level=new_level)

    async def update_balance(self, user_id: int, delta: int) -> int:
        """Atomically increment or decrement user balance."""
        await self.get_or_create(user_id)
        await self.update_one(
            {"user_id": user_id},
            {
                "$inc": {"balance": delta},
                "$set": {"updated_at": utc_now()},
            },
        )
        updated = await self.find_one({"user_id": user_id})
        return updated.get("balance", 0) if updated else 0

