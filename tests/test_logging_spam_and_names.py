"""Unit and regression tests for KROVEX Log Spam Fix and Username Display Resolution.

Verifies:
1. Display name resolution priority:
   - Server nickname (member.display_name) -> Global display name (user.global_name) -> Username (user.name) -> 'Unknown User' / '@unknown' fallback.
2. Bot voice self-logging suppression in on_voice_state_update.
3. Channel ignore logic: active audit channels and database-filtered channels ignore message delete/edit.
4. Sliding-window event deduplication prevents duplicate event emissions within window.
5. Single consolidated member join card: invite details attached directly without duplicate card.
6. Elimination of raw Discord IDs from user-facing embed descriptions and titles.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.services.logging_service import LoggingService


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.logging_repo = MagicMock()
    bot.logging_repo.get_settings = AsyncMock(return_value={
        "mod_log_channel": 111111,
        "message_log_channel": 222222,
        "member_log_channel": 333333,
        "server_log_channel": 444444,
        "voice_log_channel": 555555,
        "status_log_channel": 666666,
        "invite_log_channel": 777777,
    })
    bot.logging_repo.get_filters = AsyncMock(return_value=[
        {"filter_type": "channel", "target": "888888"},
        {"filter_type": "channel", "target": "999999"}
    ])
    bot.logging_repo.is_event_enabled = AsyncMock(return_value=True)
    bot.logging_repo.log_event = AsyncMock()
    return bot


@pytest.fixture
def service(mock_bot):
    srv = LoggingService(mock_bot)
    srv._status_cooldowns = {}
    srv._recent_events = {}
    return srv


@pytest.mark.asyncio
async def test_format_user_priority_nickname(service):
    """Priority 1: Member nickname takes precedence when present."""
    member = MagicMock(spec=discord.Member)
    member.display_name = "Super Admin"
    member.name = "admin123"
    member.global_name = "Global Admin"

    disp, handle = await service._format_user(member)
    assert disp == "Super Admin"
    assert handle == "@admin123"


@pytest.mark.asyncio
async def test_format_user_priority_global_name(service):
    """Priority 2: Global name takes precedence when member is absent or just User object."""
    user = MagicMock(spec=discord.User)
    user.global_name = "Krovex Creator"
    user.name = "krovex_dev"
    delattr(user, "display_name")  # Ensure no member display_name attribute

    disp, handle = await service._format_user(user)
    assert disp == "Krovex Creator"
    assert handle == "@krovex_dev"


@pytest.mark.asyncio
async def test_format_user_priority_username(service):
    """Priority 3: Username is used when global name is not set."""
    user = MagicMock(spec=discord.User)
    user.global_name = None
    user.name = "just_a_user"

    disp, handle = await service._format_user(user)
    assert disp == "just_a_user"
    assert handle == "@just_a_user"


@pytest.mark.asyncio
async def test_format_user_fallback_unknown(service):
    """Fallback: When user is None or unrecognized, fallback to Unknown User."""
    disp, handle = await service._format_user(None)
    assert disp == "Unknown User"
    assert handle == "@unknown"

    disp_invalid, handle_invalid = await service._format_user("invalid_type")
    assert disp_invalid == "Unknown User"
    assert handle_invalid == "@unknown"


@pytest.mark.asyncio
async def test_format_user_id_lookup_fallback(service, mock_bot):
    """Resolving raw ID fetches from cache/API or falls back cleanly."""
    mock_bot.get_user.return_value = None
    mock_bot.fetch_user = AsyncMock(side_effect=Exception("API Error"))

    disp, handle = await service._format_user(123456789, guild=None)
    assert disp == "Unknown User"
    assert handle == "@unknown"


@pytest.mark.asyncio
async def test_voice_self_logging_suppression(service, mock_bot):
    """Bot's own voice state events (e.g. music joining/leaving) must be ignored."""
    guild = MagicMock(spec=discord.Guild)
    bot_member = MagicMock(spec=discord.Member)
    bot_member.id = mock_bot.user.id
    bot_member.guild = guild

    before = MagicMock(spec=discord.VoiceState)
    before.channel = None
    after = MagicMock(spec=discord.VoiceState)
    after.channel = MagicMock(spec=discord.VoiceChannel, name="General")

    service._emit_log = AsyncMock()

    await service.on_voice_state_update(bot_member, before, after)
    service._emit_log.assert_not_called()


