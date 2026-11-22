"""KROVEX SOUL Conversation Service.

Orchestrates multi-tenant conversational sessions, rates and cooldowns, sliding-window
memory assembly, personality instruction rendering, and AI provider calls.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import discord

from bot.database.models import SoulGuildSettingsModel, SoulSessionModel
from bot.database.repositories.soul_repo import SoulRepository
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.services.ai.base_provider import BaseAIProvider
from bot.services.ai.intent_resolver import IntentResolver, ResolvedIntent
from bot.services.ai.personality import get_system_prompt, sanitize_ai_output
from bot.services.ai.session_manager import SessionManager, SoulSessionState
from bot.services.ai.tools import ToolDefinition, ToolRegistry, ToolResult
from bot.utils.logger import get_logger

logger = get_logger("death_bot.ai.soul_service")


class SoulService:
    """Core domain service for KROVEX SOUL AI conversations and autonomous action execution."""

    def __init__(
        self,
        db: SQLiteDatabaseManager,
        repo: SoulRepository,
        provider: BaseAIProvider,
        timeout: float = 12.0,
        default_cooldown: float = 3.0,
        bot: Optional[Any] = None,
    ) -> None:
        self.db = db
        self.repo = repo
        self.provider = provider
        self.timeout = timeout
        self.default_cooldown = default_cooldown
        self.bot = bot
        self.tools: Optional[ToolRegistry] = ToolRegistry(bot) if bot else None
        self.intent_resolver = IntentResolver()
        self.session_manager = SessionManager(default_timeout_seconds=300.0)
        # In-memory cooldown tracker: (guild_id, user_id) -> expiry_monotonic
        self._user_cooldowns: Dict[Tuple[int, int], float] = {}
        # Concurrency locks per (guild_id, user_id) to serialize same-user requests atomically
        self._user_locks: Dict[Tuple[int, int], asyncio.Lock] = {}
        self._map_lock = asyncio.Lock()
        # Active conversational continuity tracking: (guild_id, channel_id, user_id) -> last_activity_monotonic
        self._active_sessions: Dict[Tuple[int, int, int], float] = {}

    def bind_bot(self, bot: Any) -> None:
        """Bind DeathBot instance to enable tool execution across cogs."""
        self.bot = bot
        self.tools = ToolRegistry(bot)

    def activate_session(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        user_name: str = "User",
        timeout_seconds: Optional[float] = None,
    ) -> None:
        """Mark or refresh conversation session as actively chatting."""
        key = (guild_id, channel_id, user_id)
        now = time.monotonic()
        self._active_sessions[key] = now
        self.session_manager.activate_session(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            user_name=user_name,
            timeout_seconds=timeout_seconds,
        )

    def end_session(self, guild_id: int, channel_id: int, user_id: int) -> bool:
        """Explicitly end and deactivate the conversation session."""
        key = (guild_id, channel_id, user_id)
        self.session_manager.end_session(guild_id, channel_id, user_id)
        return self._active_sessions.pop(key, None) is not None

    def is_session_active(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        timeout_minutes: int = 5,
    ) -> bool:
        """Check if user has an active conversation session in this channel within inactivity timeout."""
        key = (guild_id, channel_id, user_id)
        last_time = self._active_sessions.get(key)
        if last_time is None:
            return False

        if time.monotonic() - last_time > (timeout_minutes * 60):
            self._active_sessions.pop(key, None)
            self.session_manager.end_session(guild_id, channel_id, user_id)
            return False

        return True

    async def process_natural_language_request(
        self,
        bot: Any,
        message: discord.Message,
        clean_prompt: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Process conversational or action request using intent resolution, permissions, and tool execution."""
        guild = message.guild
        channel = message.channel
        author = message.author
        if not guild or not isinstance(author, discord.Member):
            return None, "Only server messages can be processed."

        if not self.tools:
            self.tools = ToolRegistry(bot)

        from bot.core.context import UnifiedContext

        # Retrieve active session or activate
        session = self.session_manager.get_session(guild.id, channel.id, author.id)
        if not session:
            session = self.session_manager.activate_session(
                guild.id, channel.id, author.id, user_name=author.display_name
            )
        else:
            session.touch()
        self.activate_session(guild.id, channel.id, author.id, user_name=author.display_name)

        has_pending = bool(session.pending_confirmation and not session.pending_confirmation.is_expired())

        # Resolve intent
        intent = self.intent_resolver.resolve(
            text=clean_prompt,
            guild=guild,
            author=author,
            last_action=session.last_action,
            last_target_member=session.last_target_member,
            has_pending_confirmation=has_pending,
        )

        # 1. Termination Intent
        if intent.intent_type == "termination":
            self.end_session(guild.id, channel.id, author.id)
            return "Done! 👋 Session ended. Talk to you later!", None

        # 2. Cancellation Intent
        if intent.intent_type == "cancellation":
            self.session_manager.clear_pending_confirmation(guild.id, channel.id, author.id)
            return "Understood. The action has been cancelled.", None

        # 3. Confirmation Intent
        if intent.intent_type == "confirmation" and has_pending:
            pending = self.session_manager.clear_pending_confirmation(guild.id, channel.id, author.id)
            if not pending:
                return "The confirmation request has expired.", None

            tool = self.tools.get_tool(pending.tool_name)
            if not tool or not tool.executor:
                return None, f"Tool `{pending.tool_name}` is not registered."

            target_member = pending.args.get("target")
            allowed, perm_err = self.tools.check_permissions(tool, author, channel, target_member)
            if not allowed:
                return perm_err, None

            prefix_ctx = await bot.get_context(message)
            ctx = UnifiedContext.from_prefix(prefix_ctx)

            try:
                res = await tool.executor(ctx, **pending.args)
                session.last_action = tool.name
                if target_member:
                    session.last_target_member = target_member
                return res.message, None if res.success else res.message
            except Exception as e:
                logger.error("SOUL confirmed execution error: %s", e)
                return None, f"Execution failed: {e}"

        # 4. Action Intent
        if intent.intent_type == "action":
            if intent.clarification_question:
                return intent.clarification_question, None

            if not intent.tool_name:
                return None, "Could not determine the intended action."

            tool = self.tools.get_tool(intent.tool_name)
            if not tool or not tool.executor:
                return None, f"Tool `{intent.tool_name}` is not available."

            target_member = intent.args.get("target")
            allowed, perm_err = self.tools.check_permissions(tool, author, channel, target_member)
            if not allowed:
                return perm_err, None  # User-friendly permission denial message

            # Check if confirmation is required
            if tool.requires_confirmation:
                target_name = target_member.display_name if target_member else intent.args.get("count", "the selected items")
                prompt_text = tool.confirmation_prompt.format(target=target_name, count=intent.args.get("count", 10))
                self.session_manager.set_pending_confirmation(
                    guild.id, channel.id, author.id,
                    tool_name=tool.name,
                    args=intent.args,
                    prompt=prompt_text,
                )
                return f"{prompt_text}\n*(Reply **yes** to proceed, or **no** to cancel)*", None

            # Execute action immediately
            prefix_ctx = await bot.get_context(message)
            ctx = UnifiedContext.from_prefix(prefix_ctx)

            try:
                res = await tool.executor(ctx, **intent.args)
                session.last_action = tool.name
                if target_member:
                    session.last_target_member = target_member
                return res.message, None if res.success else res.message
            except Exception as e:
                logger.error("SOUL action execution error: %s", e)
                return None, f"Execution failed: {e}"

        # 5. Pure Conversation Fallback
        return await self.generate_chat_reply(
            guild_id=guild.id,
            channel_id=channel.id,
            user_id=author.id,
            user_name=author.display_name,
            message_text=clean_prompt,
            server_name=guild.name,
            channel_name=channel.name,
            username=author.name,
            is_admin=author.guild_permissions.administrator,
        )

    async def _get_user_lock(self, guild_id: int, user_id: int) -> asyncio.Lock:
        """Get or initialize a user-specific lock safely."""
        key = (guild_id, user_id)
        if key not in self._user_locks:
            async with self._map_lock:
                if key not in self._user_locks:
                    self._user_locks[key] = asyncio.Lock()
        return self._user_locks[key]

    def check_user_cooldown(self, guild_id: int, user_id: int, cooldown_seconds: float) -> Tuple[bool, float]:
        """Check if user is on chat cooldown. Returns (can_chat, retry_after)."""
        if cooldown_seconds <= 0:
            return True, 0.0

        key = (guild_id, user_id)
        now = time.monotonic()
        expiry = self._user_cooldowns.get(key, 0.0)

        if now < expiry:
            retry_after = round(expiry - now, 1)
            return False, max(retry_after, 0.1)

        return True, 0.0

    def apply_user_cooldown(self, guild_id: int, user_id: int, cooldown_seconds: float) -> None:
        """Apply active cooldown timestamp for user."""
        if cooldown_seconds > 0:
            key = (guild_id, user_id)
            self._user_cooldowns[key] = time.monotonic() + cooldown_seconds

    def clear_user_cooldown(self, guild_id: int, user_id: int) -> None:
        """Release or clear active cooldown timestamp for user."""
        key = (guild_id, user_id)
        self._user_cooldowns.pop(key, None)

    async def generate_chat_reply(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        user_name: str,
        message_text: str,
        server_name: Optional[str] = None,
        channel_name: Optional[str] = None,
        username: Optional[str] = None,
        is_admin: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Process conversational input, maintain memory, invoke AI provider, and return sanitized reply."""
        # Step 1: Input sanity checks
        if not message_text or not message_text.strip():
            return None, "Empty message text provided."

        clean_text = message_text.strip()
        # Bound excessively long inputs to prevent token exhaustion (max 1500 chars)
        if len(clean_text) > 1500:
            clean_text = clean_text[:1500]

        # Resolve trusted speaker identity with neutral fallback
        effective_user_name = (user_name or "").strip()
        if not effective_user_name:
            effective_user_name = (username or "").strip()
        if not effective_user_name:
            effective_user_name = "machaww"

        # Step 2: Guild configuration check
        settings = await self.repo.get_guild_settings(guild_id)
        if not settings.enabled:
            return None, "KROVEX SOUL is currently disabled in this server."

        if settings.allowed_channels and channel_id not in settings.allowed_channels:
            return None, "KROVEX SOUL is not permitted in this channel."

        # Step 3: Provider readiness check
        if not self.provider.is_configured:
            return None, "AI provider is not configured. Please add GEMINI_API_KEY to environment."

        # Step 4: Atomic Check-and-Reserve Cooldown under user lock
        user_lock = await self._get_user_lock(guild_id, user_id)
        if user_lock.locked():
            # If user has an in-flight request right now, reject concurrent attempt immediately
            return None, f"Chill macha! Please wait {settings.cooldown_seconds}s before messaging again."

        async with user_lock:
            can_chat, retry_after = self.check_user_cooldown(guild_id, user_id, settings.cooldown_seconds)
            if not can_chat:
                return None, f"Chill macha! Please wait {retry_after}s before messaging again."

            # Optimistically reserve cooldown BEFORE awaiting provider
            self.apply_user_cooldown(guild_id, user_id, settings.cooldown_seconds)

            # Step 5: Session retrieval & expiration handling
            session = await self.repo.get_or_create_session(guild_id, channel_id, user_id)
            if await self.repo.is_session_expired(session, timeout_minutes=30):
                # Session expired: wipe old messages for fresh start
                await self.repo.clear_session_messages(session.session_id)

            # Step 6: Append user message & capture pending message ID for rollback safety
            user_msg = await self.repo.add_message(session.session_id, role="user", content=clean_text)
            pending_msg_id = user_msg.id
            await self.repo.prune_session_history(session.session_id, keep_latest=settings.max_history_turns)

            # Step 7: Assemble conversation context with explicit speaker attribution
            history = await self.repo.get_recent_messages(session.session_id, limit=settings.max_history_turns)
            formatted_messages: List[Dict[str, str]] = []
            for m in history:
                if m.role in ("user", "human"):
                    content_str = m.content
                    if not content_str.startswith(f"[{effective_user_name}]:"):
                        content_str = f"[{effective_user_name}]: {content_str}"
                    formatted_messages.append({"role": "user", "content": content_str})
                else:
                    formatted_messages.append({"role": "model", "content": m.content})

            # Step 8: Build system instruction & invoke AI provider
            system_prompt = get_system_prompt(
                personality_style=settings.personality_style,
                server_name=server_name,
                user_name=effective_user_name,
                user_id=user_id,
                channel_name=channel_name,
                username=username,
            )

            try:
                response = await self.provider.generate_response(
                    messages=formatted_messages,
                    system_prompt=system_prompt,
                    temperature=0.8,
                    max_tokens=400,
                    timeout=self.timeout,
                )
            except (Exception, asyncio.CancelledError) as exc:
                # Rollback pending user message on exception or cancellation
                if pending_msg_id is not None:
                    await self.repo.delete_message(pending_msg_id)
                # Release cooldown on error so user is not penalized for system failure
                self.clear_user_cooldown(guild_id, user_id)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                logger.error("Error during AI provider generation: %s", exc)
                return None, f"AI provider error: {type(exc).__name__}"

            if not response.success:
                logger.warning("AI provider failed for guild %d user %d: %s", guild_id, user_id, response.error)
                # Rollback pending user message so failed turn does not corrupt history
                if pending_msg_id is not None:
                    await self.repo.delete_message(pending_msg_id)
                # Release cooldown on provider failure
                self.clear_user_cooldown(guild_id, user_id)
                return None, response.error or "AI provider encountered an error."

            # Step 9: Sanitize output and record assistant response
            sanitized_reply = sanitize_ai_output(response.content)
            if sanitized_reply:
                await self.repo.add_message(session.session_id, role="model", content=sanitized_reply)
                await self.repo.prune_session_history(session.session_id, keep_latest=settings.max_history_turns)
                self.activate_session(guild_id, channel_id, user_id)
            else:
                # Empty reply from model: rollback pending user turn
                if pending_msg_id is not None:
                    await self.repo.delete_message(pending_msg_id)
                self.clear_user_cooldown(guild_id, user_id)
                return None, "Empty response generated by AI provider."

            return sanitized_reply, None

    async def forget_user_memory(
        self,
        guild_id: int,
        user_id: int,
        channel_id: Optional[int] = None,
    ) -> int:
        """Purge all conversational history and session records for a user."""
        keys_to_remove = [
            k for k in self._active_sessions
            if k[0] == guild_id and k[2] == user_id and (channel_id is None or k[1] == channel_id)
        ]
        for k in keys_to_remove:
            self._active_sessions.pop(k, None)
        return await self.repo.delete_user_session(guild_id, user_id, channel_id=channel_id)

    async def reset_server_memory(
        self,
        guild_id: int,
        requester_is_admin: bool,
    ) -> Tuple[bool, str]:
        """Authorized server-wide conversation memory wipe."""
        if not requester_is_admin:
            return False, "Unauthorized: Server Administrator permission required to reset server memory."

        keys_to_remove = [k for k in self._active_sessions if k[0] == guild_id]
        for k in keys_to_remove:
            self._active_sessions.pop(k, None)

        deleted = await self.repo.delete_guild_sessions(guild_id)
        return True, f"Successfully purged {deleted} active conversation session(s) for this server."

    async def update_guild_settings(self, guild_id: int, **kwargs: Any) -> SoulGuildSettingsModel:
        """Update guild AI settings."""
        return await self.repo.update_guild_settings(guild_id, **kwargs)

    async def get_guild_settings(self, guild_id: int) -> SoulGuildSettingsModel:
        """Get guild AI settings."""
        return await self.repo.get_guild_settings(guild_id)
