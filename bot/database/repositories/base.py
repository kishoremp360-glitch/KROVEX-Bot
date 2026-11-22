"""Base asynchronous repository for MongoDB CRUD operations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorCollection

from bot.utils.logger import get_logger

logger = get_logger("death_bot.database.repository")


class BaseRepository:
    """Base repository providing standardized async MongoDB operations."""

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self.collection = collection

    async def find_one(self, filter_query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Find a single document matching the filter."""
        try:
            return await self.collection.find_one(filter_query)
        except Exception as err:
            logger.error("find_one error in %s with query %s: %s", self.collection.name, filter_query, err)
            raise

    async def find_many(
        self,
        filter_query: Dict[str, Any],
        sort_field: Optional[str] = None,
        sort_direction: int = 1,
        limit: int = 100,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """Find multiple documents with optional sorting, limit and skip."""
        try:
            cursor = self.collection.find(filter_query).skip(skip).limit(limit)
            if sort_field:
                cursor = cursor.sort(sort_field, sort_direction)
            return await cursor.to_list(length=limit)
        except Exception as err:
            logger.error("find_many error in %s: %s", self.collection.name, err)
            raise

    async def insert_one(self, document: Dict[str, Any]) -> Any:
        """Insert a single document."""
        try:
            result = await self.collection.insert_one(document)
            return result.inserted_id
        except Exception as err:
            logger.error("insert_one error in %s: %s", self.collection.name, err)
            raise

    async def update_one(
        self,
        filter_query: Dict[str, Any],
        update_data: Dict[str, Any],
        upsert: bool = False,
    ) -> bool:
        """Update a single document."""
        try:
            # Ensure update operator is used
            payload = update_data if any(k.startswith("$") for k in update_data.keys()) else {"$set": update_data}
            result = await self.collection.update_one(filter_query, payload, upsert=upsert)
            return result.modified_count > 0 or (upsert and result.upserted_id is not None)
        except Exception as err:
            logger.error("update_one error in %s: %s", self.collection.name, err)
            raise

    async def delete_one(self, filter_query: Dict[str, Any]) -> bool:
        """Delete a single document."""
        try:
            result = await self.collection.delete_one(filter_query)
            return result.deleted_count > 0
        except Exception as err:
            logger.error("delete_one error in %s: %s", self.collection.name, err)
            raise

    async def count_documents(self, filter_query: Dict[str, Any]) -> int:
        """Count documents matching the filter."""
        try:
            return await self.collection.count_documents(filter_query)
        except Exception as err:
            logger.error("count_documents error in %s: %s", self.collection.name, err)
            raise