@pytest.mark.asyncio
async def test_voice_user_event_no_raw_ids(service):
    """User voice state events produce formatted names and omit raw IDs."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 999111
    user_member = MagicMock(spec=discord.Member)
    user_member.id = 888777666
    user_member.display_name = "Alice"
    user_member.name = "alice_wonder"
    user_member.guild = guild

    before = MagicMock(spec=discord.VoiceState)
    before.channel = None
    before.mute = False
    before.deaf = False
    before.self_mute = False
    before.self_deaf = False
    before.self_stream = False
    before.self_video = False

    after = MagicMock(spec=discord.VoiceState)
    ch = MagicMock(spec=discord.VoiceChannel)
    ch.name = "Lounge"
    ch.id = 12345
    after.channel = ch
    after.mute = False
    after.deaf = False
    after.self_mute = False
    after.self_deaf = False
    after.self_stream = False
    after.self_video = False

    service._emit_log = AsyncMock()

    await service.on_voice_state_update(user_member, before, after)
    service._emit_log.assert_called_once()
    call_args = service._emit_log.call_args[0]
    embed = call_args[3]

    assert "Alice" in embed.description
    assert "@alice_wonder" in embed.description
    assert "888777666" not in embed.description


@pytest.mark.asyncio
async def test_channel_ignored_active_audit_vault(service):
    """Audit channels in KROVEX Audit Vault are recognized as ignored."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 999111

    msg_tracker = MagicMock(spec=discord.TextChannel)
    msg_tracker.id = 222222
    assert await service._is_channel_ignored(guild, msg_tracker) is True

    sec_feed = MagicMock(spec=discord.TextChannel)
    sec_feed.id = 111111
    assert await service._is_channel_ignored(guild, sec_feed) is True

    normal_channel = MagicMock(spec=discord.TextChannel)
    normal_channel.id = 333444
    assert await service._is_channel_ignored(guild, normal_channel) is False


@pytest.mark.asyncio
async def test_channel_ignored_database_filter(service):
    """Channels configured in logging filters are recognized as ignored."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 999111

    filtered_channel = MagicMock(spec=discord.TextChannel)
    filtered_channel.id = 888888
    assert await service._is_channel_ignored(guild, filtered_channel) is True


@pytest.mark.asyncio
async def test_message_delete_in_audit_channel_suppressed(service):
    """Deleting messages inside audit channels does not trigger message logging recursion."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 999111
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 222222  # message_log_channel

    author = MagicMock(spec=discord.Member)
    author.bot = False
    author.id = 12345

    msg = MagicMock(spec=discord.Message)
    msg.guild = guild
    msg.channel = channel
    msg.author = author

    service._emit_log = AsyncMock()

    await service.on_message_delete(msg)
    service._emit_log.assert_not_called()


@pytest.mark.asyncio
async def test_sliding_window_deduplication(service):
    """Repeated identical events within the deduplication window are dropped."""
    key = "test_event_key_123"
    assert service._is_duplicate_event(key, window=2.0) is False
    assert service._is_duplicate_event(key, window=2.0) is True

    # After expiration
    service._recent_events[key] = time.time() - 3.0
    assert service._is_duplicate_event(key, window=2.0) is False


@pytest.mark.asyncio
async def test_single_member_join_card_with_invite_details(service):
    """Member join generates a single consolidated card with invite info and no raw IDs in text."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 999111
    guild.member_count = 142
    guild.me.guild_permissions.manage_guild = True

    inv = MagicMock(spec=discord.Invite)
    inv.code = "krovex-vip"
    inv.uses = 5
    inviter = MagicMock(spec=discord.Member)
    inviter.id = 445566
    inviter.display_name = "Recruiter Bob"
    inviter.name = "bob"
    inv.inviter = inviter

    guild.invites = AsyncMock(return_value=[inv])
    service._invite_cache[guild.id] = {"krovex-vip": 4}  # Previous count 4, now 5

    member = MagicMock(spec=discord.Member)
    member.id = 112233
    member.guild = guild
    member.display_name = "NewComer"
    member.name = "newbie"
    member.created_at = discord.utils.utcnow()
    member.display_avatar.url = "https://cdn.discordapp.com/avatars/112233/abc.png"

    service._emit_log = AsyncMock()

    await service.on_member_join(member)

    # Exactly 1 event emitted (no duplicate direct/vanity card)
    assert service._emit_log.call_count == 1
    call_args = service._emit_log.call_args[0]
    embed = call_args[3]

    assert embed.title == "📥 Member Joined"
    assert "NewComer" in embed.description
    assert "@newbie" in embed.description
    assert "112233" not in embed.description

    # Field checks
    fields = {f.name: f.value for f in embed.fields}
    assert "Invite Code" in fields
    assert "`krovex-vip`" in fields["Invite Code"]
    assert "Invited By" in fields
    assert "Recruiter Bob (@bob)" in fields["Invited By"]
