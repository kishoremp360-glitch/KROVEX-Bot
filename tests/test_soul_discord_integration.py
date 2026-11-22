"""Test suite for KROVEX SOUL Phase 3.1 & Continuity/Emoji Upgrades.

Verifies:
1. Direct mention starts a session.
2. Direct reply to bot message starts a session.
3. Follow-up without mention or reply in active session receives a response.
4. Emoji-only messages (😂, 😭😭😭, ❤️, 💀) in active session receive responses.
5. Discord custom emojis (<:name:id>) are normalized to :name:.
6. Other users in the same channel cannot enter or hijack an active session.
7. Channel isolation prevents active session in channel A from triggering in channel B.
8. Inactivity expiry (>30 minutes) closes session and requires new mention/reply.
9. Explicit farewells ("bye", "good night", "seri bye", "stop", "tata") close the session.
10. Casual words ("seri", "okay", "hmm") do not close the session.
11. Ordinary server chatter without active session is ignored.
12. Valid prefix commands are never intercepted by SOUL.
13. Bot messages and webhooks are ignored.
14. Emoji reaction acknowledgment on KROVEX message during active session.
15. Emoji reaction without active session is ignored.
16. Deleted and unresolved reply references are handled safely.
17. Provider failures return safe friendly messages without leaking errors.
18. Message splitting respects Discord's 2000-character limit.
19. Safe AllowedMentions configuration prevents mass-pings.
20. Owner-only diagnostic command functionality.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from pathlib import Path

from bot.cogs.soul.cog import (
    Soul,
    is_conversation_ending,
    normalize_discord_emojis,
    split_discord_message,
)
from bot.services.ai.personality import get_system_prompt, sanitize_ai_output
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.soul_repo import SoulRepository
from bot.services.ai.soul_service import SoulService
from bot.services.ai.base_provider import BaseAIProvider, AIResponse


def run_async(coro):
    return asyncio.run(coro)


class AsyncContextManagerMock:
    """Mock for async context managers such as channel.typing()."""
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


def make_mock_bot(bot_id: int = 999999999999999999):
    """Create a mock DeathBot instance with realistic SoulService session tracking."""
    bot = MagicMock()
    bot.user = MagicMock(spec=discord.ClientUser)
    bot.user.id = bot_id
    bot.user.name = "KROVEX"
    bot.config = MagicMock()
    bot.config.owner_ids = [123456789012345678]
    bot.is_owner = AsyncMock(return_value=False)
    
    # In-memory active sessions tracker for the mock
    active_sessions = {}
    
    soul_service = MagicMock()
    soul_service._active_sessions = active_sessions
    
    def activate_session(guild_id, channel_id, user_id):
        active_sessions[(guild_id, channel_id, user_id)] = time.monotonic()
        
    def end_session(guild_id, channel_id, user_id):
        return active_sessions.pop((guild_id, channel_id, user_id), None) is not None
        
    def is_session_active(guild_id, channel_id, user_id, timeout_minutes=30):
        t = active_sessions.get((guild_id, channel_id, user_id))
        if t is None:
            return False
        if time.monotonic() - t > timeout_minutes * 60:
            active_sessions.pop((guild_id, channel_id, user_id), None)
            return False
        return True

    soul_service.activate_session = MagicMock(side_effect=activate_session)
    soul_service.end_session = MagicMock(side_effect=end_session)
    soul_service.is_session_active = MagicMock(side_effect=is_session_active)
    soul_service.generate_chat_reply = AsyncMock(
        return_value=("Dei machaww! Inga dhaan iruken! 😂", None)
    )
    
    bot.soul_service = soul_service
    
    # Mock get_context for prefix command check
    mock_ctx = MagicMock()
    mock_ctx.valid = False
    bot.get_context = AsyncMock(return_value=mock_ctx)
    
    return bot


def make_mock_message(
    content: str,
    author_id: int = 111111111111111111,
    author_name: str = "TestUser",
    is_bot: bool = False,
    webhook_id: int | None = None,
    guild_id: int = 222222222222222222,
    channel_id: int = 333333333333333333,
    mentions: list | None = None,
    mention_everyone: bool = False,
    reference: discord.MessageReference | None = None,
):
    """Create a mock discord.Message."""
    msg = MagicMock(spec=discord.Message)
    msg.content = content
    msg.id = 555555555555555555
    msg.webhook_id = webhook_id
    msg.mention_everyone = mention_everyone
    msg.mentions = mentions or []
    msg.reference = reference
    
    # Author
    author = MagicMock(spec=discord.Member)
    author.id = author_id
    author.display_name = author_name
    author.name = author_name
    author.bot = is_bot
    author.guild_permissions = MagicMock()
    author.guild_permissions.administrator = False
    msg.author = author
    
    # Guild
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = "Test Server"
    bot_member = MagicMock(spec=discord.Member)
    perms = MagicMock()
    perms.send_messages = True
    perms.read_messages = True
    perms.add_reactions = True
    guild.me = bot_member
    msg.guild = guild
    
    # Channel
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.permissions_for = MagicMock(return_value=perms)
    channel.typing = MagicMock(return_value=AsyncContextManagerMock())
    channel.send = AsyncMock()
    channel.fetch_message = AsyncMock()
    msg.channel = channel
    
    msg.reply = AsyncMock()
    return msg


def test_is_conversation_ending():
    """Verify detection of explicit goodbyes and preservation of casual words."""
    assert is_conversation_ending("bye") is True
    assert is_conversation_ending("byee") is True
    assert is_conversation_ending("seri bye da") is True
    assert is_conversation_ending("good night macha") is True
    assert is_conversation_ending("gn da") is True
    assert is_conversation_ending("stop") is True
    assert is_conversation_ending("end chat") is True
    assert is_conversation_ending("tata bye bye") is True
    
    # Casual words must NOT end session
    assert is_conversation_ending("seri") is False
    assert is_conversation_ending("okay") is False
    assert is_conversation_ending("ok da") is False
    assert is_conversation_ending("hmm") is False
    assert is_conversation_ending("edhuuuu") is False
    assert is_conversation_ending("stop by at 5pm") is False


def test_normalize_discord_emojis():
    """Verify custom emojis are formatted to :name: for LLM comprehension."""
    raw = "Check this out <:pepe_laugh:123456789> and <a:dance:987654321>!"
    normalized = normalize_discord_emojis(raw)
    assert normalized == "Check this out :pepe_laugh: and :dance:!"


def test_split_discord_message():
    """Verify message chunker splits long responses safely under 2000 chars."""
    assert split_discord_message("") == []
    short_text = "Macha all good!"
    assert split_discord_message(short_text, max_chars=100) == [short_text]
    
    long_text = "A" * 2500
    chunks = split_discord_message(long_text, max_chars=1000)
    assert len(chunks) == 3
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks) == long_text


def test_mention_starts_session():
    """Verify mentioning KROVEX triggers conversation and activates session."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    msg = make_mock_message(
        content=f"<@{bot.user.id}> macha enna panra?",
        mentions=[bot.user],
    )
    
    run_async(cog.on_message(msg))
    
    bot.soul_service.generate_chat_reply.assert_awaited_once()
    assert bot.soul_service.is_session_active(msg.guild.id, msg.channel.id, msg.author.id) is True
    msg.reply.assert_awaited_once()


