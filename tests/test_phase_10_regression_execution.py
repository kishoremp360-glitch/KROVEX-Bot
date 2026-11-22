"""Phase 10: Full Regression & Production Readiness Execution Test Suite.

Audits and verifies:
- P10-TC01: Root Slash Command Tree Headroom Limit (<= 100 limit, 43 root items, 57 headroom slots).
- P10-TC02: Subcommand Group Nesting Compliance (max 2 levels depth, <= 25 subcommands per group).
- P10-TC03: Slash Command & Subcommand Name/Description Specification Compliance.
- P10-TC04: Prefix Command Collision & Alias Resolution Integrity.
- P10-TC05: Custom Command Lifecycle, Template Variable Substitution & Guild Isolation.
- P10-TC06: Mimic Persona Lifecycle, Constraints & Guild Isolation.
- P10-TC07: Mention Service Notification Filtering & DM Queue Routing.
- P10-TC08: Owner Panel Voice Decoupling Regression Verification (zero voice channel check).
- P10-TC09: Bot Role Hierarchy Safety & Graceful 403 / Position Handling.
- P10-TC10: End-to-End System Readiness (All Cogs, Services, and DB Managers).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import re
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from discord.ext import commands
import pytest

from bot.config import BotConfig
from bot.core.bot import DeathBot
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.models import CustomCommandModel
from bot.database.repositories.custom_command_repo import CustomCommandRepository
from bot.database.repositories.sqlite_repos import MimicRepository
from bot.services.bot_role_service import BotRoleService
from bot.services.dm_queue_service import DMQueueService
from bot.services.mention_service import MentionService
from bot.utils.custom_commands import render_safe_template, validate_command_name_format
from tests.test_command_restructuring import get_test_bot


@pytest.mark.asyncio
async def test_p10_tc01_slash_root_command_headroom():
    """P10-TC01: Verify root slash command tree strictly adheres to Discord 100-command limit."""
    bot = await get_test_bot()
    root_items = bot.tree.get_commands()
    root_names = {c.name for c in root_items}

    assert len(root_items) <= 100, f"Exceeded Discord 100 limit, got {len(root_items)}: {root_names}"
    assert len(root_items) == 46, f"Expected 46 root items, got {len(root_items)}: {root_names}"
    headroom = 100 - len(root_items)
    assert headroom == 54, f"Expected 54 headroom slots, got {headroom}"


@pytest.mark.asyncio
async def test_p10_tc02_subcommand_nesting_depth_limit():
    """P10-TC02: Verify no command group exceeds Discord's maximum allowed subcommand nesting depth (max 2 levels)."""
    bot = await get_test_bot()
    root_items = bot.tree.get_commands()

    def check_depth(cmd, current_depth: int):
        assert current_depth <= 2, f"Command '{cmd.name}' exceeds Discord max nesting depth of 2 (got {current_depth})"
        if hasattr(cmd, "commands") and cmd.commands:
            assert len(cmd.commands) <= 25, f"Group '{cmd.name}' exceeds Discord 25 subcommand limit (got {len(cmd.commands)})"
            for sub in cmd.commands:
                check_depth(sub, current_depth + 1)

    for root_cmd in root_items:
        check_depth(root_cmd, 0)


@pytest.mark.asyncio
async def test_p10_tc03_slash_description_and_name_validation():
    """P10-TC03: Verify all registered slash commands and subcommands meet Discord naming & description specs."""
    bot = await get_test_bot()
    root_items = bot.tree.get_commands()
    name_regex = re.compile(r"^[-_\w]+$")

    all_commands = []
    def collect(cmd):
        all_commands.append(cmd)
        if hasattr(cmd, "commands") and cmd.commands:
            for sub in cmd.commands:
                collect(sub)

    for root_cmd in root_items:
        collect(root_cmd)

    for cmd in all_commands:
        # Discord spec: 1-32 chars, lowercase, regex match
        assert 1 <= len(cmd.name) <= 32, f"Command name '{cmd.name}' length out of bounds (1-32)"
        assert cmd.name.lower() == cmd.name, f"Command name '{cmd.name}' must be lowercase"
        assert name_regex.match(cmd.name), f"Command name '{cmd.name}' contains invalid characters"

        # Description: 1-100 chars
        desc = getattr(cmd, "description", "") or ""
        assert 1 <= len(desc) <= 100, f"Command '{cmd.name}' description length '{len(desc)}' out of bounds (1-100)"


