"""Automated Diagnostics and Regression Tests for Guild Prefix System and Command Execution."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord
from discord.ext import commands

from bot.config import BotConfig
from bot.core.bot import DeathBot, get_prefix
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories import GuildRepository, ServerAdminRepository


@pytest.mark.asyncio
async def test_prefix_update_and_sqlite_persistence(tmp_path):
    """Verify that updating guild prefix persists in SQLite and can be retrieved."""
    db_file = tmp_path / "test_prefix.sqlite"
    db = SQLiteDatabaseManager(db_file)
    await db.connect()

    admin_repo = ServerAdminRepository(db)
    guild_repo = GuildRepository(db)
    guild_id = 1560990395666538529

    # Default prefix before any update
    p_initial = await guild_repo.get_prefix(guild_id, default="!")
    assert p_initial == "!"

    # Update prefix to '.'
    await admin_repo.set_prefix(guild_id, ".")

    # Retrieve updated prefix
    p_updated = await guild_repo.get_prefix(guild_id, default="!")
    assert p_updated == "."

    # Update to another prefix like ','
    await admin_repo.set_prefix(guild_id, ",")
    p_comma = await guild_repo.get_prefix(guild_id, default="!")
    assert p_comma == ","

    await db.close()


@pytest.mark.asyncio
async def test_dynamic_get_prefix_resolution(tmp_path):
    """Verify that get_prefix resolver accurately extracts custom prefix '.' from database."""
    db_file = tmp_path / "test_get_prefix.sqlite"
    db = SQLiteDatabaseManager(db_file)
    await db.connect()

    guild_id = 999888777
    admin_repo = ServerAdminRepository(db)
    await admin_repo.set_prefix(guild_id, ".")

    bot = MagicMock(spec=DeathBot)
    bot.config = MagicMock()
    bot.config.default_prefix = "!"
    bot.db_manager = db
    bot.db_manager.is_connected = True
    bot.guild_repo = GuildRepository(db)
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718

    # Message from configured guild
    msg = MagicMock(spec=discord.Message)
    msg.guild = MagicMock(spec=discord.Guild)
    msg.guild.id = guild_id
    msg.content = ".help"

    resolved = await get_prefix(bot, msg)
    assert "." in resolved
    # Bot mention is also accepted
    assert f"<@{bot.user.id}> " in resolved or f"<@!{bot.user.id}> " in resolved

    await db.close()


@pytest.mark.asyncio
async def test_on_message_dispatches_process_commands():
    """Verify DeathBot.on_message calls process_commands for user messages and ignores bots."""
    bot = DeathBot(config=BotConfig.from_env(validate=False))
    bot.process_commands = AsyncMock()

    # User message
    user_msg = MagicMock(spec=discord.Message)
    user_msg.author = MagicMock()
    user_msg.author.bot = False
    user_msg.content = ".help"

    await bot.on_message(user_msg)
    bot.process_commands.assert_awaited_once_with(user_msg)

    # Bot message (should be ignored)
    bot.process_commands.reset_mock()
    bot_msg = MagicMock(spec=discord.Message)
    bot_msg.author = MagicMock()
    bot_msg.author.bot = True
    bot_msg.content = ".help"

    await bot.on_message(bot_msg)
    bot.process_commands.assert_not_awaited()

