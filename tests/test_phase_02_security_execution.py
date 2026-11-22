"""Phase 2: Security & Anti-Nuke Execution Test Suite for KROVEX Master Plan.

Verifies:
1. Anti-nuke trigger on channel deletion threshold.
2. Anti-nuke trigger on role deletion threshold.
3. Anti-nuke trigger on ban threshold.
4. Anti-nuke trigger on kick threshold.
5. Anti-nuke trigger on unauthorized bot addition.
6. Anti-nuke trigger on webhook creation and auto-deletion.
7. Whitelisted user and server owner bypass.
8. Non-whitelisted admin triggered and punished.
9. Quarantine action execution and channel lockdown.
10. Recovery action after trigger (lockdown, unlockdown, securityreset).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.services.security_service import SecurityService, QUARANTINE_ROLE_NAME
from bot.cogs.security.cog import Security
from bot.core.context import UnifiedContext


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock(spec=discord.ClientUser)
    bot.user.id = 1570428426974662718
    bot.user.name = "KROVEX"

    bot.security_repo = MagicMock()
    bot.security_repo.get_or_create_settings = AsyncMock(return_value={
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
        "channel_del_threshold": 2,
        "role_del_threshold": 2,
        "time_window_seconds": 15,
        "punishment": "quarantine",
        "account_age_threshold_hours": 24,
        "join_rate_max": 5,
        "join_rate_seconds": 10,
        "whitelist_users": [123456],
        "whitelist_roles": [],
        "log_channel_id": 999888777,
    })
    bot.security_repo.get_settings = bot.security_repo.get_or_create_settings
    bot.security_repo.update_settings = AsyncMock()
    bot.security_repo.log_incident = AsyncMock()
    bot.security_repo.log_security_event = AsyncMock()
    bot.security_repo.get_recent_incidents = AsyncMock(return_value=[])
    bot.security_repo.get_trusted_users = AsyncMock(return_value=[{"user_id": 123456, "added_by": 999}])
    bot.security_repo.is_trusted = AsyncMock(side_effect=lambda g, u: u == 123456)
    bot.security_repo.add_trusted_user = AsyncMock()
    bot.security_repo.remove_trusted_user = AsyncMock(return_value=True)

    bot.db = MagicMock()
    bot.db.fetchone = AsyncMock()
    bot.db.fetchall = AsyncMock(return_value=[])
    bot.db.execute = AsyncMock()
    return bot


def _make_mock_guild(owner_id: int = 111222333):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 555666777
    guild.name = "Security Test Citadel"
    guild.owner_id = owner_id
    guild.roles = []
    guild.channels = []

    # Mock audit log generator
    def mock_audit_logs(limit=1, action=None):
        class AsyncAuditIterator:
            def __init__(self, entries):
                self.entries = list(entries)
            def __aiter__(self):
                return self
            async def __anext__(self):
                if not self.entries:
                    raise StopAsyncIteration
                return self.entries.pop(0)

        entry = MagicMock()
        entry.user = MagicMock(spec=discord.User)
        entry.user.id = 888999111  # rogue actor id
        entry.target = MagicMock()
        entry.target.id = 2000  # matches kick target id
        return AsyncAuditIterator([entry])

    guild.audit_logs = mock_audit_logs
    guild.ban = AsyncMock()
    guild.kick = AsyncMock()
    guild.create_role = AsyncMock()

    # Member lookup
    rogue_member = MagicMock(spec=discord.Member)
    rogue_member.id = 888999111
    rogue_member.name = "RogueAdmin"
    rogue_member.roles = []
    rogue_member.add_roles = AsyncMock()
    rogue_member.timeout = AsyncMock()

    def get_member_mock(mid):
        if mid == 888999111:
            return rogue_member
        return None

    guild.get_member = get_member_mock

    # Log channel
    log_ch = MagicMock(spec=discord.TextChannel)
    log_ch.id = 999888777
    log_ch.send = AsyncMock()

    def get_channel_mock(cid):
        if cid == 999888777:
            return log_ch
        return None

    guild.get_channel = get_channel_mock
    return guild


# ==============================================================================
# P2-TC01: Channel Deletion Threshold Trigger
# ==============================================================================
@pytest.mark.asyncio
async def test_p2_tc01_channel_deletion_threshold(mock_bot):
    """Verify anti-nuke triggers punishment when channel deletion threshold is exceeded."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild()

    channel1 = MagicMock(spec=discord.TextChannel, guild=guild, name="general")
    channel2 = MagicMock(spec=discord.TextChannel, guild=guild, name="memes")

    # 1st channel delete (threshold is 2)
    await service.on_guild_channel_delete(channel1)
    mock_bot.security_repo.log_incident.assert_not_awaited()

    # 2nd channel delete (reaches threshold 2)
    await service.on_guild_channel_delete(channel2)
    mock_bot.security_repo.log_incident.assert_awaited_once()

    args = mock_bot.security_repo.log_incident.call_args[0]
    assert args[0] == guild.id
    assert args[1] == 888999111  # rogue actor
    assert args[2] == "channel_delete"
    assert args[4] == "quarantine"