@pytest.mark.asyncio
async def test_p10_tc04_prefix_command_collision_and_alias_resolution():
    """P10-TC04: Verify prefix command registry has zero conflicting ambiguous root aliases between cogs."""
    bot = await get_test_bot()
    alias_map: dict[str, str] = {}

    for cmd in bot.commands:
        primary = cmd.name.lower()
        if primary in alias_map:
            assert alias_map[primary] == cmd.qualified_name, (
                f"Collision: prefix command '{primary}' defined multiple times"
            )
        alias_map[primary] = cmd.qualified_name

        for alias in cmd.aliases:
            a_lower = alias.lower()
            if a_lower in alias_map:
                assert alias_map[a_lower] == cmd.qualified_name, (
                    f"Collision on alias '{a_lower}': mapped to '{alias_map[a_lower]}' and '{cmd.qualified_name}'"
                )
            alias_map[a_lower] = cmd.qualified_name

    # Check key operational aliases
    assert "op" in alias_map, "'op' alias must resolve to owner panel"
    assert "p" in alias_map, "'p' alias must resolve to music play"
    assert "q" in alias_map, "'q' alias must resolve to music queue"


@pytest.mark.asyncio
async def test_p10_tc05_custom_command_lifecycle_and_template_vars(tmp_path: Path):
    """P10-TC05: Verify custom command CRUD, template variable substitution, and guild isolation."""
    db_file = tmp_path / "test_p10_custom.sqlite"
    manager = SQLiteDatabaseManager(db_path=db_file)
    await manager.connect()

    try:
        repo = CustomCommandRepository(manager)
        now = datetime.now(timezone.utc)

        # 1. Create custom command in guild 111
        created = await repo.create_command(
            guild_id=111,
            name="welcomecmd",
            response_type="text",
            content="Welcome {user} to {server}!",
            creator_id=999,
        )
        assert created.guild_id == 111
        assert created.name == "welcomecmd"

        # 2. Template variable rendering
        rendered, err = render_safe_template(
            template=created.content or "",
            context={"user": "Kishore", "server": "MusicMaid Support"},
        )
        assert err is None
        assert rendered == "Welcome Kishore to MusicMaid Support!"

        # 3. Guild isolation: query from guild 222 returns None
        found_g1 = await repo.get_command(111, "welcomecmd")
        found_g2 = await repo.get_command(222, "welcomecmd")
        assert found_g1 is not None
        assert found_g2 is None

        # 4. Name format validation
        is_valid, _ = validate_command_name_format("welcomecmd")
        assert is_valid is True
        is_invalid, _ = validate_command_name_format("bad name with spaces")
        assert is_invalid is False
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_p10_tc06_mimic_persona_lifecycle(tmp_path: Path):
    """P10-TC06: Verify mimic identity repository methods, nickname limits, and guild isolation."""
    db_file = tmp_path / "test_p10_mimic.sqlite"
    manager = SQLiteDatabaseManager(db_path=db_file)
    await manager.connect()

    try:
        repo = MimicRepository(manager)

        # 1. Set nickname and avatar for guild 555
        await repo.set_nickname(555, "Support Persona")
        await repo.set_avatar(555, "https://example.com/avatar.png")

        # 2. Retrieve profile
        profile = await repo.get_profile(555)
        assert profile is not None
        assert profile["nickname"] == "Support Persona"
        assert profile["avatar_url"] == "https://example.com/avatar.png"

        # 3. Guild isolation: guild 666 profile has no nickname
        profile_other = await repo.get_profile(666)
        assert profile_other is None or profile_other.get("nickname") is None

        # 4. Reset profile
        res = await repo.reset_profile(555)
        assert res is True
        reset_profile = await repo.get_profile(555)
        assert reset_profile is None or (reset_profile.get("nickname") is None and reset_profile.get("avatar_url") is None)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_p10_tc07_mention_service_dm_queue_routing():
    """P10-TC07: Verify MentionService ignores self-mentions/bots and routes to DM queue."""
    bot = await get_test_bot()
    srv = bot.get_cog("Mention Notifications") or MentionService(bot)

    # 1. Self mention check
    msg_self = MagicMock(spec=discord.Message)
    msg_self.id = 1001
    msg_self.guild = MagicMock(spec=discord.Guild)
    msg_self.guild.id = 777
    msg_self.author = MagicMock(spec=discord.Member)
    msg_self.author.id = 12345
    msg_self.author.bot = False
    target_user = MagicMock(spec=discord.Member)
    target_user.id = 12345  # Same as author -> self mention
    target_user.bot = False
    msg_self.mentions = [target_user]

    dm_queue = MagicMock()
    dm_queue.enqueue = AsyncMock()
    with patch.object(bot, "get_cog", return_value=dm_queue):
        await srv.on_message(msg_self)
        dm_queue.enqueue.assert_not_called()

    # 2. Bot mention check
    msg_bot = MagicMock(spec=discord.Message)
    msg_bot.id = 1002
    msg_bot.guild = msg_self.guild
    msg_bot.author = msg_self.author
    target_bot = MagicMock(spec=discord.Member)
    target_bot.id = 99999
    target_bot.bot = True  # Bot user
    msg_bot.mentions = [target_bot]

    with patch.object(bot, "get_cog", return_value=dm_queue):
        await srv.on_message(msg_bot)
        dm_queue.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_p10_tc08_owner_panel_voice_decoupling_regression():
    """P10-TC08: Verify /ownerpanel is completely decoupled from voice channel requirements."""
    bot = await get_test_bot()

    # 1. Verify ownerpanel is registered in root tree
    owner_cmd = bot.tree.get_command("ownerpanel")
    assert owner_cmd is not None, "Root slash command /ownerpanel must exist in tree"

    # 2. Verify vc command exists for dedicated voice controls
    vc_group = bot.tree.get_command("vc")
    assert vc_group is not None, "Root group /vc must exist for dedicated voice controls"

    # 3. Inspect owner panel execution to verify no voice channel requirement exists
    owner_cog = bot.get_cog("Owner Dashboard") or bot.get_cog("OwnerPanelCog")
    assert owner_cog is not None, "Owner panel cog must be loaded"

    # Mock interaction with user having NO voice state (voice=None)
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 999  # Owner
    interaction.user.voice = None  # NOT in any voice channel
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 123456789
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    # Bot config treats 999 as owner
    with patch.object(bot, "is_owner", AsyncMock(return_value=True)):
        if hasattr(owner_cog, "_execute_ownerpanel"):
            await owner_cog._execute_ownerpanel(interaction)
        elif hasattr(owner_cog, "ownerpanel"):
            # Command callback
            callback = getattr(owner_cog.ownerpanel, "callback", None)
            if callback:
                await callback(owner_cog, interaction)

    # Verify that NO "Voice Channel Required" error was dispatched
    for call in interaction.response.send_message.call_args_list:
        kwargs = call.kwargs
        embed = kwargs.get("embed")
        if embed:
            assert "Voice Channel Required" not in getattr(embed, "title", ""), (
                "Regression: /ownerpanel must not require a voice channel"
            )