def test_reply_starts_session():
    """Verify replying to a KROVEX message triggers conversation and activates session."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    ref_msg = MagicMock(spec=discord.Message)
    ref_msg.author = MagicMock()
    ref_msg.author.id = bot.user.id
    ref = MagicMock(spec=discord.MessageReference)
    ref.resolved = ref_msg
    
    msg = make_mock_message(
        content="seri da game aadalam",
        mentions=[],
        reference=ref,
    )
    
    run_async(cog.on_message(msg))
    
    bot.soul_service.generate_chat_reply.assert_awaited_once()
    assert bot.soul_service.is_session_active(msg.guild.id, msg.channel.id, msg.author.id) is True
    msg.reply.assert_awaited_once()


def test_followup_without_mention_in_active_session():
    """Verify follow-up without mention or reply is answered during an active session."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    # 1. Start session with mention
    init_msg = make_mock_message(
        content=f"<@{bot.user.id}> hi macha",
        mentions=[bot.user],
    )
    run_async(cog.on_message(init_msg))
    assert bot.soul_service.is_session_active(init_msg.guild.id, init_msg.channel.id, init_msg.author.id) is True
    
    # Reset mock reply
    bot.soul_service.generate_chat_reply.reset_mock()
    
    # 2. Send follow-up: NO mention, NO reply reference
    followup_msg = make_mock_message(
        content="bore adikudhu da enna panradhu?",
        mentions=[],
        reference=None,
    )
    run_async(cog.on_message(followup_msg))
    
    bot.soul_service.generate_chat_reply.assert_awaited_once()
    kwargs = bot.soul_service.generate_chat_reply.call_args.kwargs
    assert kwargs["message_text"] == "bore adikudhu da enna panradhu?"
    followup_msg.reply.assert_awaited_once()


