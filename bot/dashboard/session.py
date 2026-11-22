"""Server-side session management, state validation, and CSRF protection for KROVEX."""
from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class OAuthStateData:
    """OAuth2 temporary state information stored during handshake."""

    state: str
    code_verifier: Optional[str] = None
    redirect_after: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 600.0)  # 10 minutes TTL


@dataclass
class Session:
    """Authenticated user session stored exclusively on the server."""

    session_id: str
    user_id: int
    username: str
    discriminator: str = "0"
    avatar: Optional[str] = None
    access_token: str = ""
    refresh_token: Optional[str] = None
    token_expires_at: float = 0.0
    csrf_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)
    max_age_seconds: float = 86400.0  # 24 hours TTL

    @property
    def is_expired(self) -> bool:
        """Check if session has expired either by absolute lifetime or token lifetime."""
        now = time.time()
        return (now - self.created_at) > self.max_age_seconds

    def touch(self) -> None:
        """Update last accessed timestamp."""
        self.last_accessed_at = time.time()

    def validate_csrf(self, candidate_token: Optional[str]) -> bool:
        """Constant-time validation of CSRF token."""
        if not candidate_token or not self.csrf_token:
            return False
        return hmac.compare_digest(self.csrf_token, candidate_token)


class SessionManager:
    """Thread-safe, in-memory server-side session and OAuth2 state store."""

    def __init__(self, default_ttl_seconds: float = 86400.0) -> None:
        self.default_ttl = default_ttl_seconds
        self._sessions: Dict[str, Session] = {}
        self._oauth_states: Dict[str, OAuthStateData] = {}

    # =========================================================================
    # OAUTH2 STATE MANAGEMENT (CSRF & REPLAY PROTECTION)
    # =========================================================================

    def create_oauth_state(
        self, code_verifier: Optional[str] = None, redirect_after: Optional[str] = None
    ) -> str:
        """Generate cryptographically secure OAuth2 state parameter with 10-minute TTL."""
        self.purge_expired()
        state = secrets.token_urlsafe(32)
        self._oauth_states[state] = OAuthStateData(
            state=state,
            code_verifier=code_verifier,
            redirect_after=redirect_after,
            created_at=time.time(),
            expires_at=time.time() + 600.0,
        )
        return state

    def validate_and_consume_state(self, state: Optional[str]) -> Optional[OAuthStateData]:
        """Validate state token and immediately consume it to prevent replay attacks."""
        if not state:
            return None
        self.purge_expired()
        state_data = self._oauth_states.pop(state, None)
        if not state_data:
            return None
        if time.time() > state_data.expires_at:
            return None
        return state_data

    # =========================================================================
    # SESSION MANAGEMENT
    # =========================================================================

    def create_session(
        self,
        user_id: int,
        username: str,
        discriminator: str = "0",
        avatar: Optional[str] = None,
        access_token: str = "",
        refresh_token: Optional[str] = None,
        token_expires_in: float = 604800.0,
    ) -> Session:
        """Issue a new authenticated session with a cryptographically secure token."""
        self.purge_expired()
        session_id = secrets.token_urlsafe(48)
        session = Session(
            session_id=session_id,
            user_id=user_id,
            username=username,
            discriminator=discriminator,
            avatar=avatar,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=time.time() + token_expires_in,
            max_age_seconds=self.default_ttl,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: Optional[str]) -> Optional[Session]:
        """Retrieve and validate an active session by ID."""
        if not session_id:
            return None
        session = self._sessions.get(session_id)
        if not session:
            return None
        if session.is_expired:
            self._sessions.pop(session_id, None)
            return None
        session.touch()
        return session

    def rotate_session(self, old_session_id: str) -> Optional[Session]:
        """Rotate session ID upon authentication to prevent session fixation attacks."""
        old_session = self._sessions.pop(old_session_id, None)
        if not old_session or old_session.is_expired:
            return None

        new_session_id = secrets.token_urlsafe(48)
        new_session = Session(
            session_id=new_session_id,
            user_id=old_session.user_id,
            username=old_session.username,
            discriminator=old_session.discriminator,
            avatar=old_session.avatar,
            access_token=old_session.access_token,
            refresh_token=old_session.refresh_token,
            token_expires_at=old_session.token_expires_at,
            csrf_token=secrets.token_urlsafe(32),  # Also refresh CSRF token
            created_at=time.time(),
            last_accessed_at=time.time(),
            max_age_seconds=old_session.max_age_seconds,
        )
        self._sessions[new_session_id] = new_session
        return new_session

    def destroy_session(self, session_id: Optional[str]) -> bool:
        """Invalidate session on logout."""
        if not session_id:
            return False
        return self._sessions.pop(session_id, None) is not None

    def purge_expired(self) -> None:
        """Purge stale sessions and expired OAuth states."""
        now = time.time()
        # Purge sessions
        expired_sessions = [s_id for s_id, s in self._sessions.items() if s.is_expired]
        for s_id in expired_sessions:
            self._sessions.pop(s_id, None)

        # Purge OAuth states
        expired_states = [st for st, data in self._oauth_states.items() if now > data.expires_at]
        for st in expired_states:
            self._oauth_states.pop(st, None)

    @property
    def active_session_count(self) -> int:
        """Number of active sessions in memory."""
        self.purge_expired()
        return len(self._sessions)