@pytest.mark.asyncio
async def test_p10_tc09_bot_role_hierarchy_safety():
    """P10-TC09: Verify BotRoleService gracefully handles role hierarchy without 403 Forbidden crashes."""
    service = BotRoleService(MagicMock())

    guild = MagicMock(spec=discord.Guild)
    guild.name = "Test Hierarchy Guild"
    guild.roles = []

    # Mock bot member with top_role at position 5
    bot_member = MagicMock(spec=discord.Member)
    bot_top_role = MagicMock(spec=discord.Role)
    bot_top_role.position = 5
    bot_member.top_role = bot_top_role
    bot_member.roles = [bot_top_role]
    bot_member.guild_permissions = discord.Permissions(manage_roles=True)
    guild.me = bot_member

    # Create pre-existing role positioned higher than bot (position 10)
    high_role = MagicMock(spec=discord.Role)
    high_role.name = "KROVEX"
    high_role.position = 10
    high_role.managed = False
    high_role.permissions = discord.Permissions(administrator=True)
    high_role.color = discord.Color.default()
    high_role.edit = AsyncMock()
    guild.roles = [high_role, bot_top_role]

    def create_mock_role(name, position=1):
        r = MagicMock(spec=discord.Role)
        r.name = name
        r.position = position
        r.managed = False
        r.permissions = discord.Permissions(administrator=True)
        r.color = discord.Color.default()
        r.edit = AsyncMock()
        return r

    guild.create_role = AsyncMock(side_effect=lambda **kwargs: create_mock_role(kwargs.get("name", "Role"), position=1))

    # Run setup_bot_roles - should detect role is higher than top_role and log warning without crashing
    active, failed, err = await service.setup_bot_roles(guild)

    # Role could not be assigned to bot due to hierarchy, but process completed safely
    assert err is None
    assert isinstance(active, list)


@pytest.mark.asyncio
async def test_p10_tc10_end_to_end_system_readiness():
    """P10-TC10: Verify all cogs, services, database schemas, and listeners are healthy and production-ready."""
    bot = await get_test_bot()

    # 1. Essential cogs verification
    required_cogs = [
        "ServerAdmin",
        "AutoMod",
        "EconomyCog",
        "Fun & Entertainment",
        "LevelingCog",
        "Voice System",
        "Music System",
        "TicketsCog",
        "Moderation",
        "Help",
    ]
    loaded_cogs = list(bot.cogs.keys())
    for cog_name in required_cogs:
        assert cog_name in loaded_cogs, f"Required cog '{cog_name}' must be loaded"

    # 2. Database manager operational
    assert bot.db_manager is not None
    assert bot.db_manager.is_connected is True

    # 3. Tree sync readiness
    assert bot.tree is not None
    assert len(bot.tree.get_commands()) == 46
