"""Comprehensive automated tests for Leveling and XP Progression System."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
from types import SimpleNamespace
import pytest
import discord

from bot.cogs.leveling.cog import LevelingCog
from bot.cogs.leveling.card import build_progress_bar, render_rank_card
from bot.core.context import UnifiedContext
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import LevelRepository


def run_async(coro):
    return asyncio.run(coro)


def test_leveling_xp_progression_and_level_up(tmp_path: Path):
    """Verify XP addition, curve calculation, and level-up detection."""
    async def _test():
        db_file = tmp_path / "test_leveling.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = LevelRepository(manager)

        guild_id = 2001
        user_id = 3001

        # Add 100 XP -> level 0 (needs 150)
        xp, lvl, up = await repo.add_xp(guild_id, user_id, 100)
        assert xp == 100
        assert lvl == 0
        assert up is False

        # Add 60 XP -> total 160 -> level 1
        xp, lvl, up = await repo.add_xp(guild_id, user_id, 60)
        assert xp == 160
        assert lvl == 1
        assert up is True

        # Check member data
        data = await repo.get_member(guild_id, user_id)
        assert data["xp"] == 160
        assert data["level"] == 1
        assert data["messages_count"] == 2

        # Check rank
        rank = await repo.get_rank(guild_id, user_id)
        assert rank == 1

        await manager.close()

    run_async(_test())


def test_leveling_rewards_and_exemptions(tmp_path: Path):
    """Verify role rewards CRUD and channel/role exemptions."""
    async def _test():
        db_file = tmp_path / "test_leveling_rewards.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = LevelRepository(manager)

        guild_id = 2001

        # Rewards
        await repo.add_reward(guild_id, 5, 55555)
        await repo.add_reward(guild_id, 10, 101010)

        rewards = await repo.get_rewards(guild_id)
        assert len(rewards) == 2
        assert rewards[0]["level"] == 5
        assert rewards[0]["role_id"] == 55555

        ok = await repo.remove_reward(guild_id, 5)
        assert ok is True
        rewards_after = await repo.get_rewards(guild_id)
        assert len(rewards_after) == 1
        assert rewards_after[0]["level"] == 10

        # Exemptions
        await repo.add_exemption(guild_id, 111222, "channel")
        await repo.add_exemption(guild_id, 333444, "role")

        assert await repo.is_exempt(guild_id, 111222, []) is True
        assert await repo.is_exempt(guild_id, 999999, [333444]) is True
        assert await repo.is_exempt(guild_id, 999999, [888888]) is False

        await repo.remove_exemption(guild_id, 111222, "channel")
        assert await repo.is_exempt(guild_id, 111222, []) is False

        await manager.close()

    run_async(_test())


def test_leveling_leaderboard_accuracy(tmp_path: Path):
    """Verify ranking and leaderboard order."""
    async def _test():
        db_file = tmp_path / "test_leveling_lb.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = LevelRepository(manager)

        guild_id = 5001

        await repo.add_xp(guild_id, 101, 500)
        await repo.add_xp(guild_id, 102, 1200)
        await repo.add_xp(guild_id, 103, 300)

        leaderboard = await repo.get_leaderboard(guild_id, limit=3)
        assert len(leaderboard) == 3
        assert leaderboard[0]["user_id"] == 102
        assert leaderboard[1]["user_id"] == 101
        assert leaderboard[2]["user_id"] == 103

        assert await repo.get_rank(guild_id, 102) == 1
        assert await repo.get_rank(guild_id, 101) == 2
        assert await repo.get_rank(guild_id, 103) == 3

        await manager.close()

    run_async(_test())


def test_progress_bar_and_rank_card():
    """Verify text progress bar formatting and embed construction."""
    bar = build_progress_bar(50, 100, length=10)
    assert "[█████░░░░░]" in bar
    assert "50%" in bar

    mock_member = MagicMock(spec=discord.Member)
    mock_member.display_name = "PlayerOne"
    mock_member.display_avatar.url = "https://example.com/avatar.png"
    mock_member.guild.name = "Test Guild"
    mock_member.guild.icon.url = "https://example.com/icon.png"

    embed = render_rank_card(mock_member, {"level": 3, "xp": 1200, "messages_count": 85}, rank=1)
    assert embed.title == "⭐ Rank Profile • PlayerOne"
    assert any("Level 3" in f.value for f in embed.fields)


def test_leveling_manager_authorization():
    """Configured bot owners, Discord app owners, and admins can manage leveling."""
    async def _test():
        fake_cog = SimpleNamespace(
            bot=SimpleNamespace(
                config=SimpleNamespace(owner_ids=[12345]),
                is_owner=AsyncMock(return_value=False),
            )
        )

        def make_ctx(user_id: int, administrator: bool = False):
            author = SimpleNamespace(
                id=user_id,
                guild_permissions=SimpleNamespace(administrator=administrator),
            )
            return SimpleNamespace(guild=object(), author=author)

        # Configured KROVEX bot owner is allowed without Discord Administrator.
        assert await LevelingCog._is_level_manager(fake_cog, make_ctx(12345)) is True

        # Discord.py application owner fallback is also honored.
        fake_cog.bot.is_owner = AsyncMock(return_value=True)
        assert await LevelingCog._is_level_manager(fake_cog, make_ctx(67890)) is True

        # Server administrators retain their existing access.
        fake_cog.bot.is_owner = AsyncMock(return_value=False)
        assert await LevelingCog._is_level_manager(fake_cog, make_ctx(67890, administrator=True)) is True

        # Ordinary members remain blocked.
        assert await LevelingCog._is_level_manager(fake_cog, make_ctx(67890)) is False

        # No guild context must never grant access.
        no_guild_ctx = make_ctx(12345)
        no_guild_ctx.guild = None
        assert await LevelingCog._is_level_manager(fake_cog, no_guild_ctx) is False

    run_async(_test())
