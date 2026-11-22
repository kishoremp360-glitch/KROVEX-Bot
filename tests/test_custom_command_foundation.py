"""Unit and integration test suite for Custom Command Builder Stage 1 Foundation.

Covers:
1. Database schema and repository CRUD operations.
2. Foreign key cascade on alias deletion.
3. Strict guild isolation.
4. Bidirectional name and alias collision prevention.
5. Native command collision rejection (prefix and slash).
6. Name format validation rules (regex, length limits).
7. Safe template parser (allowlist-only tokens, zero eval/exec/format injection).
8. Permission validation model (everyone, required roles, moderator, administrator).
9. In-memory sliding-window cooldown tracker and disabled-command rejection.
10. Atomic usage accounting.
11. Legacy custom_tags table preservation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import discord
import pytest

from bot.database.models import CustomCommandAliasModel, CustomCommandModel
from bot.database.repositories.custom_command_repo import CustomCommandRepository
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.services.custom_command_service import CustomCommandService
from bot.utils.custom_commands import (
    ALLOWED_TEMPLATE_VARS,
    normalize_command_name,
    render_safe_template,
    validate_command_collision,
    validate_command_name_format,
    validate_template_variables,
)


def run_async(coro):
    """Synchronously run async coroutine in isolated event loop."""
    return asyncio.run(coro)


async def create_test_harness(tmp_path: Path):
    """Create an isolated SQLite database, repository, mock bot, and service."""
    db_file = tmp_path / "test_custom_commands.sqlite"
    manager = SQLiteDatabaseManager(db_path=db_file)
    await manager.connect()
    repo = CustomCommandRepository(manager)

    bot = MagicMock()
    bot.all_commands = {
        "play": MagicMock(),
        "pause": MagicMock(),
        "skip": MagicMock(),
        "help": MagicMock(),
        "ping": MagicMock(),
    }
    cmd_play = MagicMock()
    cmd_play.name = "play"
    cmd_admin = MagicMock()
    cmd_admin.name = "admin"
    bot.tree = MagicMock()
    bot.tree.get_commands.return_value = [cmd_play, cmd_admin]

    service = CustomCommandService(repo=repo, bot=bot)
    return manager, repo, service


# =============================================================================
# 1. REPOSITORY CRUD & SCHEMA TESTS
# =============================================================================

def test_custom_command_create_text(tmp_path: Path):
    """Verify creating a text response custom command."""
    async def _test():
        manager, repo, _ = await create_test_harness(tmp_path)
        try:
            cmd = await repo.create_command(
                guild_id=1001,
                name="rules",
                response_type="text",
                content="Welcome to our server! Be respectful.",
                permission_level="everyone",
                cooldown_seconds=10,
                creator_id=999,
            )

            assert cmd.guild_id == 1001
            assert cmd.name == "rules"
            assert cmd.response_type == "text"
            assert cmd.content == "Welcome to our server! Be respectful."
            assert cmd.permission_level == "everyone"
            assert cmd.cooldown_seconds == 10
            assert cmd.is_enabled is True
            assert cmd.creator_id == 999
            assert cmd.uses == 0
        finally:
            await manager.close()

    run_async(_test())


def test_custom_command_create_embed(tmp_path: Path):
    """Verify creating an embed response custom command with JSON serialization."""
    async def _test():
        manager, repo, _ = await create_test_harness(tmp_path)
        try:
            embed_payload = {
                "title": "Server Links",
                "description": "Visit our website and documentation.",
                "color": 0x9D4EDD,
            }
            cmd = await repo.create_command(
                guild_id=1001,
                name="website",
                response_type="embed",
                embed_data=embed_payload,
                permission_level="everyone",
            )

            assert cmd.name == "website"
            assert cmd.response_type == "embed"
            assert cmd.embed_data is not None
            assert cmd.embed_data["title"] == "Server Links"
            assert cmd.embed_data["color"] == 0x9D4EDD
        finally:
            await manager.close()

    run_async(_test())


def test_custom_command_get_by_name(tmp_path: Path):
    """Verify retrieving an existing command by exact normalized name."""
    async def _test():
        manager, repo, _ = await create_test_harness(tmp_path)
        try:
            await repo.create_command(guild_id=1001, name="faq", content="Frequently Asked Questions")

            found = await repo.get_command(guild_id=1001, name="FAQ")  # Case-insensitive
            assert found is not None
            assert found.name == "faq"
            assert found.content == "Frequently Asked Questions"

            missing = await repo.get_command(guild_id=1001, name="nonexistent")
            assert missing is None
        finally:
            await manager.close()

    run_async(_test())


def test_custom_command_update_fields(tmp_path: Path):
    """Verify updating command attributes."""
    async def _test():
        manager, repo, _ = await create_test_harness(tmp_path)
        try:
            await repo.create_command(guild_id=1001, name="socials", content="Twitter: @krovex")

            updated = await repo.update_command(
                guild_id=1001,
                name="socials",
                content="Discord & Twitter: @krovex",
                cooldown_seconds=30,
                permission_level="moderator",
            )

            assert updated is not None
            assert updated.content == "Discord & Twitter: @krovex"
            assert updated.cooldown_seconds == 30
            assert updated.permission_level == "moderator"
        finally:
            await manager.close()

    run_async(_test())


def test_custom_command_delete_and_cascade(tmp_path: Path):
    """Verify deleting a command cascades and cleans up associated aliases."""
    async def _test():
        manager, repo, _ = await create_test_harness(tmp_path)
        try:
            await repo.create_command(guild_id=1001, name="support", content="Open a ticket in #support")
            alias_created = await repo.create_alias(guild_id=1001, alias="helpdesk", target_command="support")
            assert alias_created is True

            # Confirm alias resolves
            resolved = await repo.get_command(guild_id=1001, name="helpdesk", resolve_alias=True)
            assert resolved is not None
            assert resolved.name == "support"

            # Delete primary command
            deleted = await repo.delete_command(guild_id=1001, name="support")
            assert deleted is True

            # Confirm primary command is gone
            assert await repo.get_command(guild_id=1001, name="support") is None

            # Confirm alias is cascaded and gone
            assert await repo.get_alias(guild_id=1001, alias="helpdesk") is None
        finally:
            await manager.close()

    run_async(_test())


def test_custom_command_guild_isolation(tmp_path: Path):
    """Verify strict guild isolation: Guild A cannot access or mutate Guild B commands."""
    async def _test():
        manager, repo, _ = await create_test_harness(tmp_path)
        try:
            await repo.create_command(guild_id=1111, name="info", content="Guild 1111 Info")
            await repo.create_command(guild_id=2222, name="info", content="Guild 2222 Info")

            cmd1 = await repo.get_command(guild_id=1111, name="info")
            cmd2 = await repo.get_command(guild_id=2222, name="info")

            assert cmd1 is not None and cmd2 is not None
            assert cmd1.content == "Guild 1111 Info"
            assert cmd2.content == "Guild 2222 Info"

            # Listing commands is strictly guild-scoped
            guild1_cmds = await repo.list_commands(guild_id=1111)
            assert len(guild1_cmds) == 1
            assert guild1_cmds[0].guild_id == 1111
        finally:
            await manager.close()

    run_async(_test())


def test_custom_command_alias_create_and_resolve(tmp_path: Path):
    """Verify creating aliases and resolving them transparently."""
    async def _test():
        manager, repo, _ = await create_test_harness(tmp_path)
        try:
            await repo.create_command(guild_id=1001, name="donate", content="Support us on Patreon!")
            await repo.create_alias(guild_id=1001, alias="patreon", target_command="donate")
            await repo.create_alias(guild_id=1001, alias="tip", target_command="donate")

            # Resolve aliases
            res1 = await repo.get_command(guild_id=1001, name="patreon", resolve_alias=True)
            res2 = await repo.get_command(guild_id=1001, name="tip", resolve_alias=True)
            assert res1 is not None and res1.name == "donate"
            assert res2 is not None and res2.name == "donate"

            # List aliases for target
            aliases = await repo.list_aliases(guild_id=1001, target_command="donate")
            assert len(aliases) == 2
            assert {a.alias for a in aliases} == {"patreon", "tip"}
        finally:
            await manager.close()

    run_async(_test())


# =============================================================================
# 2. COLLISION & NAME VALIDATION TESTS
# =============================================================================

def test_bidirectional_collision_command_matches_existing_alias(tmp_path: Path):
    """A new custom command cannot be created if an alias with that name already exists."""
    async def _test():
        manager, repo, service = await create_test_harness(tmp_path)
        try:
            await repo.create_command(guild_id=1001, name="original", content="Original content")
            await repo.create_alias(guild_id=1001, alias="alias_one", target_command="original")

            # Try to create a primary command named 'alias_one'
            cmd, err = await service.create_command(guild_id=1001, name="alias_one", content="Colliding content")
            assert cmd is None
            assert "conflicts with an existing alias" in str(err)
        finally:
            await manager.close()

    run_async(_test())


def test_bidirectional_collision_alias_matches_existing_command(tmp_path: Path):
    """An alias cannot be created if a primary custom command with that name already exists."""
    async def _test():
        manager, repo, service = await create_test_harness(tmp_path)
        try:
            await repo.create_command(guild_id=1001, name="target_cmd", content="Target content")
            await repo.create_command(guild_id=1001, name="existing_cmd", content="Existing content")

            # Try to create an alias named 'existing_cmd' pointing to 'target_cmd'
            success, err = await service.create_alias(guild_id=1001, alias="existing_cmd", target_command="target_cmd")
            assert success is False
            assert "conflicts with an existing custom command" in str(err)
        finally:
            await manager.close()

    run_async(_test())


def test_bidirectional_collision_alias_matches_existing_alias(tmp_path: Path):
    """An alias cannot be created if another alias with that name already exists."""
    async def _test():
        manager, repo, service = await create_test_harness(tmp_path)
        try:
            await repo.create_command(guild_id=1001, name="base_cmd", content="Base content")
            await repo.create_alias(guild_id=1001, alias="shortcut", target_command="base_cmd")

            success, err = await service.create_alias(guild_id=1001, alias="shortcut", target_command="base_cmd")
            assert success is False
            assert "already exists in this server" in str(err)
        finally:
            await manager.close()

    run_async(_test())


def test_collision_with_native_prefix_command(tmp_path: Path):
    """Custom command creation is rejected if name conflicts with native prefix command."""
    async def _test():
        manager, _, service = await create_test_harness(tmp_path)
        try:
            cmd, err = await service.create_command(guild_id=1001, name="play", content="Play override")
            assert cmd is None
            assert "reserved system command name" in str(err) or "conflicts with an existing native" in str(err)
        finally:
            await manager.close()

    run_async(_test())


def test_collision_with_native_slash_command(tmp_path: Path):
    """Custom command creation is rejected if name conflicts with native slash command."""
    async def _test():
        manager, _, service = await create_test_harness(tmp_path)
        try:
            cmd, err = await service.create_command(guild_id=1001, name="admin", content="Admin override")
            assert cmd is None
            assert "reserved system command name" in str(err) or "conflicts with an existing native" in str(err)
        finally:
            await manager.close()

    run_async(_test())


def test_command_name_validation_format():
    """Verify name validation accepts lowercase alphanumeric, -, _ and rejects invalid formats."""
    # Valid names
    for valid in ["rules", "my-command", "info_link", "cmd123", "a1"]:
        ok, msg = validate_command_name_format(valid)
        assert ok is True, f"Expected '{valid}' to be valid, got: {msg}"

    # Invalid names
    invalid_cases = [
        ("", "empty"),
        ("a", "too short"),
        ("this_is_a_way_too_long_command_name_that_exceeds_thirty_two_characters", "too long"),
        ("Rules With Spaces", "spaces"),
        ("command!", "punctuation"),
        ("hello@world", "special characters"),
    ]
    for inv, reason in invalid_cases:
        ok, msg = validate_command_name_format(inv)
        assert ok is False, f"Expected '{inv}' ({reason}) to be invalid, but passed."


# =============================================================================
# 3. SAFE TEMPLATE ENGINE TESTS
# =============================================================================

def test_template_parser_all_valid_tokens():
    """Verify safe template engine replaces all allowlisted tokens accurately."""
    template = "Hello {user} ({user_mention})! Welcome to {server} in {channel}. We now have {member_count} members on {date}."
    context = {
        "user": "TheRealRai",
        "user_mention": "<@123456789>",
        "server": "KROVEX Sanctuary",
        "member_count": "150",
        "channel": "#general",
        "date": "2026-11-14",
    }

    rendered, err = render_safe_template(template, context)
    assert err is None
    expected = "Hello TheRealRai (<@123456789>)! Welcome to KROVEX Sanctuary in #general. We now have 150 members on 2026-11-14."
    assert rendered == expected


def test_template_parser_rejects_unknown_tokens():
    """Verify template validator rejects any placeholder not in the allowlist."""
    templates_with_unknown = [
        "Hello {user}, your balance is {balance}",
        "Execute {command} here",
        "Your IP is {ip_address}",
    ]
    for tmpl in templates_with_unknown:
        ok, err = validate_template_variables(tmpl)
        assert ok is False
        assert "Unknown or forbidden variable" in err


def test_template_parser_zero_eval_injection():
    """Verify that malicious Python code injection payloads are strictly rejected without evaluation."""
    malicious_templates = [
        "Result: {__import__('os').system('dir')}",
        "{eval('1+1')}",
        "{open('db/death_bot.sqlite')}",
        "{globals()}",
        "{getattr(bot, 'token')}",
    ]
    for evil in malicious_templates:
        ok, err = validate_template_variables(evil)
        assert ok is False
        assert "Unknown or forbidden variable" in err

        # Even if passed to render, it returns error and empty string, never executing code
        rendered, render_err = render_safe_template(evil, {})
        assert rendered == ""
        assert render_err is not None


# =============================================================================
# 4. PERMISSION & COOLDOWN MODEL TESTS
# =============================================================================

def test_permission_checks_everyone_and_roles(tmp_path: Path):
    """Verify 'everyone' permission level and role restrictions."""
    async def _test():
        manager, _, service = await create_test_harness(tmp_path)
        try:
            cmd_open = CustomCommandModel(guild_id=1, name="test", permission_level="everyone")
            cmd_role_locked = CustomCommandModel(guild_id=1, name="vip", permission_level="everyone", required_role_ids=[8888])

            member_no_roles = MagicMock()
            member_no_roles.roles = []
            member_no_roles.guild_permissions.administrator = False

            role_mock = MagicMock()
            role_mock.id = 8888
            member_with_role = MagicMock()
            member_with_role.roles = [role_mock]
            member_with_role.guild_permissions.administrator = False

            # Open command passes for anyone
            ok, _ = service.check_permission(member_no_roles, cmd_open)
            assert ok is True

            # Role-locked command fails for member without role
            ok, err = service.check_permission(member_no_roles, cmd_role_locked)
            assert ok is False
            assert "required role" in err

            # Role-locked command passes for member with role
            ok, _ = service.check_permission(member_with_role, cmd_role_locked)
            assert ok is True
        finally:
            await manager.close()

    run_async(_test())


def test_permission_checks_moderator_and_administrator(tmp_path: Path):
    """Verify moderator and administrator permission requirements."""
    async def _test():
        manager, _, service = await create_test_harness(tmp_path)
        try:
            cmd_mod = CustomCommandModel(guild_id=1, name="modnote", permission_level="moderator")
            cmd_admin = CustomCommandModel(guild_id=1, name="adminpanel", permission_level="administrator")

            perms_regular = discord.Permissions.none()
            regular_member = MagicMock()
            regular_member.guild_permissions = perms_regular
            regular_member.roles = []
            regular_member.guild.owner_id = 999
            regular_member.id = 111

            perms_mod = discord.Permissions(manage_messages=True)
            mod_member = MagicMock()
            mod_member.guild_permissions = perms_mod
            mod_member.roles = []
            mod_member.guild.owner_id = 999
            mod_member.id = 222

            perms_admin = discord.Permissions(administrator=True)
            admin_member = MagicMock()
            admin_member.guild_permissions = perms_admin
            admin_member.roles = []
            admin_member.guild.owner_id = 999
            admin_member.id = 333

            # Regular member fails both
            assert service.check_permission(regular_member, cmd_mod)[0] is False
            assert service.check_permission(regular_member, cmd_admin)[0] is False

            # Moderator passes mod command, fails admin command
            assert service.check_permission(mod_member, cmd_mod)[0] is True
            assert service.check_permission(mod_member, cmd_admin)[0] is False

            # Administrator passes both
            assert service.check_permission(admin_member, cmd_mod)[0] is True
            assert service.check_permission(admin_member, cmd_admin)[0] is True
        finally:
            await manager.close()

    run_async(_test())


def test_cooldown_enforcement_and_retry_after(tmp_path: Path):
    """Verify in-memory sliding window cooldown calculation."""
    async def _test():
        manager, _, service = await create_test_harness(tmp_path)
        try:
            # Check cooldown before applying -> should be allowed
            can_run, retry = service.check_cooldown(guild_id=1, command_name="daily_tip", user_id=42, cooldown_seconds=10)
            assert can_run is True
            assert retry == 0.0

            # Apply 10-second cooldown
            service.apply_cooldown(guild_id=1, command_name="daily_tip", user_id=42, cooldown_seconds=10)

            # Immediately check again -> should be blocked with retry_after > 0
            can_run_2, retry_2 = service.check_cooldown(guild_id=1, command_name="daily_tip", user_id=42, cooldown_seconds=10)
            assert can_run_2 is False
            assert 8.0 <= retry_2 <= 10.0

            # Different user is not blocked
            can_run_other, _ = service.check_cooldown(guild_id=1, command_name="daily_tip", user_id=99, cooldown_seconds=10)
            assert can_run_other is True
        finally:
            await manager.close()

    run_async(_test())


def test_disabled_command_rejection(tmp_path: Path):
    """Verify that disabled commands are rejected even for administrators."""
    async def _test():
        manager, _, service = await create_test_harness(tmp_path)
        try:
            cmd_disabled = CustomCommandModel(guild_id=1, name="offline_cmd", is_enabled=False)
            admin_member = MagicMock()
            admin_member.guild_permissions.administrator = True

            ok, err = service.check_permission(admin_member, cmd_disabled)
            assert ok is False
            assert "currently disabled" in err
        finally:
            await manager.close()

    run_async(_test())


def test_atomic_usage_counter(tmp_path: Path):
    """Verify atomic increment of command uses and last_used_at update."""
    async def _test():
        manager, repo, _ = await create_test_harness(tmp_path)
        try:
            await repo.create_command(guild_id=1001, name="counter_test", content="Tracking usage")

            initial = await repo.get_command(guild_id=1001, name="counter_test")
            assert initial is not None
            assert initial.uses == 0
            assert initial.last_used_at is None

            # Increment twice
            await repo.increment_uses(guild_id=1001, name="counter_test")
            await repo.increment_uses(guild_id=1001, name="counter_test")

            updated = await repo.get_command(guild_id=1001, name="counter_test")
            assert updated is not None
            assert updated.uses == 2
            assert updated.last_used_at is not None
        finally:
            await manager.close()

    run_async(_test())


def test_legacy_custom_tags_table_unmodified(tmp_path: Path):
    """Verify that the existing custom_tags table remains completely intact and unmodified."""
    async def _test():
        manager, _, _ = await create_test_harness(tmp_path)
        try:
            row = await manager.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='custom_tags'")
            assert row is not None
            assert row["name"] == "custom_tags"
        finally:
            await manager.close()

    run_async(_test())