def test_emoji_only_followup_in_active_session():
    """Verify emoji-only messages (😂, 😭😭😭, ❤️, 💀) are processed in active session."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    # Activate session first
    bot.soul_service.activate_session(222222222222222222, 333333333333333333, 111111111111111111)
    
    # Send emoji-only message
    emoji_msg = make_mock_message(
        content="😂😂😂",
        mentions=[],
        reference=None,
    )
    run_async(cog.on_message(emoji_msg))
    
    bot.soul_service.generate_chat_reply.assert_awaited_once()
    kwargs = bot.soul_service.generate_chat_reply.call_args.kwargs
    assert kwargs["message_text"] == "😂😂😂"
    emoji_msg.reply.assert_awaited_once()


def test_other_user_cannot_enter_session():
    """Verify messages from other users in the same channel do not hijack an active session."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    # User 1 activates session
    user_1_id = 111111111111111111
    channel_id = 333333333333333333
    guild_id = 222222222222222222
    bot.soul_service.activate_session(guild_id, channel_id, user_1_id)
    
    # User 2 sends message in same channel without mention or reply
    user_2_msg = make_mock_message(
        content="hey guys what time is the meeting?",
        author_id=999999999999999998,
        channel_id=channel_id,
        guild_id=guild_id,
        mentions=[],
        reference=None,
    )
    run_async(cog.on_message(user_2_msg))
    
    # SOUL must remain silent for User 2
    bot.soul_service.generate_chat_reply.assert_not_awaited()
    user_2_msg.reply.assert_not_awaited()


def test_channel_isolation_for_same_user():
    """Verify an active session in channel A does not trigger in channel B for the same user."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    user_id = 111111111111111111
    guild_id = 222222222222222222
    channel_a = 333333333333333333
    channel_b = 444444444444444444
    
    # Activate session in channel A
    bot.soul_service.activate_session(guild_id, channel_a, user_id)
    
    # User sends message in channel B without mention/reply
    msg_channel_b = make_mock_message(
        content="hello here too",
        author_id=user_id,
        channel_id=channel_b,
        guild_id=guild_id,
        mentions=[],
        reference=None,
    )
    run_async(cog.on_message(msg_channel_b))
    
    bot.soul_service.generate_chat_reply.assert_not_awaited()
    msg_channel_b.reply.assert_not_awaited()


def test_session_expiry_after_30_minutes():
    """Verify sessions expire after 30 minutes of inactivity and ignore follow-ups."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    user_id = 111111111111111111
    guild_id = 222222222222222222
    channel_id = 333333333333333333
    
    # Activate session with timestamp set 31 minutes ago
    bot.soul_service._active_sessions[(guild_id, channel_id, user_id)] = time.monotonic() - (31 * 60)
    
    # Follow-up message sent after expiry
    msg = make_mock_message(
        content="are you still there?",
        author_id=user_id,
        channel_id=channel_id,
        guild_id=guild_id,
        mentions=[],
        reference=None,
    )
    run_async(cog.on_message(msg))
    
    # Must be ignored due to timeout
    bot.soul_service.generate_chat_reply.assert_not_awaited()
    msg.reply.assert_not_awaited()
    assert bot.soul_service.is_session_active(guild_id, channel_id, user_id) is False


