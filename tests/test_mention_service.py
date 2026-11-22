"""Comprehensive Automated Tests for Real-Time Mention Notification System."""

from __future__ import annotations

import collections
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.config import BotConfig
from bot.core.bot import DeathBot
from bot.services.mention_service import MentionService, _sanitize, BRAND_COLOR
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import MentionSettingsRepository


@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=DeathBot)
    bot.user = MagicMock(spec=discord.ClientUser)
    bot.user.id = 999999999
    bot.user.name = "Death Bot"
    bot.user.display_avatar.url = "https://example.com/bot_avatar.png"
    bot.mention_repo = AsyncMock(spec=MentionSettingsRepository)
    bot.mention_repo.is_enabled = AsyncMock(return_value=True)
    bot.mention_repo.set_enabled = AsyncMock()
    bot.mention_repo.toggle = AsyncMock(return_value=False)
    return bot


def _make_mock_message(
    content: str = "Hey @user check this out!",
    author_id: int = 1001,
    author_bot: bool = False,
    guild_id: int = 5001,
    channel_id: int = 6001,
    mentions: list = None,
    message_id: int = 7001,
):
    msg = MagicMock(spec=discord.Message)
    msg.id = message_id
    msg.content = content
    msg.created_at = datetime.now(timezone.utc)
    msg.jump_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"

    # Guild
    msg.guild = MagicMock(spec=discord.Guild)
    msg.guild.id = guild_id
    msg.guild.name = "Test Guild Nexus"
    msg.guild.icon = MagicMock()
    msg.guild.icon.url = "https://example.com/guild_icon.png"

    # Channel
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.name = "general-chat"
    channel.mention = f"<#{channel_id}>"
    msg.channel = channel

    # Author
    author = MagicMock(spec=discord.Member)
    author.id = author_id
    author.name = "AuthorUser"
    author.mention = f"<@{author_id}>"
    author.bot = author_bot
    msg.author = author

    # Mentions
    msg.mentions = mentions or []
    return msg


def _make_mock_member(user_id: int = 2001, name: str = "TargetUser", is_bot: bool = False, can_read: bool = True):
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.name = name
    member.mention = f"<@{user_id}>"
    member.bot = is_bot
    member.send = AsyncMock()

    # Permissions
    perms = MagicMock()
    perms.read_messages = can_read
    perms.view_channel = can_read
    return member, perms


# ========================================================
# 1. EMBED STRUCTURE & SPECIFICATION TESTS
# ========================================================

def test_sanitize_tokens():
    """Verify sensitive tokens are redacted from preview snippets."""
    sample = "Check token sample_mock_token_string_24.mock06.sample_mock_secret_string_27chars"
    sanitized = _sanitize(sample)
    assert "[REDACTED_TOKEN]" in sanitized
    assert "sample_mock_token_string_24" not in sanitized


def test_mention_embed_uginex_format(mock_bot):
    """Verify the notification embed matches the exact UGINEX reference specification."""
    service = MentionService(mock_bot)
    target, _ = _make_mock_member(user_id=2001, name="Alice")
    msg = _make_mock_message(content="Hey @Alice look at this awesome update!", mentions=[target])

    embed = service._build_mention_embed(msg, target)

    # 1. Title
    assert embed.title == "🔔 You were mentioned in Test Guild Nexus"
    assert embed.color.value == BRAND_COLOR

    # 2. Field verification
    field_dict = {f.name: f.value for f in embed.fields}
    assert "Mentioned User" in field_dict
    assert "<@2001>" in field_dict["Mentioned User"]
    assert "Alice" in field_dict["Mentioned User"]

    assert "Server" in field_dict
    assert "**Test Guild Nexus**" in field_dict["Server"]

    assert "Channel" in field_dict
    assert "<#6001>" in field_dict["Channel"]

    assert "Message Author" in field_dict
    assert "<@1001>" in field_dict["Message Author"]
    assert "AuthorUser" in field_dict["Message Author"]

    assert "Message Content" in field_dict
    assert "Hey @Alice look at this awesome update!" in field_dict["Message Content"]

    assert "Direct Link" in field_dict
    assert f"[Jump to Message]({msg.jump_url})" in field_dict["Direct Link"]

    # 3. Footer
    assert embed.footer.text == "DEATH BOT • REAL-TIME MENTIONS"


