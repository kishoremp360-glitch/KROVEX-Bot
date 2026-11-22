"""Unit tests for the Advanced Security & Anti-Nuke Cog and Service."""

import json
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.security.cog import Security
from bot.services.security_service import SecurityService
from bot.core.context import UnifiedContext


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.user.name = "Death Bot"
    bot.db = MagicMock()
    bot.db_manager = bot.db
    bot.security_repo = MagicMock()
    bot.security_repo.get_settings = AsyncMock(return_value={
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
        "punishment": "quarantine",
        "account_age_threshold_hours": 24,
        "join_rate_max": 5,
        "join_rate_seconds": 10,
        "whitelist_users": [123456],
        "whitelist_roles": [],
    })
    bot.security_repo.update_settings = AsyncMock()
    bot.security_repo.get_trusted_users = AsyncMock(return_value=[{"user_id": 123456, "added_by": 999}])
    bot.security_repo.add_trusted_user = AsyncMock()
    bot.security_repo.remove_trusted_user = AsyncMock(return_value=True)
    bot.security_repo.get_recent_incidents = AsyncMock(return_value=[])
    return bot


def _make_admin_ctx():
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock()
    ctx.guild.id = 111111
    ctx.guild.name = "Test Guild"
    ctx.is_interaction = False
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = 999
    ctx.author.guild_permissions.administrator = True
    ctx.reply = AsyncMock()
    ctx.send = AsyncMock()
    ctx.send_success = AsyncMock()
    ctx.send_error = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_security_status(mock_bot):
    """Test securitystatus command returns status embed."""
    cog = Security(mock_bot)
    ctx = _make_admin_ctx()

    await cog._execute_securitystatus(ctx)
    ctx.send.assert_awaited_once()
    kwargs = ctx.send.call_args[1]
    assert "embed" in kwargs
    embed = kwargs["embed"]
    assert "Security Status" in embed.title


@pytest.mark.asyncio
async def test_antinuke_toggle(mock_bot):
    """Test antinuke command can enable/disable module."""
    cog = Security(mock_bot)
    ctx = _make_admin_ctx()

    await cog._execute_antinuke(ctx, "disable")
    mock_bot.security_repo.update_settings.assert_awaited_with(111111, anti_nuke=0)


@pytest.mark.asyncio
async def test_antibanthreshold_valid_and_invalid(mock_bot):
    """Test antibanthreshold validates integer bounds (1-10)."""
    cog = Security(mock_bot)
    ctx = _make_admin_ctx()

    # Valid threshold
    await cog._execute_antibanthreshold(ctx, 5)
    mock_bot.security_repo.update_settings.assert_awaited_with(111111, mass_ban_threshold=5)

    # Invalid threshold (too high)
    await cog._execute_antibanthreshold(ctx, 15)
    ctx.send_error.assert_awaited_with("Invalid Range", "Threshold must be between 1 and 10.")


@pytest.mark.asyncio
async def test_security_punishment_validation(mock_bot):
    """Test securitypunish validates allowed punishment types."""
    cog = Security(mock_bot)
    ctx = _make_admin_ctx()

    # Valid punishment
    await cog._execute_securitypunish(ctx, "ban")
    mock_bot.security_repo.update_settings.assert_awaited_with(111111, punishment="ban")

    # Invalid punishment
    await cog._execute_securitypunish(ctx, "explode")
    ctx.send_error.assert_awaited()


@pytest.mark.asyncio
async def test_security_service_tracking():
    """Test in-memory window pruning and rate tracking in SecurityService."""
    bot = MagicMock()
    service = SecurityService(bot)
    guild_id = 9999
    actor_id = 5555

    # Tracking 3 actions within 15 seconds window
    count1 = service._track(guild_id, actor_id, "mass_ban", 15)
    assert count1 == 1
    count2 = service._track(guild_id, actor_id, "mass_ban", 15)
    assert count2 == 2
    count3 = service._track(guild_id, actor_id, "mass_ban", 15)
    assert count3 == 3

    # Server owner is always whitelisted
    guild = MagicMock()
    guild.owner_id = actor_id
    assert service._is_whitelisted(actor_id, guild, "[]") is True