def test_explicit_goodbye_closes_session():
    """Verify farewell message sends a reply and immediately terminates active session."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    user_id = 111111111111111111
    guild_id = 222222222222222222
    channel_id = 333333333333333333
    
    # Activate session
    bot.soul_service.activate_session(guild_id, channel_id, user_id)
    assert bot.soul_service.is_session_active(guild_id, channel_id, user_id) is True
    
    # User sends goodbye
    bye_msg = make_mock_message(
        content="seri bye da macha",
        author_id=user_id,
        channel_id=channel_id,
        guild_id=guild_id,
        mentions=[],
        reference=None,
    )
    run_async(cog.on_message(bye_msg))
    
    # SOUL replies to the goodbye
    bot.soul_service.generate_chat_reply.assert_awaited_once()
    bye_msg.reply.assert_awaited_once()
    
    # Session MUST be closed!
    assert bot.soul_service.is_session_active(guild_id, channel_id, user_id) is False
    
    # Later message without mention must be ignored!
    bot.soul_service.generate_chat_reply.reset_mock()
    later_msg = make_mock_message(
        content="forgot one thing",
        author_id=user_id,
        channel_id=channel_id,
        guild_id=guild_id,
        mentions=[],
        reference=None,
    )
    run_async(cog.on_message(later_msg))
    bot.soul_service.generate_chat_reply.assert_not_awaited()


def test_casual_words_do_not_close_session():
    """Verify casual words like 'seri' or 'okay' do not close active session."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    user_id = 111111111111111111
    guild_id = 222222222222222222
    channel_id = 333333333333333333
    bot.soul_service.activate_session(guild_id, channel_id, user_id)
    
    msg = make_mock_message(
        content="seri",
        author_id=user_id,
        channel_id=channel_id,
        guild_id=guild_id,
        mentions=[],
        reference=None,
    )
    run_async(cog.on_message(msg))
    
    # Session must remain ACTIVE
    assert bot.soul_service.is_session_active(guild_id, channel_id, user_id) is True


def test_ordinary_chatter_ignored():
    """Verify messages without mention, reply, or active session are ignored."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    msg = make_mock_message(
        content="hey friends let's play valorant",
        mentions=[],
        reference=None,
    )
    run_async(cog.on_message(msg))
    
    bot.soul_service.generate_chat_reply.assert_not_awaited()
    msg.reply.assert_not_awaited()


def test_prefix_command_compatibility():
    """Verify that valid prefix commands (!help, !play) are not intercepted by SOUL."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    valid_ctx = MagicMock()
    valid_ctx.valid = True
    bot.get_context = AsyncMock(return_value=valid_ctx)
    
    msg = make_mock_message(
        content="!play song",
        mentions=[],
    )
    run_async(cog.on_message(msg))
    
    bot.soul_service.generate_chat_reply.assert_not_awaited()
    msg.reply.assert_not_awaited()


def test_bots_and_webhooks_ignored():
    """Verify other bots and webhooks never trigger SOUL."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    # Other bot
    msg_bot = make_mock_message(
        content=f"<@{bot.user.id}> hello brother",
        is_bot=True,
        mentions=[bot.user],
    )
    run_async(cog.on_message(msg_bot))
    bot.soul_service.generate_chat_reply.assert_not_awaited()
    
    # Webhook
    msg_webhook = make_mock_message(
        content=f"<@{bot.user.id}> automated alert",
        webhook_id=777777777777777777,
        mentions=[bot.user],
    )
    run_async(cog.on_message(msg_webhook))
    bot.soul_service.generate_chat_reply.assert_not_awaited()


def test_emoji_reaction_acknowledgment():
    """Verify reaction to KROVEX message during active session triggers emoji reaction."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    user_id = 111111111111111111
    guild_id = 222222222222222222
    channel_id = 333333333333333333
    message_id = 777777777777777777
    
    # Activate session
    bot.soul_service.activate_session(guild_id, channel_id, user_id)
    
    # Mock channel and message
    channel = MagicMock(spec=discord.TextChannel)
    bot.get_channel = MagicMock(return_value=channel)
    
    krovex_msg = MagicMock(spec=discord.Message)
    krovex_msg.author = MagicMock()
    krovex_msg.author.id = bot.user.id
    krovex_msg.add_reaction = AsyncMock()
    channel.fetch_message = AsyncMock(return_value=krovex_msg)
    
    # Raw reaction event
    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.user_id = user_id
    payload.guild_id = guild_id
    payload.channel_id = channel_id
    payload.message_id = message_id
    payload.emoji = "❤️"
    
    run_async(cog.on_raw_reaction_add(payload))
    
    krovex_msg.add_reaction.assert_awaited_once_with("🫂")


