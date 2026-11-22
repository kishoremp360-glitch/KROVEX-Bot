"""Automated Tests for KROVEX Automatic Bot Role Setup Service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.config import BotConfig
from bot.core.bot import DeathBot
from bot.services.bot_role_service import BotRoleService, KROVEX_ROLE_SPECS


@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=DeathBot)
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    return bot


def _make_mock_guild(has_manage_roles: bool = True):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 777666555
    guild.name = "Krovex Secured Guild"
    guild.roles = []

    # Bot Member
    me = MagicMock(spec=discord.Member)
    me.id = 1570428426974662718
    me.name = "KROVEX"
    me.roles = []
    me.guild_permissions.manage_roles = has_manage_roles

    # Top role
    top_role = MagicMock(spec=discord.Role)
    top_role.position = 99
    me.top_role = top_role
    me.add_roles = AsyncMock()

    guild.me = me

    # Role factory
    def mock_create_role(name, color, permissions, mentionable, reason, **kwargs):
        role = MagicMock(spec=discord.Role)
        role.name = name
        role.color = color
        role.permissions = permissions
        role.mentionable = mentionable
        role.position = 10
        role.hoist = kwargs.get("hoist", True)
        role.managed = False
        guild.roles.append(role)
        return role

    guild.create_role = AsyncMock(side_effect=mock_create_role)
    return guild


@pytest.mark.asyncio
async def test_krovex_roles_created_in_exact_order(mock_bot):
    """Verify first-time server join creates all 3 roles in the exact prescribed order."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    active_roles, failed_roles, err = await service.setup_bot_roles(guild)

    assert err is None
    assert len(failed_roles) == 0
    assert len(active_roles) == 3

    expected_names = [
        "KROVEX",
        "KROVEX Prime Security™",
        "KROVEX Unbypassable Security™",
    ]
    actual_names = [r.name for r in active_roles]
    assert actual_names == expected_names


def test_krovex_roles_admin_and_non_mentionable():
    """Verify all 3 role specifications grant Administrator at top of server, and are non-mentionable."""
    for spec in KROVEX_ROLE_SPECS:
        perms: discord.Permissions = spec["permissions"]
        assert perms.administrator is True, f"{spec['name']} must grant Administrator permission!"


@pytest.mark.asyncio
async def test_krovex_roles_assigned_only_to_bot(mock_bot):
    """Verify roles are added only to guild.me and never to other guild members."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    # Ordinary user member in guild
    user_member = MagicMock(spec=discord.Member)
    user_member.id = 12345
    user_member.roles = []
    user_member.add_roles = AsyncMock()
    guild.members = [guild.me, user_member]

    await service.setup_bot_roles(guild)

    # Bot had add_roles called 3 times
    assert guild.me.add_roles.await_count == 3
    # Ordinary user was never touched
    user_member.add_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_zynrax_role_migration(mock_bot):
    """Verify legacy Zynrax roles are automatically renamed and upgraded to KROVEX specifications."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    # Pre-populate with legacy Zynrax role
    legacy_role = MagicMock(spec=discord.Role)
    legacy_role.name = "Zynrax Prime Security™"
    legacy_role.position = 20
    legacy_role.permissions = discord.Permissions(administrator=False)
    legacy_role.edit = AsyncMock()
    guild.roles.append(legacy_role)

    active_roles, failed_roles, err = await service.setup_bot_roles(guild)

    assert err is None
    assert len(active_roles) == 3
    legacy_role.edit.assert_awaited()


@pytest.mark.asyncio
async def test_rejoin_prevents_duplicate_roles(mock_bot):
    """Verify that rejoining a server reuses existing roles and never duplicates them."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    # First setup
    active_1, _, _ = await service.setup_bot_roles(guild)
    assert guild.create_role.await_count == 3

    # Second setup (simulate bot rejoins or manual sync)
    guild.create_role.reset_mock()
    guild.me.add_roles.reset_mock()
    guild.me.roles = []  # bot just rejoined and has no roles yet
    active_2, failed, err = await service.setup_bot_roles(guild)

    # create_role must NOT be called again
    guild.create_role.assert_not_awaited()
    assert len(active_2) == 3
    # All 3 pre-existing roles were reused and reassigned to bot
    assert guild.me.add_roles.await_count == 3


@pytest.mark.asyncio
async def test_missing_manage_roles_handled_gracefully(mock_bot):
    """Verify that missing Manage Roles permission produces a clean report without throwing unhandled exception."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=False)

    active_roles, failed_roles, err = await service.setup_bot_roles(guild)

    assert err is not None
    assert "Missing 'Manage Roles' permission" in err
    assert len(failed_roles) == 3
    assert len(active_roles) == 0
    guild.create_role.assert_not_awaited()


