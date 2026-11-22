"""Comprehensive automated tests for Phase 6 Moderation Ecosystem."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.moderation.cog import Moderation
from bot.core.context import UnifiedContext
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import ModerationRepository


def run_async(coro):
    return asyncio.run(coro)


def test_moderation_hierarchy_checks():
    """Verify role hierarchy and sovereign protections in Moderation cog."""
    bot = MagicMock()
    cog = Moderation(bot)

    guild = MagicMock(spec=discord.Guild)
    guild.owner_id = 12345

    mod = MagicMock(spec=discord.Member)
    mod.id = 67890
    mod.guild = guild
    mod.top_role = MagicMock(position=10)

    bot_member = MagicMock(spec=discord.Member)
    bot_member.id = 99999
    bot_member.top_role = MagicMock(position=20)

    # 1. Target is sovereign
    sovereign_target = MagicMock(spec=discord.Member)
    sovereign_target.id = 12345
    err = cog._check_hierarchy(mod, bot_member, sovereign_target)
    assert "Server Sovereign" in err

    # 2. Target has higher role than mod
    high_target = MagicMock(spec=discord.Member)
    high_target.id = 11111
    high_target.top_role = MagicMock(position=15)
    err = cog._check_hierarchy(mod, bot_member, high_target)
    assert "higher than yours" in err

    # 3. Target has higher role than bot
    highest_target = MagicMock(spec=discord.Member)
    highest_target.id = 22222
    highest_target.top_role = MagicMock(position=25)
    mod.top_role.position = 30
    err = cog._check_hierarchy(mod, bot_member, highest_target)
    assert "my role is not high enough" in err
    mod.top_role.position = 10

    # 4. Valid target (lower than both)
    valid_target = MagicMock(spec=discord.Member)
    valid_target.id = 33333
    valid_target.top_role = MagicMock(position=5)
    err = cog._check_hierarchy(mod, bot_member, valid_target)
    assert err is None


def test_moderation_sqlite_warnings_and_cases(tmp_path: Path):
    """Test warning logging, history retrieval, and case tracking in SQLite."""
    async def _test():
        db_file = tmp_path / "test_mod.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = ModerationRepository(db)
            guild_id = 100
            user_id = 200
            mod_id = 300

            # Add warnings
            w1 = await repo.add_warning(guild_id, user_id, mod_id, "First warning: spam")
            w2 = await repo.add_warning(guild_id, user_id, mod_id, "Second warning: toxicity")
            assert w1 > 0
            assert w2 > 0

            # Fetch warnings
            warns = await repo.get_warnings(guild_id, user_id)
            assert len(warns) == 2
            assert warns[0]["reason"] == "Second warning: toxicity"

            # Check cases
            cases = await repo.get_user_cases(guild_id, user_id)
            assert len(cases) == 2
            assert cases[0].action == "WARN"

            # Clear warnings
            cleared = await repo.clear_warnings(guild_id, user_id)
            assert cleared == 2
            assert len(await repo.get_warnings(guild_id, user_id)) == 0
        finally:
            await db.close()

    run_async(_test())


def test_moderation_ban_and_kick(tmp_path: Path):
    """Test ban and kick command execution with permission checks and logging."""
    async def _test():
        db_file = tmp_path / "test_mod_actions.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            bot = MagicMock()
            bot.db = db
            bot.db_manager = db
            bot.moderation_repo = ModerationRepository(db)
            cog = Moderation(bot)

            guild = MagicMock(spec=discord.Guild)
            guild.id = 500
            guild.name = "Mod Test Server"
            guild.owner_id = 99999
            guild.ban = AsyncMock()

            bot_member = MagicMock(spec=discord.Member)
            bot_member.id = 88888
            bot_member.guild_permissions.ban_members = True
            bot_member.guild_permissions.kick_members = True
            bot_member.top_role = MagicMock(position=50)
            guild.me = bot_member

            mod = MagicMock(spec=discord.Member)
            mod.id = 77777
            mod.guild = guild
            mod.guild_permissions.ban_members = True
            mod.guild_permissions.kick_members = True
            mod.top_role = MagicMock(position=40)

            target = MagicMock(spec=discord.Member)
            target.id = 11111
            target.guild = guild
            target.top_role = MagicMock(position=10)
            target.kick = AsyncMock()

            # Execute Ban
            ctx_ban = MagicMock(spec=UnifiedContext)
            ctx_ban.guild = guild
            ctx_ban.author = mod
            ctx_ban.reply = AsyncMock()
            await cog._execute_ban(ctx_ban, target, "Violating server rules")
            guild.ban.assert_awaited_once()
            assert ctx_ban.reply.called

            # Check case was logged
            cases = await bot.moderation_repo.get_user_cases(guild.id, target.id)
            assert len(cases) == 1
            assert cases[0].action == "BAN"

            # Execute Kick
            ctx_kick = MagicMock(spec=UnifiedContext)
            ctx_kick.guild = guild
            ctx_kick.author = mod
            ctx_kick.reply = AsyncMock()
            await cog._execute_kick(ctx_kick, target, "Spamming voice")
            target.kick.assert_awaited_once()
            assert ctx_kick.reply.called

            cases_after_kick = await bot.moderation_repo.get_user_cases(guild.id, target.id)
            assert len(cases_after_kick) == 2
            assert cases_after_kick[0].action == "KICK"
        finally:
            await db.close()

    run_async(_test())


def test_moderation_lock_unlock_and_purge():
    """Test text channel lock/unlock overwrites and purge."""
    async def _test():
        bot = MagicMock()
        cog = Moderation(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 500
        guild.owner_id = 99999
        guild.default_role = MagicMock()

        bot_member = MagicMock(spec=discord.Member)
        bot_member.guild_permissions.manage_channels = True
        bot_member.guild_permissions.manage_messages = True
        guild.me = bot_member

        mod = MagicMock(spec=discord.Member)
        mod.id = 77777
        mod.guild = guild
        mod.guild_permissions.manage_channels = True
        mod.guild_permissions.manage_messages = True

        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = guild
        channel.mention = "<#123>"
        channel.set_permissions = AsyncMock()
        channel.purge = AsyncMock(return_value=[MagicMock(), MagicMock()])

        ctx = MagicMock(spec=UnifiedContext)
        ctx.guild = guild
        ctx.channel = channel
        ctx.author = mod
        ctx.reply = AsyncMock()
        ctx._source = MagicMock()

        # Lock
        await cog._execute_lock(ctx, channel)
        channel.set_permissions.assert_awaited_with(
            guild.default_role, send_messages=False, reason=f"Channel Lock by {mod}"
        )

        # Unlock
        channel.set_permissions.reset_mock()
        await cog._execute_unlock(ctx, channel)
        channel.set_permissions.assert_awaited_with(
            guild.default_role, send_messages=None, reason=f"Channel Unlock by {mod}"
        )

        # Purge
        await cog._execute_purge(ctx, 15)
        channel.purge.assert_awaited_with(limit=15)
        assert ctx.reply.called

    run_async(_test())