# ==============================================================================
# P2-TC02: Role Deletion Threshold Trigger
# ==============================================================================
@pytest.mark.asyncio
async def test_p2_tc02_role_deletion_threshold(mock_bot):
    """Verify anti-nuke triggers punishment when role deletion threshold is reached."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild()

    role1 = MagicMock(spec=discord.Role, guild=guild, name="VIP")
    role2 = MagicMock(spec=discord.Role, guild=guild, name="Member")

    await service.on_guild_role_delete(role1)
    assert mock_bot.security_repo.log_incident.call_count == 0

    await service.on_guild_role_delete(role2)
    assert mock_bot.security_repo.log_incident.call_count == 1
    args = mock_bot.security_repo.log_incident.call_args[0]
    assert args[2] == "role_delete"


# ==============================================================================
# P2-TC03: Ban Threshold Trigger
# ==============================================================================
@pytest.mark.asyncio
async def test_p2_tc03_ban_threshold_trigger(mock_bot):
    """Verify mass ban threshold triggers anti-nuke punishment."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild()

    # mass_ban_threshold = 3
    for i in range(3):
        victim = MagicMock(spec=discord.User, id=1000 + i)
        await service.on_member_ban(guild, victim)

    assert mock_bot.security_repo.log_incident.call_count == 1
    args = mock_bot.security_repo.log_incident.call_args[0]
    assert args[2] == "mass_ban"


# ==============================================================================
# P2-TC04: Kick Threshold Trigger
# ==============================================================================
@pytest.mark.asyncio
async def test_p2_tc04_kick_threshold_trigger(mock_bot):
    """Verify mass kick threshold triggers anti-nuke punishment."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild()

    # mass_kick_threshold = 3
    for _ in range(3):
        victim_member = MagicMock(spec=discord.Member, guild=guild, id=2000)
        await service.on_member_remove(victim_member)

    assert mock_bot.security_repo.log_incident.call_count == 1
    args = mock_bot.security_repo.log_incident.call_args[0]
    assert args[2] == "mass_kick"


# ==============================================================================
# P2-TC05: Unauthorized Bot Addition Trigger
# ==============================================================================
@pytest.mark.asyncio
async def test_p2_tc05_unauthorized_bot_add(mock_bot):
    """Verify adding an unauthorized bot immediately triggers punishment against the adder."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild()

    rogue_bot = MagicMock(spec=discord.Member, guild=guild, id=777888999)
    rogue_bot.bot = True
    rogue_bot.created_at = datetime.now(timezone.utc) - timedelta(days=30)

    await service.on_member_join(rogue_bot)

    mock_bot.security_repo.log_incident.assert_awaited()
    args = mock_bot.security_repo.log_incident.call_args[0]
    assert args[1] == 888999111  # adder from audit log
    assert args[2] == "bot_add"