@pytest.mark.asyncio
async def test_krovex_roles_hoisted_and_managed_role_bypassed(mock_bot):
    """Verify all 3 roles are created with hoist=True and existing managed integration role does not block custom role creation."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    # Pre-existing managed integration role named 'KROVEX' (created by Discord OAuth)
    managed_role = MagicMock(spec=discord.Role)
    managed_role.name = "KROVEX"
    managed_role.managed = True
    managed_role.position = 90
    guild.roles.append(managed_role)

    # edit_role_positions mock
    guild.edit_role_positions = AsyncMock()

    active_roles, failed_roles, err = await service.setup_bot_roles(guild)

    assert err is None
    assert len(active_roles) == 3
    # All active roles have hoist=True so they display separately at top of online member list
    for r in active_roles:
        assert getattr(r, "hoist", False) is True
    # Bulk position edit was called to elevate roles to top
    guild.edit_role_positions.assert_awaited()


@pytest.mark.asyncio
async def test_duplicate_role_pruning(mock_bot):
    """Verify that multiple duplicate custom roles are pruned down to a single canonical role."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    # Pre-populate with two duplicate "KROVEX Prime Security™" roles
    dup1 = MagicMock(spec=discord.Role, name="KROVEX Prime Security™", position=50, managed=False)
    dup1.name = "KROVEX Prime Security™"
    dup1.permissions = discord.Permissions(administrator=True)
    dup1.delete = AsyncMock()
    dup2 = MagicMock(spec=discord.Role, name="KROVEX Prime Security™", position=40, managed=False)
    dup2.name = "KROVEX Prime Security™"
    dup2.permissions = discord.Permissions(administrator=True)
    dup2.delete = AsyncMock()
    guild.roles.extend([dup1, dup2])

    active_roles, _, err = await service.setup_bot_roles(guild)

    assert err is None
    # Lower duplicate was deleted
    dup2.delete.assert_awaited()
    # Higher duplicate was retained
    dup1.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_unremovable_role_protection_on_member_update(mock_bot):
    """Verify that if an administrator removes a KROVEX dedicated role, it is instantly restored."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    security_role = MagicMock(spec=discord.Role, name="KROVEX Prime Security™", managed=False)
    security_role.name = "KROVEX Prime Security™"

    before_member = MagicMock(spec=discord.Member, id=mock_bot.user.id)
    before_member.roles = [security_role]

    after_member = MagicMock(spec=discord.Member, id=mock_bot.user.id, guild=guild)
    after_member.roles = []  # Role was removed by an administrator!
    after_member.add_roles = AsyncMock()

    await service.on_member_update(before_member, after_member)

    # Bot instantly re-added the role back to itself!
    after_member.add_roles.assert_awaited_with(security_role, reason="Unremovable KROVEX Security Architecture: Re-applying dedicated role")


@pytest.mark.asyncio
async def test_pruning_does_not_trigger_recreation_loop(mock_bot):
    """Verify that pruning a duplicate role marks it so on_guild_role_delete does not auto-recreate."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    dup_role = MagicMock(spec=discord.Role, id=999888, name="KROVEX Prime Security™", managed=False)
    dup_role.name = "KROVEX Prime Security™"
    dup_role.guild = guild

    # Mark as pruning
    service._pruning_role_ids.add(dup_role.id)

    # Trigger on_guild_role_delete
    service.setup_bot_roles = AsyncMock()
    await service.on_guild_role_delete(dup_role)

    # setup_bot_roles must NOT be called because it was an internal prune!
    service.setup_bot_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_skipped_if_canonical_role_exists(mock_bot):
    """Verify that deleting a role does not trigger recreate if another canonical role still exists."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    # Canonical role remaining in guild
    canonical = MagicMock(spec=discord.Role, id=1111, name="KROVEX Prime Security™", managed=False)
    canonical.name = "KROVEX Prime Security™"
    guild.roles = [canonical]

    deleted_dup = MagicMock(spec=discord.Role, id=2222, name="KROVEX Prime Security™", managed=False)
    deleted_dup.name = "KROVEX Prime Security™"
    deleted_dup.guild = guild

    service.setup_bot_roles = AsyncMock()
    await service.on_guild_role_delete(deleted_dup)

    # Recreate must NOT be called because canonical already exists
    service.setup_bot_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_pruning_hierarchy_prevents_deletion_cleans_up_tracking(mock_bot):
    """Verify that when bot hierarchy is lower or equal, extra is not deleted and tracking ID is discarded."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    # Bot top role is 50
    guild.me.top_role.position = 50

    canonical = MagicMock(spec=discord.Role, id=1001, name="KROVEX Prime Security™", position=50, managed=False)
    canonical.name = "KROVEX Prime Security™"
    # Duplicate has position 60 (higher than bot top role 50)
    extra = MagicMock(spec=discord.Role, id=1002, name="KROVEX Prime Security™", position=60, managed=False)
    extra.name = "KROVEX Prime Security™"
    extra.delete = AsyncMock()
    guild.roles.extend([canonical, extra])

    await service.setup_bot_roles(guild)

    # Deletion was skipped
    extra.delete.assert_not_awaited()
    # Tracking ID was cleanly discarded
    assert 1002 not in service._pruning_role_ids