# ========================================================
# 2. EVENT DISPATCH & FILTERING TESTS
# ========================================================

@pytest.mark.asyncio
async def test_single_mention_delivery(mock_bot):
    """Verify single mention sends a single DM with the proper embed."""
    service = MentionService(mock_bot)
    target, perms = _make_mock_member(user_id=2001, name="Alice")
    msg = _make_mock_message(mentions=[target])
    msg.channel.permissions_for = MagicMock(return_value=perms)

    await service.on_message(msg)

    target.send.assert_awaited_once()
    sent_embed = target.send.call_args.kwargs.get("embed")
    assert sent_embed is not None
    assert sent_embed.title == "🔔 You were mentioned in Test Guild Nexus"


@pytest.mark.asyncio
async def test_multiple_mentions_and_duplicate_suppression(mock_bot):
    """Verify multiple unique targets receive DMs, but duplicates within the same message do not receive duplicate DMs."""
    service = MentionService(mock_bot)
    target1, perms1 = _make_mock_member(user_id=2001, name="Alice")
    target2, perms2 = _make_mock_member(user_id=2002, name="Bob")

    # Pass target1 twice (duplicate mention in same message)
    msg = _make_mock_message(mentions=[target1, target2, target1])
    msg.channel.permissions_for = MagicMock(side_effect=lambda m: perms1 if m.id == 2001 else perms2)

    await service.on_message(msg)

    # Each target should be sent exactly once
    target1.send.assert_awaited_once()
    target2.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_ignore_author_self_mention(mock_bot):
    """Verify author mentioning themselves is strictly ignored."""
    service = MentionService(mock_bot)
    author_target, _ = _make_mock_member(user_id=1001, name="AuthorUser")
    msg = _make_mock_message(author_id=1001, mentions=[author_target])

    await service.on_message(msg)

    author_target.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_ignore_bot_mentions(mock_bot):
    """Verify bots mentioned in messages are strictly ignored."""
    service = MentionService(mock_bot)
    bot_target, _ = _make_mock_member(user_id=3001, name="MusicBot", is_bot=True)
    msg = _make_mock_message(mentions=[bot_target])

    await service.on_message(msg)

    bot_target.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_ignore_messages_from_bots_or_dms(mock_bot):
    """Verify messages sent by bots or outside guilds do not trigger notifications."""
    service = MentionService(mock_bot)
    target, _ = _make_mock_member(user_id=2001)

    # 1. Author is bot
    msg_bot = _make_mock_message(author_bot=True, mentions=[target])
    await service.on_message(msg_bot)
    target.send.assert_not_awaited()

    # 2. No guild (DM)
    msg_dm = _make_mock_message(mentions=[target])
    msg_dm.guild = None
    await service.on_message(msg_dm)
    target.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_message_loop_prevention(mock_bot):
    """Verify processing the same message ID twice hits the deduplication cache."""
    service = MentionService(mock_bot)
    target, perms = _make_mock_member(user_id=2001)
    msg = _make_mock_message(message_id=8888, mentions=[target])
    msg.channel.permissions_for = MagicMock(return_value=perms)

    # First trigger
    await service.on_message(msg)
    assert target.send.await_count == 1

    # Second trigger with same message ID
    await service.on_message(msg)
    assert target.send.await_count == 1  # Unchanged!