# ==============================================================================
# P2-TC06: Webhook Creation Trigger & Auto-Deletion
# ==============================================================================
@pytest.mark.asyncio
async def test_p2_tc06_webhook_creation_trigger_and_autodelete(mock_bot):
    """Verify rogue webhook creation triggers anti-nuke and deletes the unauthorized webhook."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild()

    channel = MagicMock(spec=discord.TextChannel, guild=guild, name="announcements")

    # Mock audit log entry with webhook target
    webhook_mock = MagicMock()
    webhook_mock.delete = AsyncMock()

    def mock_webhook_audit_logs(limit=1, action=None):
        class AsyncAuditIterator:
            def __init__(self):
                self.done = False
            def __aiter__(self):
                return self
            async def __anext__(self):
                if self.done:
                    raise StopAsyncIteration
                self.done = True
                entry = MagicMock()
                entry.user = MagicMock(spec=discord.User, id=888999111)
                entry.target = webhook_mock
                return entry
        return AsyncAuditIterator()

    guild.audit_logs = mock_webhook_audit_logs

    await service.on_webhooks_update(channel)

    # Actor punished and incident logged
    mock_bot.security_repo.log_incident.assert_awaited()
    args = mock_bot.security_repo.log_incident.call_args[0]
    assert args[2] == "webhook_create"

    # Rogue webhook was automatically deleted
    webhook_mock.delete.assert_awaited_once()


# ==============================================================================
# P2-TC07: Whitelisted User & Server Owner Bypass
# ==============================================================================
@pytest.mark.asyncio
async def test_p2_tc07_whitelisted_and_owner_bypass(mock_bot):
    """Verify server owner and whitelisted users bypass anti-nuke thresholds completely."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild(owner_id=111222333)

    # Server owner is always whitelisted
    assert service._is_whitelisted(111222333, guild, "[]") is True

    # User in whitelist_users is whitelisted
    assert service._is_whitelisted(123456, guild, "[123456]") is True

    # Unlisted user is NOT whitelisted
    assert service._is_whitelisted(888999111, guild, "[123456]") is False

    # Simulate 5 bans by server owner -> zero incidents logged
    def owner_audit_logs(limit=1, action=None):
        class AsyncAuditIterator:
            def __aiter__(self):
                return self
            async def __anext__(self):
                entry = MagicMock()
                entry.user = MagicMock(spec=discord.User, id=111222333)
                return entry
        return AsyncAuditIterator()

    guild.audit_logs = owner_audit_logs
    for i in range(5):
        await service.on_member_ban(guild, MagicMock(spec=discord.User, id=3000 + i))

    mock_bot.security_repo.log_incident.assert_not_awaited()


# ==============================================================================
# P2-TC08: Non-Whitelisted Admin Triggered & Punished
# ==============================================================================
@pytest.mark.asyncio
async def test_p2_tc08_non_whitelisted_admin_punished(mock_bot):
    """Verify an admin who is not on the whitelist gets tracked and punished on threshold breach."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild()

    channel1 = MagicMock(spec=discord.TextChannel, guild=guild, name="ch1")
    channel2 = MagicMock(spec=discord.TextChannel, guild=guild, name="ch2")

    await service.on_guild_channel_delete(channel1)
    await service.on_guild_channel_delete(channel2)

    # Member was fetched and quarantined
    rogue = guild.get_member(888999111)
    assert rogue is not None
    # Add roles was called for quarantine
    rogue.add_roles.assert_awaited()


# ==============================================================================
# P2-TC09: Quarantine Action Execution & Permissions
# ==============================================================================
@pytest.mark.asyncio
async def test_p2_tc09_quarantine_action_execution(mock_bot):
    """Verify quarantine role is created with zero permissions and channel overrides are locked."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild()

    channel = MagicMock(spec=discord.TextChannel, guild=guild)
    channel.set_permissions = AsyncMock()
    guild.channels = [channel]

    created_role = MagicMock(spec=discord.Role, name=QUARANTINE_ROLE_NAME)
    guild.create_role = AsyncMock(return_value=created_role)

    role = await service._get_quarantine_role(guild)
    assert role == created_role

    # Verify channel permissions locked for quarantine role
    channel.set_permissions.assert_awaited_with(
        created_role,
        send_messages=False,
        view_channel=False,
        reason="Death Bot: Quarantine lock",
    )