def test_reaction_without_active_session_ignored():
    """Verify reaction without active session is ignored."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.user_id = 111111111111111111
    payload.guild_id = 222222222222222222
    payload.channel_id = 333333333333333333
    payload.message_id = 777777777777777777
    payload.emoji = "❤️"
    
    # No session active
    run_async(cog.on_raw_reaction_add(payload))
    bot.get_channel.assert_not_called()


def test_deleted_or_unresolved_reply_reference():
    """Verify deleted or inaccessible reply references do not crash."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    ref = MagicMock(spec=discord.MessageReference)
    ref.resolved = None
    ref.message_id = 888888888888888888
    
    msg = make_mock_message(
        content="reply to deleted message",
        reference=ref,
    )
    msg.channel.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(), "Not Found"))
    
    run_async(cog.on_message(msg))
    bot.soul_service.generate_chat_reply.assert_not_awaited()


def test_provider_failure_friendly_message():
    """Verify provider errors return friendly Tanglish fallback."""
    bot = make_mock_bot()
    bot.soul_service.generate_chat_reply = AsyncMock(
        return_value=(None, "AI provider error: Rate limit 429")
    )
    cog = Soul(bot)
    
    msg = make_mock_message(
        content=f"<@{bot.user.id}> hi da",
        mentions=[bot.user],
    )
    run_async(cog.on_message(msg))
    
    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "Rate limit" not in reply_text
    assert "chinna connection issue" in reply_text


def test_owner_diagnostic_command():
    """Verify the !soultest command invokes the engine with diagnostic output."""
    bot = make_mock_bot()
    cog = Soul(bot)
    
    ctx = MagicMock(spec=commands.Context)
    ctx.guild = MagicMock()
    ctx.guild.id = 999
    ctx.guild.name = "Owner Server"
    ctx.channel = MagicMock()
    ctx.channel.id = 888
    ctx.author = MagicMock()
    ctx.author.id = 123456789012345678
    ctx.author.display_name = "OwnerKishore"
    ctx.typing = MagicMock(return_value=AsyncContextManagerMock())
    ctx.reply = AsyncMock()
    
    run_async(cog.soul_test.callback(cog, ctx, prompt="diagnostic test prompt"))
    
    bot.soul_service.generate_chat_reply.assert_awaited_once()
    call_kwargs = bot.soul_service.generate_chat_reply.call_args.kwargs
    assert call_kwargs["message_text"] == "diagnostic test prompt"
    assert call_kwargs["is_admin"] is True
    ctx.reply.assert_awaited_once()


# =============================================================================
# Phase 3.2: Identity Awareness & Third-Party Mention Protection Tests
# =============================================================================

def test_current_speaker_remains_when_third_party_mentioned():
    """Verify that when TheRealThor mentions Leon, the speaker identity remains TheRealThor."""
    bot = make_mock_bot()
    cog = Soul(bot)

    msg = make_mock_message(
        content=f"<@{bot.user.id}> leon anu lover daw",
        author_id=872384645373788170,
        author_name="TheRealThor",
        mentions=[bot.user],
    )
    run_async(cog.on_message(msg))

    bot.soul_service.generate_chat_reply.assert_awaited_once()
    kwargs = bot.soul_service.generate_chat_reply.call_args.kwargs
    assert kwargs["user_id"] == 872384645373788170
    assert kwargs["user_name"] == "TheRealThor"
    assert "leon anu lover daw" in kwargs["message_text"]

    # Verify system prompt establishes TheRealThor as authoritative speaker
    prompt = get_system_prompt(personality_style="tanglish_bro", user_name="TheRealThor")
    assert "Member Talking To You (Speaker): TheRealThor" in prompt
    assert "Member Talking To You (Speaker): Leon" not in prompt


