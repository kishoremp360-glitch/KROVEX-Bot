"""KROVEX SOUL Session Manager.

Provides multi-tenant, isolated conversation sessions scoped to (guild_id, channel_id, user_id)
with configurable inactivity timeouts, context memory, and safe confirmation lifecycle management.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import discord

from bot.utils.logger import get_logger

logger = get_logger("death_bot.ai.session_manager")


@dataclass
class PendingConfirmation:
    """Represents a dangerous action awaiting explicit confirmation."""
    tool_name: str
    args: Dict[str, Any]
    prompt: str
    created_at: float = field(default_factory=time.monotonic)
    timeout_seconds: float = 60.0

    def is_expired(self) -> bool:
        """True if the confirmation prompt has timed out."""
        return (time.monotonic() - self.created_at) > self.timeout_seconds


@dataclass
class SoulSessionState:
    """In-memory active conversational session state for a member in a specific channel."""
    guild_id: int
    channel_id: int
    user_id: int
    user_name: str
    created_at: float = field(default_factory=time.monotonic)
    last_activity_at: float = field(default_factory=time.monotonic)
    timeout_seconds: float = 300.0  # 5 minutes default
    last_action: Optional[str] = None
    last_target_member: Optional[discord.Member] = None
    last_query: Optional[str] = None
    pending_confirmation: Optional[PendingConfirmation] = None

    def is_expired(self, custom_timeout: Optional[float] = None) -> bool:
        """True if the session has exceeded its inactivity threshold."""
        effective_timeout = custom_timeout if custom_timeout is not None else self.timeout_seconds
        return (time.monotonic() - self.last_activity_at) > effective_timeout

    def touch(self) -> None:
        """Reset inactivity timer on message activity."""
        self.last_activity_at = time.monotonic()


class SessionManager:
    """Manages active SOUL sessions with strict isolation and lazy sweep cleanup."""

    def __init__(self, default_timeout_seconds: float = 300.0) -> None:
        self.default_timeout_seconds = default_timeout_seconds
        # Key: (guild_id, channel_id, user_id)
        self._sessions: Dict[Tuple[int, int, int], SoulSessionState] = {}
        self._last_sweep = time.monotonic()

    def get_session(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[SoulSessionState]:
        """Retrieve an active session if it exists and has not expired."""
        self._maybe_sweep()
        key = (guild_id, channel_id, user_id)
        session = self._sessions.get(key)
        if not session:
            return None

        eff_timeout = timeout_seconds if timeout_seconds is not None else session.timeout_seconds
        if session.is_expired(eff_timeout):
            self._sessions.pop(key, None)
            return None

        return session

    def activate_session(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        user_name: str,
        timeout_seconds: Optional[float] = None,
    ) -> SoulSessionState:
        """Create or refresh an active conversational session."""
        key = (guild_id, channel_id, user_id)
        effective_timeout = timeout_seconds or self.default_timeout_seconds
        session = self._sessions.get(key)
        if session and not session.is_expired(effective_timeout):
            session.touch()
            session.user_name = user_name
            session.timeout_seconds = effective_timeout
            return session

        new_session = SoulSessionState(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            user_name=user_name,
            timeout_seconds=effective_timeout,
        )
        self._sessions[key] = new_session
        return new_session

    def end_session(self, guild_id: int, channel_id: int, user_id: int) -> bool:
        """Explicitly terminate an active session."""
        key = (guild_id, channel_id, user_id)
        return self._sessions.pop(key, None) is not None

    def is_session_active(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """Check if an unexpired session exists for the user."""
        return self.get_session(guild_id, channel_id, user_id, timeout_seconds) is not None

    def set_pending_confirmation(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        tool_name: str,
        args: Dict[str, Any],
        prompt: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        """Attach a pending dangerous action awaiting explicit confirmation."""
        session = self.get_session(guild_id, channel_id, user_id)
        if session:
            session.pending_confirmation = PendingConfirmation(
                tool_name=tool_name,
                args=args,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
            )

    def clear_pending_confirmation(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
    ) -> Optional[PendingConfirmation]:
        """Clear and return any pending confirmation."""
        session = self.get_session(guild_id, channel_id, user_id)
        if session and session.pending_confirmation:
            pending = session.pending_confirmation
            session.pending_confirmation = None
            if not pending.is_expired():
                return pending
        return None

    def _maybe_sweep(self) -> None:
        """Periodically purge expired sessions without heavy looping."""
        now = time.monotonic()
        if now - self._last_sweep < 60.0:  # Sweep at most once every minute
            return
        self._last_sweep = now
        expired_keys = [
            k for k, sess in self._sessions.items()
            if sess.is_expired()
        ]
        for k in expired_keys:
            self._sessions.pop(k, None)