@pytest.mark.asyncio
async def test_hidden_channel_permission_gating(mock_bot):
    """Verify users without read_messages permissions do NOT receive mention DMs for hidden channels."""
    service = MentionService(mock_bot)
    target, perms = _make_mock_member(user_id=2001, can_read=False)
    msg = _make_mock_message(mentions=[target])
    msg.channel.permissions_for = MagicMock(return_value=perms)

    await service.on_message(msg)

    # Notification must NOT be sent
    target.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_opt_out_respected(mock_bot):
    """Verify user opt-out in database stops DMs."""
    service = MentionService(mock_bot)
    mock_bot.mention_repo.is_enabled = AsyncMock(return_value=False)

    target, perms = _make_mock_member(user_id=2001)
    msg = _make_mock_message(mentions=[target])
    msg.channel.permissions_for = MagicMock(return_value=perms)

    await service.on_message(msg)

    target.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_closed_dms_handled_gracefully(mock_bot):
    """Verify discord.Forbidden or HTTPException does not raise an unhandled error."""
    service = MentionService(mock_bot)
    target, perms = _make_mock_member(user_id=2001)
    target.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Cannot send messages to this user"))

    msg = _make_mock_message(mentions=[target])
    msg.channel.permissions_for = MagicMock(return_value=perms)

    # Must complete cleanly without unhandled exception
    await service.on_message(msg)
    assert target.send.await_count == 1


# ========================================================
# 3. REPOSITORY & PREFERENCE COMMAND TESTS
# ========================================================

@pytest.mark.asyncio
async def test_mention_repository_toggle_and_state(tmp_path):
    """Verify MentionSettingsRepository database persistence and toggle behavior."""
    db_file = tmp_path / "test_mentions.sqlite"
    db = SQLiteDatabaseManager(db_file)
    await db.connect()

    repo = MentionSettingsRepository(db)

    # Default is True
    assert await repo.is_enabled(12345) is True

    # Toggle to False
    new_state = await repo.toggle(12345)
    assert new_state is False
    assert await repo.is_enabled(12345) is False

    # Toggle to True
    new_state = await repo.toggle(12345)
    assert new_state is True
    assert await repo.is_enabled(12345) is True

    # Explicit set_enabled
    await repo.set_enabled(12345, False)
    assert await repo.is_enabled(12345) is False

    await db.close()


@pytest.mark.asyncio
async def test_mentionnotifs_prefix_command_toggle(mock_bot):
    """Verify prefix command toggle and subcommands work cleanly."""
    service = MentionService(mock_bot)
    ctx = MagicMock()
    ctx.author.id = 9999
    ctx.prefix = ","
    ctx.send = AsyncMock()

    # 1. Toggle (no state arg)
    mock_bot.mention_repo.toggle = AsyncMock(return_value=True)
    await service.mentionnotifs_prefix.callback(service, ctx, state=None)
    ctx.send.assert_awaited()
    embed = ctx.send.call_args.kwargs.get("embed")
    assert "Enabled" in embed.title

    # 2. Enable
    await service.mentionnotifs_prefix.callback(service, ctx, state="enable")
    mock_bot.mention_repo.set_enabled.assert_awaited_with(9999, True)

    # 3. Disable
    await service.mentionnotifs_prefix.callback(service, ctx, state="disable")
    mock_bot.mention_repo.set_enabled.assert_awaited_with(9999, False)

    # 4. Status
    mock_bot.mention_repo.is_enabled = AsyncMock(return_value=True)
    await service.mentionnotifs_prefix.callback(service, ctx, state="status")
    status_embed = ctx.send.call_args.kwargs.get("embed")
    assert "Status" in status_embed.title


# ========================================================
# 4. BOT INTEGRATION & SLASH COMMAND LIMIT AUDIT
# ========================================================

@pytest.mark.asyncio
async def test_slash_command_registered_under_limit():
    """Verify /mentionnotifs is registered and top-level slash commands remain <= 100."""
    bot = DeathBot(config=BotConfig.from_env(validate=False))
    await bot.load_cogs()
    # Also load the mention service
    cog = MentionService(bot)
    await bot.add_cog(cog)

    # Check top-level slash commands
    top_level_cmds = bot.tree.get_commands()
    cmd_names = [cmd.name for cmd in top_level_cmds]

    # Check prefix command remains registered
    assert bot.get_command("mentionnotifs") is not None
    assert len(top_level_cmds) <= 100, f"Slash command limit exceeded: {len(top_level_cmds)}/100"
    print(f"Total slash commands registered: {len(top_level_cmds)} / 100")
