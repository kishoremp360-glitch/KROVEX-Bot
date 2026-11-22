"""Regression Test Suite for Role-Based Whitelist Enforcement and Bot Owner Immunity.

Tests:
1. Direct user whitelist bypass.
2. Whitelisted role bypass.
3. Multiple roles with one matching whitelist.
4. Non-whitelisted role does not bypass.
5. Role whitelist isolation between two guilds.
6. Deleted whitelisted role handling.
7. Server owner immunity across detection and punishment paths.
8. Bot owner immunity across all punishment actions (ban, kick, timeout, quarantine, warn).
9. Normal members remain punishable when configured.
10. Unconfigured punishment remains strictly non-destructive (log-only).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.services.security_service import SecurityService


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock(spec=discord.ClientUser)
    bot.user.id = 1570428426974662718
    bot.user.name = "KROVEX"
    bot.latency = 0.020
    bot.config = MagicMock()
    bot.config.owner_ids = [999000111, "888000222"]
    bot.owner_ids = {999000111, 888000222}

    guild_settings_store = {}

    async def mock_get_settings(guild_id: int):
        if guild_id not in guild_settings_store:
            guild_settings_store[guild_id] = {
                "guild_id": guild_id,
                "enabled": 1,
                "anti_nuke": 1,
                "anti_raid": 1,
                "anti_spam": 1,
                "anti_phishing": 1,
                "anti_bot": 1,
                "anti_webhook": 1,
                "anti_mention_spam": 1,
                "mass_ban_threshold": 3,
                "mass_kick_threshold": 3,
                "channel_del_threshold": 3,
                "role_del_threshold": 3,
                "time_window_seconds": 15,
                "punishment": "none",
                "event_punishments": {},
                "account_age_threshold_hours": 24,
                "join_rate_max": 5,
                "join_rate_seconds": 10,
                "whitelist_users": [],
                "whitelist_roles": [],
                "log_channel_id": None,
            }
        return dict(guild_settings_store[guild_id])

    async def mock_update_settings(guild_id: int, **kwargs):
        settings = await mock_get_settings(guild_id)
        for k, v in kwargs.items():
            if isinstance(v, (dict, list)):
                settings[k] = json.loads(json.dumps(v))
            else:
                settings[k] = v
        guild_settings_store[guild_id] = settings

    async def mock_set_event_punishment(guild_id: int, event_name: str, punishment: str):
        settings = await mock_get_settings(guild_id)
        ep = dict(settings.get("event_punishments") or {})
        if punishment in ("not_configured", "none", "reset"):
            ep.pop(event_name, None)
        else:
            ep[event_name] = punishment.lower()
        await mock_update_settings(guild_id, event_punishments=ep)

    bot.security_repo = MagicMock()
    bot.security_repo.get_settings = AsyncMock(side_effect=mock_get_settings)
    bot.security_repo.get_or_create_settings = bot.security_repo.get_settings
    bot.security_repo.update_settings = AsyncMock(side_effect=mock_update_settings)
    bot.security_repo.set_event_punishment = AsyncMock(side_effect=mock_set_event_punishment)
    bot.security_repo.log_incident = AsyncMock()

    return bot


def _make_guild(guild_id: int = 10001, owner_id: int = 111222333):
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = f"Guild-{guild_id}"
    guild.owner_id = owner_id
    guild.ban = AsyncMock()
    guild.kick = AsyncMock()

    bot_member = MagicMock(spec=discord.Member)
    bot_member.id = 1570428426974662718
    bot_top_role = MagicMock()
    bot_top_role.position = 50
    bot_member.top_role = bot_top_role
    bot_member.guild_permissions = discord.Permissions.all()
    guild.me = bot_member

    members = {}

    def get_member(user_id):
        return members.get(user_id)

    guild.get_member = MagicMock(side_effect=get_member)
    guild._members_dict = members
    return guild


def _make_member(user_id: int, guild: discord.Guild, role_ids: list[int] = None, top_pos: int = 10):
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.name = f"User-{user_id}"
    member.guild = guild
    member.timeout = AsyncMock()
    member.add_roles = AsyncMock()
    member.send = AsyncMock()

    top_role = MagicMock()
    top_role.position = top_pos
    member.top_role = top_role

    roles = []
    for rid in (role_ids or []):
        r = MagicMock(spec=discord.Role)
        r.id = rid
        r.name = f"Role-{rid}"
        roles.append(r)
    member.roles = roles

    guild._members_dict[user_id] = member
    return member


# ─────────────────────────────────────────────────────────────────────────────
# Issue 1: Role-Based Whitelist Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_direct_user_whitelist_bypass(mock_bot):
    """Verify that a direct user ID in whitelist_users bypasses threshold evaluation."""
    service = SecurityService(mock_bot)
    guild = _make_guild(owner_id=500)

    # Actor in whitelist_users
    assert service._is_whitelisted(1001, guild, whitelist_users=[1001], whitelist_roles=[]) is True
    # Actor as string in JSON whitelist_users
    assert service._is_whitelisted(1001, guild, whitelist_users="[1001]", whitelist_roles="[]") is True
    # Non-whitelisted actor
    assert service._is_whitelisted(2002, guild, whitelist_users=[1001], whitelist_roles=[]) is False


def test_whitelisted_role_bypass(mock_bot):
    """Verify that a member holding a whitelisted role ID bypasses threshold checks."""
    service = SecurityService(mock_bot)
    guild = _make_guild(owner_id=500)
    member = _make_member(user_id=777, guild=guild, role_ids=[9001])

    # Member's role 9001 is whitelisted
    assert service._is_whitelisted(777, guild, whitelist_users=[], whitelist_roles=[9001], member=member) is True
    # Check with JSON string representation
    assert service._is_whitelisted(777, guild, whitelist_users="[]", whitelist_roles="[9001]") is True


def test_multiple_roles_with_one_matching_whitelist(mock_bot):
    """Verify that having multiple roles where only one matches whitelist correctly grants bypass."""
    service = SecurityService(mock_bot)
    guild = _make_guild(owner_id=500)
    member = _make_member(user_id=888, guild=guild, role_ids=[101, 102, 103])

    # Only 102 is whitelisted
    assert service._is_whitelisted(888, guild, whitelist_users=[], whitelist_roles=[102], member=member) is True


def test_non_whitelisted_role_does_not_bypass(mock_bot):
    """Verify that holding roles that are not whitelisted does NOT grant bypass."""
    service = SecurityService(mock_bot)
    guild = _make_guild(owner_id=500)
    member = _make_member(user_id=999, guild=guild, role_ids=[201, 202])

    # Whitelist contains 9999, not 201 or 202
    assert service._is_whitelisted(999, guild, whitelist_users=[], whitelist_roles=[9999], member=member) is False


def test_role_whitelist_guild_isolation(mock_bot):
    """Verify that a role whitelisted in Guild A does NOT grant bypass in Guild B."""
    service = SecurityService(mock_bot)
    guild_a = _make_guild(guild_id=1111)
    guild_b = _make_guild(guild_id=2222)

    member_b = _make_member(user_id=4004, guild=guild_b, role_ids=[7007])

    # Role 7007 is whitelisted in Guild A, but NOT in Guild B
    guild_a_roles = [7007]
    guild_b_roles = [8008]

    # In Guild A, role 7007 would bypass
    member_a = _make_member(user_id=4004, guild=guild_a, role_ids=[7007])
    assert service._is_whitelisted(4004, guild_a, whitelist_roles=guild_a_roles, member=member_a) is True

    # In Guild B, role 7007 does NOT bypass
    assert service._is_whitelisted(4004, guild_b, whitelist_roles=guild_b_roles, member=member_b) is False


def test_deleted_or_removed_whitelisted_role(mock_bot):
    """Verify that if a whitelisted role was removed from a member or deleted, bypass is denied."""
    service = SecurityService(mock_bot)
    guild = _make_guild(owner_id=500)

    # Member currently has no roles (or role was deleted/stripped)
    member = _make_member(user_id=3003, guild=guild, role_ids=[])

    # Whitelist still has stale role ID 5555
    assert service._is_whitelisted(3003, guild, whitelist_users=[], whitelist_roles=[5555], member=member) is False


def test_malformed_whitelist_db_values_handled_safely(mock_bot):
    """Verify that corrupted or malformed database values do not crash whitelist checks."""
    service = SecurityService(mock_bot)
    guild = _make_guild(owner_id=500)
    member = _make_member(user_id=123, guild=guild, role_ids=[456])

    # Corrupt JSON strings
    assert service._is_whitelisted(123, guild, whitelist_users="{invalid json", whitelist_roles="not json", member=member) is False
    # Mixed data types
    assert service._is_whitelisted(123, guild, whitelist_users=[None, "abc"], whitelist_roles=[None, "def"], member=member) is False


# ─────────────────────────────────────────────────────────────────────────────
# Issue 2: Bot Owner & Server Sovereign Immunity Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_server_owner_immunity_in_whitelist_check(mock_bot):
    """Verify that the Server Sovereign (guild.owner_id) is always immune regardless of whitelist."""
    service = SecurityService(mock_bot)
    guild = _make_guild(owner_id=123456789)

    # Empty whitelist, but actor is owner
    assert service._is_whitelisted(123456789, guild, whitelist_users=[], whitelist_roles=[]) is True


def test_bot_owner_immunity_in_whitelist_check(mock_bot):
    """Verify that Bot Owners (configured in bot.config.owner_ids) are immune regardless of whitelist."""
    service = SecurityService(mock_bot)
    guild = _make_guild(owner_id=500)

    # Bot owners from mock_bot fixture: 999000111 and "888000222"
    assert service._is_whitelisted(999000111, guild, whitelist_users=[], whitelist_roles=[]) is True
    assert service._is_whitelisted(888000222, guild, whitelist_users=[], whitelist_roles=[]) is True


@pytest.mark.asyncio
async def test_server_owner_immunity_in_punishment_execution(mock_bot):
    """Verify server owner cannot be banned, kicked, timed out, or quarantined by automated security."""
    service = SecurityService(mock_bot)
    guild = _make_guild(owner_id=111222)
    owner = _make_member(user_id=111222, guild=guild, top_pos=10)

    for punishment_type in ["ban", "kick", "timeout", "quarantine", "warn"]:
        await service._apply_punishment(guild, owner, punishment_type, "Test Trigger")

    # Assert zero moderation API calls on the server sovereign
    guild.ban.assert_not_called()
    guild.kick.assert_not_called()
    owner.timeout.assert_not_called()
    owner.add_roles.assert_not_called()
    owner.send.assert_not_called()


@pytest.mark.asyncio
async def test_bot_owner_immunity_in_punishment_execution(mock_bot):
    """Verify bot owners cannot be banned, kicked, timed out, or quarantined by automated security."""
    service = SecurityService(mock_bot)
    guild = _make_guild(owner_id=500)
    bot_owner_member = _make_member(user_id=999000111, guild=guild, top_pos=10)

    for punishment_type in ["ban", "kick", "timeout", "quarantine", "warn"]:
        await service._apply_punishment(guild, bot_owner_member, punishment_type, "Test Trigger")

    # Assert zero moderation API calls on the bot owner
    guild.ban.assert_not_called()
    guild.kick.assert_not_called()
    bot_owner_member.timeout.assert_not_called()
    bot_owner_member.add_roles.assert_not_called()
    bot_owner_member.send.assert_not_called()


@pytest.mark.asyncio
async def test_normal_member_punished_when_configured(mock_bot):
    """Verify that a regular offender without whitelist or immunity is properly punished when configured."""
    service = SecurityService(mock_bot)
    guild = _make_guild(owner_id=500)
    offender = _make_member(user_id=6006, guild=guild, top_pos=10)

    await service._apply_punishment(guild, offender, "kick", "Mass kick threshold exceeded")
    guild.kick.assert_called_once_with(offender, reason="KROVEX Security: Mass kick threshold exceeded")


@pytest.mark.asyncio
async def test_unconfigured_punishment_remains_strictly_log_only(mock_bot):
    """Verify that unconfigured punishment (not_configured/log_only/none) takes no destructive action."""
    service = SecurityService(mock_bot)
    guild = _make_guild(owner_id=500)
    offender = _make_member(user_id=7007, guild=guild, top_pos=10)

    for unconfigured_val in ["not_configured", "log_only", "none", None, ""]:
        await service._apply_punishment(guild, offender, unconfigured_val, "Unconfigured event trigger")

    # Assert zero moderation API calls
    guild.ban.assert_not_called()
    guild.kick.assert_not_called()
    offender.timeout.assert_not_called()
    offender.add_roles.assert_not_called()
