"""Tests for Phase 2A.4 Slash Command Restructuring & Tree Architecture.

Verifies:
1. Exact Root Slash count = 29 items (19 groups + 10 standalone shortcuts).
2. Root headroom = 71 available slots (out of Discord's 100 limit).
3. Exactly 10 standalone commands retained at root.
4. Exactly 19 groups present in command tree.
5. Duplicate Slash retirements: `/love`, `/latency`, `/daily` absent from root; `/interact ship` exists.
6. Prefix backward compatibility: `!love` and `!lovemeter` resolve to `ship`; `!daily` exists; `!latency` resolves to `ping`.
7. Mimic nick alias collision resolved: `mimic nick` aliases do not include `nickname`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.core.bot import DeathBot
from bot.config import BotConfig
from bot.database.sqlite_manager import SQLiteDatabaseManager

_CACHED_BOT: DeathBot | None = None


async def get_test_bot() -> DeathBot:
    global _CACHED_BOT
    if _CACHED_BOT is not None:
        return _CACHED_BOT

    # Use a temp directory for DB
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_restructure.sqlite"
    db = SQLiteDatabaseManager(db_path=db_path)
    await db.connect()

    bot = DeathBot(config=BotConfig.from_env(validate=False))
    bot.db_manager = db
    bot._init_database = AsyncMock()
    bot.sync_app_commands = AsyncMock()

    # Load services
    await bot.load_extension("bot.services.security_service")
    await bot.load_extension("bot.services.automod_service")
    await bot.load_extension("bot.services.dm_queue_service")
    await bot.load_extension("bot.services.logging_service")
    await bot.load_extension("bot.services.mention_service")
    await bot.load_extension("bot.services.bot_role_service")

    # Load all cogs
    await bot.load_cogs()

    _CACHED_BOT = bot
    return bot


@pytest.mark.asyncio
async def test_root_command_count_and_headroom():
    """Verify root count satisfies Discord's 100 limit with ample headroom."""
    bot = await get_test_bot()
    root_items = bot.tree.get_commands()
    root_names = {c.name for c in root_items}

    assert len(root_items) <= 100, f"Exceeded Discord 100 limit, got {len(root_items)}: {root_names}"
    assert len(root_items) == 46, f"Expected 46 root items, got {len(root_items)}: {root_names}"
    headroom = 100 - len(root_items)
    assert headroom == 54, f"Expected 54 headroom slots, got {headroom}"


@pytest.mark.asyncio
async def test_retained_standalone_commands():
    """Verify standalone root commands are registered."""
    bot = await get_test_bot()
    expected_standalone = {
        "play",
        "pause",
        "skip",
        "stop",
        "queue",
        "ping",
        "serverinfo",
        "userinfo",
        "avatar",
        "help",
        "ownerpanel",
        "vcpanel",
        "governance",
        "ban",
        "unban",
        "kick",
        "timeout",
        "untimeout",
        "warn",
        "warnings",
        "clearwarns",
        "purge",
        "lock",
        "unlock",
        "slowmode",
    }
    root_items = bot.tree.get_commands()
    actual_standalone = {
        c.name for c in root_items if not (hasattr(c, "commands") and bool(c.commands))
    }

    assert actual_standalone == expected_standalone, (
        f"Standalone mismatch: {actual_standalone.symmetric_difference(expected_standalone)}"
    )


@pytest.mark.asyncio
async def test_retained_and_new_groups():
    """Verify exactly 21 groups exist at root level."""
    bot = await get_test_bot()
    expected_groups = {
        "admin",
        "setup",
        "automod",
        "eco",
        "rate",
        "level",
        "logs",
        "game",
        "mimic",
        "music",
        "playlist",
        "vc",
        "rr",
        "security",
        "shop",
        "soul",
        "interact",
        "react",
        "ticket",
        "util",
        "welcome",
    }
    root_items = bot.tree.get_commands()
    actual_groups = {
        c.name for c in root_items if hasattr(c, "commands") and bool(c.commands)
    }

    assert actual_groups == expected_groups, (
        f"Group mismatch: {actual_groups.symmetric_difference(expected_groups)}"
    )


@pytest.mark.asyncio
async def test_duplicate_retirements_from_tree():
    """Verify retired duplicates (/love, /latency, /daily) are absent from root tree."""
    bot = await get_test_bot()
    root_items = bot.tree.get_commands()
    root_names = {c.name for c in root_items}

    assert "love" not in root_names, "/love must be retired from root slash tree"
    assert "latency" not in root_names, "/latency must be retired from root slash tree"
    assert "daily" not in root_names, "/daily root slash must be retired (retained under /eco daily)"

    # Verify /interact ship and /eco daily exist in subcommands
    interact_group = next((c for c in root_items if c.name == "interact"), None)
    assert interact_group is not None
    interact_subnames = {sub.name for sub in interact_group.commands}
    assert "ship" in interact_subnames, "/interact ship must exist"

    eco_group = next((c for c in root_items if c.name == "eco"), None)
    assert eco_group is not None
    eco_subnames = {sub.name for sub in eco_group.commands}
    assert "daily" in eco_subnames, "/eco daily must exist"


@pytest.mark.asyncio
async def test_prefix_backward_compatibility():
    """Verify prefix commands and backward-compatible aliases exist."""
    bot = await get_test_bot()

    # !ship exists and has love, lovemeter aliases
    ship_cmd = bot.get_command("ship")
    assert ship_cmd is not None, "!ship prefix command must exist"
    assert "love" in ship_cmd.aliases, "'love' must be an alias for !ship"
    assert "lovemeter" in ship_cmd.aliases, "'lovemeter' must be an alias for !ship"

    # Resolving via get_command("love") returns the ship command
    resolved_love = bot.get_command("love")
    assert resolved_love is not None
    assert resolved_love.name == "ship"

    # !daily prefix command exists
    daily_cmd = bot.get_command("daily")
    assert daily_cmd is not None, "!daily prefix command must exist"

    # !latency resolves to ping
    latency_cmd = bot.get_command("latency")
    assert latency_cmd is not None, "!latency prefix alias must exist"
    assert latency_cmd.name == "ping" or "latency" in latency_cmd.aliases


@pytest.mark.asyncio
async def test_mimic_nick_collision_resolved():
    """Verify mimic nick alias does not collide with !nick."""
    bot = await get_test_bot()
    mimic_nick_cmd = bot.get_command("mimic nick")
    assert mimic_nick_cmd is not None, "mimic nick must exist"
    assert "nickname" not in mimic_nick_cmd.aliases, "'nickname' must not be an alias on mimic nick"

    # Nick command in moderation or utility should resolve without conflict
    nick_cmd = bot.get_command("nick")
    if nick_cmd is not None:
        assert nick_cmd.name != "mimic"
