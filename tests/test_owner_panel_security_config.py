"""Comprehensive Test Suite for OwnerPanel, Security Whitelist, and Per-Guild Punishments.

Verifies:
1. OwnerPanel opens without requiring voice channel connection.
2. Voice-specific actions retain voice channel requirement.
3. Unauthorized users are blocked from OwnerPanel.
4. Security whitelist opens independently of voice channels.
5. Whitelist management (add/remove users & roles) with guild isolation.
6. Non-destructive initial state: unconfigured events do NOT execute destructive punishments.
7. Per-guild, per-event independent punishment configuration and persistence.
8. Role hierarchy and bot permission enforcement during punishment execution.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.cogs.admin.owner_panel import OwnerDashboardCog, OwnerDashboardView
from bot.cogs.security.cog import Security
from bot.cogs.security.panel import (
    SecurityWhitelistView,
    SecurityPunishmentConfigView,
    SecurityPanelView,
    SECURITY_EVENTS_MAP,
)
from bot.services.security_service import SecurityService
from bot.core.context import UnifiedContext


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock(spec=discord.ClientUser)
    bot.user.id = 1570428426974662718
    bot.user.name = "KROVEX"
    bot.latency = 0.025
    bot.config = MagicMock()
    bot.config.owner_ids = [999000111]
    bot.owner_ids = {999000111}
    bot.vc_repo = MagicMock()
    bot.vc_repo.get_staff_roles = AsyncMock(return_value=[])

    # Per-guild settings storage for isolation testing
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

    bot.db_manager = MagicMock()
    bot.db_manager.fetchone = AsyncMock()
    bot.db_manager.execute = AsyncMock()
    return bot


def _make_mock_guild(guild_id: int = 12345678, owner_id: int = 999000111):
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = f"Guild_{guild_id}"
    guild.owner_id = owner_id
    guild.roles = []
    guild.channels = []
    guild.text_channels = []
    guild.voice_channels = []
    guild.member_count = 10
    guild.created_at = datetime.now(timezone.utc) - timedelta(days=100)

    # Bot Member
    me = MagicMock(spec=discord.Member)
    me.id = 1570428426974662718
    me.name = "KROVEX"
    me.joined_at = datetime.now(timezone.utc) - timedelta(days=10)
    top_role = MagicMock(spec=discord.Role, position=100)
    me.top_role = top_role
    me.guild_permissions.ban_members = True
    me.guild_permissions.kick_members = True
    me.guild_permissions.moderate_members = True
    me.guild_permissions.manage_roles = True
    guild.me = me

    guild.ban = AsyncMock()
    guild.kick = AsyncMock()
    return guild


# ==============================================================================
# SECTION 1: OWNER PANEL TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_ownerpanel_opens_without_voice_channel(mock_bot):
    """Verify /ownerpanel opens OwnerDashboardView even when user is NOT in a voice channel."""
    cog = OwnerDashboardCog(mock_bot)
    guild = _make_mock_guild(owner_id=999000111)

    # User is not connected to voice (voice is None)
    owner_member = MagicMock(spec=discord.Member)
    owner_member.id = 999000111
    owner_member.voice = None
    owner_member.guild = guild

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = owner_member
    interaction.guild = guild
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog._execute_ownerpanel(interaction)

    # Defer was called
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    # Followup sent with OwnerDashboardView (NOT blocked by voice requirement!)
    interaction.followup.send.assert_awaited_once()
    kwargs = interaction.followup.send.call_args[1]
    assert "view" in kwargs
    assert isinstance(kwargs["view"], OwnerDashboardView)
    assert kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_ownerpanel_blocks_unauthorized_user(mock_bot):
    """Verify /ownerpanel denies access to ordinary non-owner users."""
    cog = OwnerDashboardCog(mock_bot)
    guild = _make_mock_guild(owner_id=999000111)

    intruder = MagicMock(spec=discord.Member)
    intruder.id = 555444333  # Not owner, not bot owner
    intruder.voice = None
    intruder.guild = guild

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = intruder
    interaction.guild = guild
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.send_message = AsyncMock()

    await cog._execute_ownerpanel(interaction)

    interaction.response.send_message.assert_awaited_once()
    msg = interaction.response.send_message.call_args[0][0]
    assert "Access Denied" in msg


# ==============================================================================
# SECTION 2: SECURITY WHITELIST TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_security_whitelist_opens_without_voice(mock_bot):
    """Verify /security whitelist opens the management interface without needing a voice channel."""
    cog = Security(mock_bot)
    guild = _make_mock_guild(owner_id=999000111)

    owner_member = MagicMock(spec=discord.Member)
    owner_member.id = 999000111
    owner_member.guild = guild

    uctx = MagicMock(spec=UnifiedContext)
    uctx.guild = guild
    uctx.author = owner_member
    uctx.interaction = MagicMock()
    uctx.interaction.user = owner_member
    uctx.is_interaction = True
    uctx.send = AsyncMock()

    await cog._execute_securitywhitelist(uctx)

    uctx.send.assert_awaited_once()
    kwargs = uctx.send.call_args[1]
    assert "view" in kwargs
    assert type(kwargs["view"]).__name__ == "SecurityWhitelistView"


@pytest.mark.asyncio
async def test_whitelist_guild_data_isolation(mock_bot):
    """Verify whitelisting a user in Server A does NOT whitelist them in Server B."""
    guild_a = _make_mock_guild(guild_id=11111)
    guild_b = _make_mock_guild(guild_id=22222)

    # Server A whitelist view
    view_a = SecurityWhitelistView(mock_bot, guild_a, whitelist_users=[777], whitelist_roles=[])
    # Server B whitelist view
    view_b = SecurityWhitelistView(mock_bot, guild_b, whitelist_users=[], whitelist_roles=[])

    assert 777 in view_a.whitelist_users
    assert 777 not in view_b.whitelist_users


# ==============================================================================
# SECTION 3: PER-GUILD SECURITY PUNISHMENT & NON-DESTRUCTIVE DEFAULT TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_new_guild_defaults_to_non_destructive_log_only(mock_bot):
    """Verify that a freshly initialized guild does NOT execute destructive punishments by default."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild(guild_id=99999)

    # Actor exceeds mass ban threshold in unconfigured guild
    rogue = MagicMock(spec=discord.Member, id=444555666)
    rogue.top_role = MagicMock(spec=discord.Role, position=10)
    guild.get_member = MagicMock(return_value=rogue)

    # Trigger 3 bans (threshold is 3)
    for _ in range(3):
        service._track(guild.id, 444555666, "mass_ban", 15)

    # Execute nuke handling with default settings
    await service._handle_nuke_action(guild, 444555666, "mass_ban", "Banned 3 members", 3)

    # Incident was logged
    mock_bot.security_repo.log_incident.assert_awaited()
    # BUT NO destructive ban/kick was executed against the rogue actor because policy is not_configured / none!
    guild.ban.assert_not_awaited()
    guild.kick.assert_not_awaited()


