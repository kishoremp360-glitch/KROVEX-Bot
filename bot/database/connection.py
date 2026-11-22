"""MongoDB connection manager utilizing Motor for asynchronous persistence."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from bot.utils.logger import get_logger

logger = get_logger("death_bot.database")


class DatabaseConnectionError(Exception):
    """Raised when MongoDB connection fails or cannot be established."""
    pass


class DatabaseManager:
    """Manages asynchronous MongoDB connection lifecycle and schema indexing."""

    COLLECTIONS = [
        "guild_settings",
        "user_profiles",
        "music_settings",
        "voice_settings",
        "voice_sessions",
        "welcome_settings",
        "command_usage",
        "moderation_logs",
        "playlists",
    ]

    def __init__(self, uri: str, database_name: str = "death_bot") -> None:
        self.uri = uri
        self.database_name = database_name
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
        self._is_connected: bool = False

    @property
    def client(self) -> AsyncIOMotorClient:
        if self._client is None:
            raise DatabaseConnectionError("Database client is not initialized. Call connect() first.")
        return self._client

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise DatabaseConnectionError("Database is not connected. Call connect() first.")
        return self._db

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    async def connect(self, timeout_ms: int = 5000) -> None:
        """Establish connection to MongoDB Atlas with connection timeout."""
        if not self.uri:
            raise DatabaseConnectionError("MongoDB URI is empty or not configured.")

        logger.info("Initializing MongoDB Atlas connection...")
        try:
            self._client = AsyncIOMotorClient(
                self.uri,
                serverSelectionTimeoutMS=timeout_ms,
                connectTimeoutMS=timeout_ms,
                socketTimeoutMS=10000,
                maxPoolSize=50,
                minPoolSize=5,
            )
            # Verify connectivity via admin ping
            await self._client.admin.command("ping")
            self._db = self._client[self.database_name]
            self._is_connected = True
            logger.info("MongoDB connected successfully to database: %s", self.database_name)

            # Ensure optimal indexes exist
            await self.ensure_indexes()
        except (ConnectionFailure, ServerSelectionTimeoutError) as err:
            self._is_connected = False
            logger.error("Failed to connect to MongoDB: %s", err)
            raise DatabaseConnectionError(f"Could not connect to MongoDB: {err}") from err
        except Exception as err:
            self._is_connected = False
            logger.error("Unexpected error during MongoDB initialization: %s", err)
            raise DatabaseConnectionError(f"Unexpected database error: {err}") from err

    async def ping(self) -> bool:
        """Perform a quick health check to verify database responsiveness."""
        if not self._is_connected or self._client is None:
            return False
        try:
            await asyncio.wait_for(self._client.admin.command("ping"), timeout=3.0)
            return True
        except Exception as err:
            logger.warning("MongoDB ping health check failed: %s", err)
            return False

    async def disconnect(self) -> None:
        """Close client connection pool gracefully."""
        if self._client:
            logger.info("Closing MongoDB connection pool...")
            self._client.close()
            self._client = None
            self._db = None
            self._is_connected = False
            logger.info("MongoDB connection closed.")

    async def ensure_indexes(self) -> None:
        """Create standard indexes across all collections for high-performance lookups."""
        if self._db is None:
            return

        logger.info("Ensuring database indexes across all collections...")
        try:
            # 1. guild_settings
            await self._db.guild_settings.create_indexes([
                IndexModel([("guild_id", ASCENDING)], unique=True, name="idx_guild_settings_guild_id"),
            ])

            # 2. user_profiles
            await self._db.user_profiles.create_indexes([
                IndexModel([("user_id", ASCENDING)], unique=True, name="idx_user_profiles_user_id"),
                IndexModel([("balance", DESCENDING)], name="idx_user_profiles_balance_leaderboard"),
                IndexModel([("xp", DESCENDING)], name="idx_user_profiles_xp_leaderboard"),
            ])

            # 3. music_settings
            await self._db.music_settings.create_indexes([
                IndexModel([("guild_id", ASCENDING)], unique=True, name="idx_music_settings_guild_id"),
            ])

            # 4. voice_settings
            await self._db.voice_settings.create_indexes([
                IndexModel([("guild_id", ASCENDING)], unique=True, name="idx_voice_settings_guild_id"),
            ])

            # 5. voice_sessions
            await self._db.voice_sessions.create_indexes([
                IndexModel([("guild_id", ASCENDING), ("user_id", ASCENDING)], name="idx_voice_sessions_guild_user"),
                IndexModel([("joined_at", DESCENDING)], name="idx_voice_sessions_joined_at"),
            ])

            # 6. welcome_settings
            await self._db.welcome_settings.create_indexes([
                IndexModel([("guild_id", ASCENDING)], unique=True, name="idx_welcome_settings_guild_id"),
            ])

            # 7. command_usage
            await self._db.command_usage.create_indexes([
                IndexModel([("command_name", ASCENDING)], name="idx_command_usage_name"),
                IndexModel([("user_id", ASCENDING)], name="idx_command_usage_user_id"),
                IndexModel([("timestamp", DESCENDING)], name="idx_command_usage_timestamp"),
            ])

            # 8. moderation_logs
            await self._db.moderation_logs.create_indexes([
                IndexModel([("guild_id", ASCENDING), ("case_id", ASCENDING)], unique=True, name="idx_moderation_logs_case"),
                IndexModel([("guild_id", ASCENDING), ("user_id", ASCENDING)], name="idx_moderation_logs_user"),
            ])

            # 9. playlists
            await self._db.playlists.create_indexes([
                IndexModel([("guild_id", ASCENDING), ("user_id", ASCENDING), ("name", ASCENDING)], unique=True, name="idx_playlists_guild_user_name"),
            ])

            logger.info("Database indexes successfully verified and ensured.")
        except Exception as err:
            logger.error("Failed to build database indexes: %s", err)
            raise