# ==============================================================================
# P2-TC09-B: Alternate Punishment Modes (Ban, Kick, Timeout)
# ==============================================================================
@pytest.mark.asyncio
async def test_p2_tc09_alternate_punishment_modes(mock_bot):
    """Verify punishment dispatcher handles ban, kick, and timeout properly."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild()
    rogue = guild.get_member(888999111)

    # 1. Ban
    await service._apply_punishment(guild, rogue, "ban", "Mass nuke")
    guild.ban.assert_awaited_with(rogue, reason="KROVEX Security: Mass nuke", delete_message_days=0)

    # 2. Kick
    await service._apply_punishment(guild, rogue, "kick", "Spam raid")
    guild.kick.assert_awaited_with(rogue, reason="KROVEX Security: Spam raid")

    # 3. Timeout
    await service._apply_punishment(guild, rogue, "timeout", "Rate limit")
    rogue.timeout.assert_awaited()


# ==============================================================================
# P2-TC10: Recovery Actions (Lockdown, Unlockdown, Security Reset)
# ==============================================================================
@pytest.mark.asyncio
async def test_p2_tc10_recovery_actions(mock_bot):
    """Verify lockdown, unlockdown, and securityreset restore guild equilibrium."""
    import importlib
    sec_mod = importlib.import_module("bot.cogs.security.cog")
    SecurityClass = getattr(sec_mod, "Security", Security)
    cog = SecurityClass(mock_bot)

    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = _make_mock_guild()
    ctx.is_interaction = False
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = ctx.guild.owner_id
    ctx.author.guild_permissions.administrator = True
    ctx.send = AsyncMock()
    ctx.send_success = AsyncMock()
    ctx.send_error = AsyncMock()
    ctx.defer = AsyncMock()

    mock_msg = MagicMock()
    mock_msg.edit = AsyncMock()
    ctx.prefix_ctx = MagicMock()
    ctx.prefix_ctx.send = AsyncMock(return_value=mock_msg)

    # Target channel for lockdown
    text_ch = MagicMock(spec=discord.TextChannel)
    text_ch.name = "chat"
    text_ch.overwrites_for = MagicMock(return_value=discord.PermissionOverwrite())
    text_ch.set_permissions = AsyncMock()
    ctx.guild.text_channels = [text_ch]
    ctx.guild.default_role = MagicMock(spec=discord.Role)

    # 1. Lockdown
    await cog._execute_lockdown(ctx, reason="Emergency Raid in progress")
    text_ch.set_permissions.assert_awaited()
    ctx.send_success.assert_awaited()

    # 2. Unlockdown
    ctx.send_success.reset_mock()
    text_ch.set_permissions.reset_mock()
    await cog._execute_unlockdown(ctx, reason="Raid resolved")
    text_ch.set_permissions.assert_awaited()
    ctx.send_success.assert_awaited()

    # 3. Security Reset (with confirm view simulation)
    ctx.send_success.reset_mock()

    mock_view_instance = MagicMock()
    mock_view_instance.confirmed = True
    mock_view_instance.wait = AsyncMock(return_value=False)

    with patch.object(sec_mod, "ConfirmView", return_value=mock_view_instance):
        await cog._execute_securityreset(ctx)

    # Verifies database reset calls were executed
    mock_bot.db.execute.assert_any_await(
        "DELETE FROM security_settings WHERE guild_id=?", (ctx.guild.id,)
    )
    mock_bot.db.execute.assert_any_await(
        "INSERT OR IGNORE INTO security_settings (guild_id) VALUES (?)", (ctx.guild.id,)
    )
    mock_bot.db.execute.assert_any_await(
        "DELETE FROM trusted_users WHERE guild_id=?", (ctx.guild.id,)
    )
    mock_msg.edit.assert_awaited()
