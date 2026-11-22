"""Phase 2A.7 Verification Tests: Slash Command Renames & Prefix Compatibility.

Verifies:
1. All three new Slash commands exist:
   - /admin prefix
   - /music filter bass
   - /logs channel
2. All three old Slash command names are absent:
   - /admin setprefix
   - /music filter bassboost
   - /logs logchannel
3. Existing Prefix triggers still work:
   - !setprefix (admin)
   - !bassboost and !bb (music)
   - !logchannel and !setlogchannel (logs)
4. Permission and authorization parity:
   - /admin prefix requires administrator permissions
   - /logs channel requires administrator permissions
   - /music filter bass has standard user access
5. Hierarchy limits:
   - Root items count remains 43 (24 standalone + 19 groups; satisfies Discord's 100 limit, 57 headroom slots)
   - /admin direct subcommands <= 25 (exactly 25)
   - /logs direct subcommands <= 25 (exactly 22)
   - /music direct children <= 25 (20 subcommands + 1 subgroup)
   - /music filter subgroup subcommands <= 25 (exactly 5)
   - No group exceeds Discord's 25-subcommand limit
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
from bot.core.context import UnifiedContext

_TEST_BOT: DeathBot | None = None


async def get_test_bot() -> DeathBot:
    global _TEST_BOT
    if _TEST_BOT is not None:
        return _TEST_BOT

    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_renames.sqlite"
    db = SQLiteDatabaseManager(db_path=db_path)
    await db.connect()

    bot = DeathBot(config=BotConfig.from_env(validate=False))
    bot.db_manager = db
    bot._init_database = AsyncMock()
    bot.sync_app_commands = AsyncMock()

    # Load required services
    await bot.load_extension("bot.services.security_service")
    await bot.load_extension("bot.services.automod_service")
    await bot.load_extension("bot.services.dm_queue_service")
    await bot.load_extension("bot.services.logging_service")
    await bot.load_extension("bot.services.mention_service")
    await bot.load_extension("bot.services.bot_role_service")

    # Load all cogs
    await bot.load_cogs()

    _TEST_BOT = bot
    return bot


@pytest.mark.asyncio
async def test_renamed_slash_commands_present_and_old_absent():
    """Verify /admin prefix, /music filter bass, /logs channel exist, and old names are absent."""
    bot = await get_test_bot()
    root_items = bot.tree.get_commands()
    group_map = {c.name: c for c in root_items if hasattr(c, "commands")}

    # 1. /admin prefix exists, /admin setprefix is gone
    admin_group = group_map.get("admin")
    assert admin_group is not None, "Group /admin must exist in slash tree"
    admin_subnames = {sub.name for sub in admin_group.commands}
    assert "prefix" in admin_subnames, "New slash command '/admin prefix' must exist"
    assert "setprefix" not in admin_subnames, "Old slash command '/admin setprefix' must be absent"

    # 2. /music filter bass exists, /music filter bassboost is gone
    music_group = group_map.get("music")
    assert music_group is not None, "Group /music must exist in slash tree"
    filter_group = next((sub for sub in music_group.commands if sub.name == "filter" and hasattr(sub, "commands")), None)
    assert filter_group is not None, "Subgroup /music filter must exist"
    filter_subnames = {sub.name for sub in filter_group.commands}
    assert "bass" in filter_subnames, "New slash command '/music filter bass' must exist"
    assert "bassboost" not in filter_subnames, "Old slash command '/music filter bassboost' must be absent"

    # 3. /logs channel exists, /logs logchannel is gone
    logs_group = group_map.get("logs")
    assert logs_group is not None, "Group /logs must exist in slash tree"
    logs_subnames = {sub.name for sub in logs_group.commands}
    assert "channel" in logs_subnames, "New slash command '/logs channel' must exist"
    assert "logchannel" not in logs_subnames, "Old slash command '/logs logchannel' must be absent"


@pytest.mark.asyncio
async def test_prefix_triggers_and_aliases_intact():
    """Verify prefix commands !setprefix, !bassboost, !bb, !logchannel, !setlogchannel work."""
    bot = await get_test_bot()

    # 1. Admin Prefix Command
    setprefix_cmd = bot.get_command("setprefix")
    assert setprefix_cmd is not None, "Prefix command !setprefix must remain registered"
    assert setprefix_cmd.name == "setprefix"

    # 2. Music Bassboost and alias bb
    bb_cmd = bot.get_command("bassboost")
    assert bb_cmd is not None, "Prefix command !bassboost must remain registered"
    assert "bb" in bb_cmd.aliases, "Alias !bb must remain active for bassboost"
    resolved_bb = bot.get_command("bb")
    assert resolved_bb is not None
    assert resolved_bb.name == "bassboost"

    # 3. Logging Logchannel and alias setlogchannel
    logch_cmd = bot.get_command("logchannel")
    assert logch_cmd is not None, "Prefix command !logchannel must remain registered"
    assert "setlogchannel" in logch_cmd.aliases, "Alias !setlogchannel must remain active"
    resolved_setlog = bot.get_command("setlogchannel")
    assert resolved_setlog is not None
    assert resolved_setlog.name == "logchannel"


@pytest.mark.asyncio
async def test_permission_and_authorization_parity():
    """Verify default_permissions for renamed slash commands."""
    bot = await get_test_bot()
    root_items = bot.tree.get_commands()
    group_map = {c.name: c for c in root_items if hasattr(c, "commands")}

    # /admin prefix requires administrator
    admin_group = group_map["admin"]
    prefix_cmd = next(c for c in admin_group.commands if c.name == "prefix")
    assert prefix_cmd.default_permissions is not None
    assert prefix_cmd.default_permissions.administrator is True

    # /logs channel requires administrator
    logs_group = group_map["logs"]
    channel_cmd = next(c for c in logs_group.commands if c.name == "channel")
    assert channel_cmd.default_permissions is not None
    assert channel_cmd.default_permissions.administrator is True

    # /music filter bass has standard user permissions
    music_group = group_map["music"]
    filter_group = next(c for c in music_group.commands if c.name == "filter")
    bass_cmd = next(c for c in filter_group.commands if c.name == "bass")
    assert bass_cmd.default_permissions is None or bass_cmd.default_permissions.administrator is not True


@pytest.mark.asyncio
async def test_discord_constraints_and_headroom():
    """Verify root count satisfies Discord's 100 limit (43 root items, 57 headroom), and no group exceeds Discord's 25 subcommand limit."""
    bot = await get_test_bot()
    root_items = bot.tree.get_commands()

    # Root items = 43 (19 groups + 24 standalone shortcuts; <= 100 Discord limit)
    assert len(root_items) <= 100, f"Exceeded Discord 100 limit, got {len(root_items)}"
    assert len(root_items) == 43, f"Expected 43 root items, got {len(root_items)}"
    assert (100 - len(root_items)) == 57, "Headroom must remain 57 slots"

    # Subcommand limit <= 25 for every group
    for root in root_items:
        if hasattr(root, "commands"):
            direct_subs = len(root.commands)
            assert direct_subs <= 25, f"Group /{root.name} has {direct_subs} subcommands (max 25 allowed)!"
            for sub in root.commands:
                if hasattr(sub, "commands"):
                    nested_subs = len(sub.commands)
                    assert nested_subs <= 25, f"Subgroup /{root.name} {sub.name} has {nested_subs} subcommands (max 25 allowed)!"