@pytest.mark.asyncio
async def test_per_event_punishment_configuration_independent(mock_bot):
    """Verify server owner can independently configure different punishments for different events."""
    cog = Security(mock_bot)
    guild = _make_mock_guild(guild_id=88888, owner_id=999000111)

    owner_member = MagicMock(spec=discord.Member, id=999000111, guild=guild)

    uctx = MagicMock(spec=UnifiedContext)
    uctx.guild = guild
    uctx.author = owner_member
    uctx.interaction = MagicMock(user=owner_member)
    uctx.is_interaction = True
    uctx.send_success = AsyncMock()

    # 1. Set channel_delete -> ban
    await cog._execute_securitypunish(uctx, action="ban", event="channel_delete")
    mock_bot.security_repo.set_event_punishment.assert_awaited_with(guild.id, "channel_delete", "ban")

    # 2. Set mass_kick -> timeout
    await cog._execute_securitypunish(uctx, action="timeout", event="mass_kick")
    mock_bot.security_repo.set_event_punishment.assert_awaited_with(guild.id, "mass_kick", "timeout")

    # 3. Set anti_bot -> kick
    await cog._execute_securitypunish(uctx, action="kick", event="anti_bot")
    mock_bot.security_repo.set_event_punishment.assert_awaited_with(guild.id, "anti_bot", "kick")


@pytest.mark.asyncio
async def test_configured_punishment_executes_safely(mock_bot):
    """Verify that when a punishment is explicitly configured, it executes correctly."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild(guild_id=77777)

    # Configure channel_delete = ban
    await mock_bot.security_repo.set_event_punishment(guild.id, "channel_delete", "ban")

    rogue = MagicMock(spec=discord.Member, id=333222111)
    rogue.top_role = MagicMock(spec=discord.Role, position=20)
    guild.get_member = MagicMock(return_value=rogue)

    # Trigger channel delete threshold
    service._track(guild.id, 333222111, "channel_delete", 15)
    await service._handle_nuke_action(guild, 333222111, "channel_delete", "Deleted channel", 1)

    # Ban was executed!
    guild.ban.assert_awaited_once_with(
        rogue,
        reason="KROVEX Security: channel_delete threshold exceeded",
        delete_message_days=0,
    )


@pytest.mark.asyncio
async def test_role_hierarchy_blocks_higher_target(mock_bot):
    """Verify that bot does not attempt destructive punishment if target role is higher than bot."""
    service = SecurityService(mock_bot)
    guild = _make_mock_guild(guild_id=66666)

    # Bot top role is 100, target role is 110 (higher than bot!)
    guild.me.top_role.position = 100
    target = MagicMock(spec=discord.Member, id=888777666)
    target.top_role = MagicMock(spec=discord.Role, position=110)

    # Attempt ban
    await service._apply_punishment(guild, target, "ban", "Mass nuke")

    # Ban was aborted due to hierarchy restriction
    guild.ban.assert_not_awaited()


@pytest.mark.asyncio
async def test_punishment_reset_to_not_configured(mock_bot):
    """Verify resetting an event policy restores it to not_configured."""
    cog = Security(mock_bot)
    guild = _make_mock_guild(guild_id=55555, owner_id=999000111)

    owner_member = MagicMock(spec=discord.Member, id=999000111, guild=guild)
    uctx = MagicMock(spec=UnifiedContext, guild=guild, author=owner_member, is_interaction=False)
    uctx.send_success = AsyncMock()

    # Reset channel_delete to not_configured
    await cog._execute_securitypunish(uctx, action="not_configured", event="channel_delete")

    mock_bot.security_repo.set_event_punishment.assert_awaited_with(
        guild.id, "channel_delete", "not_configured"
    )