def test_mentioning_third_party_does_not_replace_speaker_identity():
    """Verify mentioning members in prompt resolves display names but author remains speaker."""
    bot = make_mock_bot()
    cog = Soul(bot)

    leon_member = MagicMock(spec=discord.Member)
    leon_member.id = 1525834616764764212
    leon_member.display_name = "Leon"

    msg = make_mock_message(
        content=f"<@{bot.user.id}> check <@1525834616764764212> please",
        author_id=872384645373788170,
        author_name="TheRealThor",
        mentions=[bot.user, leon_member],
    )
    run_async(cog.on_message(msg))

    bot.soul_service.generate_chat_reply.assert_awaited_once()
    kwargs = bot.soul_service.generate_chat_reply.call_args.kwargs
    assert kwargs["user_name"] == "TheRealThor"
    assert "Leon" in kwargs["message_text"]
    assert "<@1525834616764764212>" not in kwargs["message_text"]


def test_asking_to_tag_third_party_does_not_produce_fake_tag():
    """Verify that fake simulated tags like @Leon or @Thor are stripped by output sanitizer."""
    raw_ai_text = "Dei @Leon, vandhu badhil sollu da! @Thor also asked!"
    sanitized = sanitize_ai_output(raw_ai_text)

    # Names must remain present, but fake @ prefixes must be stripped
    assert "@Leon" not in sanitized
    assert "@Thor" not in sanitized
    assert "Leon" in sanitized
    assert "Thor" in sanitized
    assert "Dei Leon, vandhu badhil sollu da! Thor also asked!" in sanitized


def test_asking_to_tag_user_does_not_confuse_recipient_and_speaker():
    """Verify asking to tag does not change Discord reply recipient from the actual author."""
    bot = make_mock_bot()
    cog = Soul(bot)

    msg = make_mock_message(
        content=f"<@{bot.user.id}> tag panu daw",
        author_id=872384645373788170,
        author_name="TheRealThor",
        mentions=[bot.user],
    )
    run_async(cog.on_message(msg))

    # Reply is sent directly to TheRealThor's message
    msg.reply.assert_awaited_once()
    call_kwargs = msg.reply.call_args.kwargs
    assert call_kwargs["allowed_mentions"].replied_user is True
    assert call_kwargs["allowed_mentions"].users is False


def test_previous_ai_responses_mentioning_third_parties_do_not_alter_speaker(tmp_path: Path):
    """Verify prior model turns addressing third parties do not alter user speaker attribution."""
    async def _test():
        db_path = tmp_path / "test_identity.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_path)
        await manager.connect()
        repo = SoulRepository(manager)
        
        captured_messages = []
        class CaptureProvider(BaseAIProvider):
            @property
            def is_configured(self) -> bool:
                return True
            async def generate_response(self, messages, system_prompt, **kwargs):
                nonlocal captured_messages
                captured_messages = list(messages)
                return AIResponse(content="Dei macha, unkitta dhaan pesuren da!", model="mock-model", success=True)
            async def close(self):
                pass

        service = SoulService(db=manager, repo=repo, provider=CaptureProvider())
        session = await repo.get_or_create_session(guild_id=1, channel_id=2, user_id=872384645373788170)

        # Seed conversation history where previous model response simulated @Leon
        await repo.add_message(session.session_id, role="user", content="leon anu lover daw")
        await repo.add_message(session.session_id, role="model", content="Dei @Leon, enna da silent-ah sambavam pan")

        # Now TheRealThor sends another turn
        reply, error = await service.generate_chat_reply(
            guild_id=1,
            channel_id=2,
            user_id=872384645373788170,
            user_name="TheRealThor",
            message_text="tag panu daw",
        )
        assert error is None
        assert reply is not None

        # Verify all user turns are attributed to [TheRealThor]
        user_turns = [m for m in captured_messages if m["role"] == "user"]
        assert len(user_turns) == 2
        assert user_turns[0]["content"] == "[TheRealThor]: leon anu lover daw"
        assert user_turns[1]["content"] == "[TheRealThor]: tag panu daw"
        assert "[Leon]" not in user_turns[0]["content"]
        assert "[Leon]" not in user_turns[1]["content"]

        await manager.close()

    run_async(_test())