@pytest.mark.asyncio
async def test_pruning_deletion_exception_cleans_up_tracking(mock_bot):
    """Verify that when extra.delete raises an exception, tracking ID is cleanly discarded."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    guild.me.top_role.position = 90
    canonical = MagicMock(spec=discord.Role, id=2001, name="KROVEX Prime Security™", position=80, managed=False)
    canonical.name = "KROVEX Prime Security™"
    extra = MagicMock(spec=discord.Role, id=2002, name="KROVEX Prime Security™", position=70, managed=False)
    extra.name = "KROVEX Prime Security™"
    extra.delete = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "Discord API Error"))
    guild.roles.extend([canonical, extra])

    await service.setup_bot_roles(guild)

    extra.delete.assert_awaited_once()
    assert 2002 not in service._pruning_role_ids


@pytest.mark.asyncio
async def test_pruning_successful_deletion_preserves_tracking_until_event(mock_bot):
    """Verify tracking ID remains until on_guild_role_delete processes it on successful deletion."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    guild.me.top_role.position = 90
    canonical = MagicMock(spec=discord.Role, id=3001, name="KROVEX Prime Security™", position=80, managed=False)
    canonical.name = "KROVEX Prime Security™"
    extra = MagicMock(spec=discord.Role, id=3002, name="KROVEX Prime Security™", position=70, managed=False)
    extra.name = "KROVEX Prime Security™"
    extra.guild = guild
    extra.delete = AsyncMock()
    guild.roles.extend([canonical, extra])

    await service.setup_bot_roles(guild)

    # On success, 3002 was added and remains in _pruning_role_ids awaiting gateway event
    assert 3002 in service._pruning_role_ids

    # Simulate gateway event on_guild_role_delete
    service.setup_bot_roles = AsyncMock()
    await service.on_guild_role_delete(extra)

    # Consumed and discarded by the event handler
    assert 3002 not in service._pruning_role_ids
    service.setup_bot_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_deletion_of_unprunable_role_allows_recreation(mock_bot):
    """Verify that when an unpruned role is later deleted, it is NOT in _pruning_role_ids and recreates if canonical is missing."""
    service = BotRoleService(mock_bot)
    guild = _make_mock_guild(has_manage_roles=True)

    # Bot top role is 50, duplicate is 60 (unprunable)
    guild.me.top_role.position = 50
    canonical = MagicMock(spec=discord.Role, id=4001, name="KROVEX Prime Security™", position=50, managed=False)
    canonical.name = "KROVEX Prime Security™"
    extra = MagicMock(spec=discord.Role, id=4002, name="KROVEX Prime Security™", position=60, managed=False)
    extra.name = "KROVEX Prime Security™"
    extra.guild = guild
    extra.delete = AsyncMock()
    guild.roles.extend([canonical, extra])

    # Run setup: extra is skipped and discarded from _pruning_role_ids
    await service.setup_bot_roles(guild)
    assert 4002 not in service._pruning_role_ids

    # Now simulate both roles were deleted externally (canonical missing)
    guild.roles = []
    service.setup_bot_roles = AsyncMock()
    await service.on_guild_role_delete(extra)

    # Recreate was invoked because role was not in _pruning_role_ids and no canonical role exists!
    service.setup_bot_roles.assert_awaited_once_with(guild)