def test_two_users_discussing_same_third_party_remain_isolated(tmp_path: Path):
    """Verify two users discussing the same topic in the same channel have completely isolated sessions."""
    async def _test():
        db_path = tmp_path / "test_multi_user.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_path)
        await manager.connect()
        repo = SoulRepository(manager)

        class EchoProvider(BaseAIProvider):
            @property
            def is_configured(self) -> bool:
                return True
            async def generate_response(self, messages, system_prompt, **kwargs):
                return AIResponse(content="Echo reply", model="mock-model", success=True)
            async def close(self):
                pass

        service = SoulService(db=manager, repo=repo, provider=EchoProvider())

        # User A (TheRealThor) talks about Leon
        await service.generate_chat_reply(
            guild_id=1, channel_id=2, user_id=101, user_name="TheRealThor", message_text="leon is my friend"
        )
        # User B (Groot) also talks about Leon
        await service.generate_chat_reply(
            guild_id=1, channel_id=2, user_id=102, user_name="Groot", message_text="leon is studying"
        )

        history_a = await repo.get_recent_messages("1:2:101", limit=10)
        history_b = await repo.get_recent_messages("1:2:102", limit=10)

        assert len(history_a) == 2
        assert "leon is my friend" in history_a[0].content
        assert len(history_b) == 2
        assert "leon is studying" in history_b[0].content

        await manager.close()

    run_async(_test())


def test_existing_conversation_history_remains_correctly_attributed(tmp_path: Path):
    """Verify raw SQLite storage is preserved while provider messages receive speaker labels."""
    async def _test():
        db_path = tmp_path / "test_attribution.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_path)
        await manager.connect()
        repo = SoulRepository(manager)

        captured_messages = []
        class CaptureProvider(BaseAIProvider):
            @property
            def is_configured(self) -> bool:
                return True
            async def generate_response(self, messages, system_prompt, **kwargs):
                nonlocal captured_messages
                captured_messages = list(messages)
                return AIResponse(content="I hear you da!", model="mock-model", success=True)
            async def close(self):
                pass

        service = SoulService(db=manager, repo=repo, provider=CaptureProvider())

        await service.generate_chat_reply(
            guild_id=1, channel_id=2, user_id=101, user_name="Kishore", message_text="Vanakkam da"
        )

        # Database stores raw un-prefixed content
        db_messages = await repo.get_recent_messages("1:2:101", limit=10)
        assert db_messages[0].content == "Vanakkam da"
        assert not db_messages[0].content.startswith("[Kishore]:")

        # Provider received formatted speaker attribution
        assert captured_messages[0]["content"] == "[Kishore]: Vanakkam da"

        await manager.close()

    run_async(_test())


def test_neutral_fallback_when_display_name_unavailable():
    """Verify neutral fallback 'machaww' when user display name and username are empty."""
    prompt = get_system_prompt(personality_style="tanglish_bro", user_name="", username=None)
    assert "machaww" in prompt
    assert "Member Talking To You (Speaker): machaww" in prompt


def test_ordinary_discussion_of_third_party_names_remains_possible():
    """Verify ordinary names of third parties, anime characters, and games are never stripped."""
    normal_text = "Dei macha, Leon and Anu are hanging out with Goku and Naruto in Chennai!"
    sanitized = sanitize_ai_output(normal_text)
    assert sanitized == normal_text
    assert "Leon" in sanitized
    assert "Anu" in sanitized
    assert "Goku" in sanitized
    assert "Naruto" in sanitized


def test_discord_allowed_mentions_protection_remains_enabled():
    """Verify AllowedMentions strictly prevents user and role pings while allowing author reply ping."""
    bot = make_mock_bot()
    cog = Soul(bot)

    msg = make_mock_message(
        content=f"<@{bot.user.id}> ping test",
        mentions=[bot.user],
    )
    run_async(cog.on_message(msg))

    msg.reply.assert_awaited_once()
    mentions: discord.AllowedMentions = msg.reply.call_args.kwargs["allowed_mentions"]
    assert mentions.replied_user is True
    assert mentions.users is False
    assert mentions.roles is False
    assert mentions.everyone is False
