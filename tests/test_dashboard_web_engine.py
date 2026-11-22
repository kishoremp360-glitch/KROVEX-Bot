"""Comprehensive test suite for Phase 2A.9.1: OAuth2 Authentication & Web Server Engine.

Verifies:
1. OAuth2 login URL generation.
2. State generation and validation.
3. Invalid state rejection.
4. Replayed state rejection.
5. Authorization callback.
6. Invalid authorization code handling.
7. Session creation and rotation.
8. Session expiration.
9. Logout invalidation.
10. Cookie security attributes.
11. Unauthorized route rejection.
12. Guild membership verification.
13. Manage Server permission verification.
14. Cross-server access rejection.
15. Discord API failure handling.
16. CSRF rejection.
17. Web server startup.
18. Web server shutdown.
19. Port conflict handling.
20. Existing bot regression compatibility (verified across full suite).
"""
from __future__ import annotations

import socket
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.dashboard.oauth import (
    PERM_ADMINISTRATOR,
    PERM_MANAGE_GUILD,
    DiscordOAuth2Client,
    generate_pkce_pair,
    has_manage_guild_permission,
)
from bot.dashboard.server import (
    SESSION_COOKIE_NAME,
    DashboardServer,
    require_auth,
    require_csrf,
)
from bot.dashboard.session import Session, SessionManager


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_bot():
    """Create a realistic mock DeathBot instance."""
    bot = MagicMock()
    bot.config.client_id = 123456789012345678
    bot.config.discord_client_secret = "test_client_secret_xyz"
    bot.config.dashboard_redirect_uri = "http://localhost:8080/callback"
    bot.config.is_production = False
    bot.is_ready.return_value = True
    bot.session = None

    mock_guild = MagicMock()
    mock_guild.id = 999888777
    mock_guild.name = "Krovex Test Guild"
    bot.get_guild.side_effect = lambda g_id: mock_guild if g_id == 999888777 else None
    return bot


# =============================================================================
# 1. OAUTH2 LOGIN URL GENERATION
# =============================================================================

def test_01_oauth2_login_url_generation():
    """Test 1: Verify Discord OAuth2 login URL contains correct scopes, client_id, and PKCE challenge."""
    client = DiscordOAuth2Client(
        client_id=123456789012345678,
        client_secret="secret",
        redirect_uri="http://localhost:8080/callback",
    )
    code_verifier, code_challenge = generate_pkce_pair()
    url = client.get_authorization_url(state="test_state_123", code_challenge=code_challenge)

    assert "https://discord.com/oauth2/authorize" in url
    assert "client_id=123456789012345678" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fcallback" in url
    assert "scope=identify+guilds" in url
    assert "state=test_state_123" in url
    assert f"code_challenge={code_challenge}" in url
    assert "code_challenge_method=S256" in url


# =============================================================================
# 2. STATE GENERATION AND VALIDATION
# =============================================================================

def test_02_state_generation_and_validation():
    """Test 2: Verify cryptographically secure state generation, storage, and consumption."""
    manager = SessionManager()
    state = manager.create_oauth_state(code_verifier="test_verifier", redirect_after="/dashboard")

    assert state is not None
    assert len(state) >= 32

    state_data = manager.validate_and_consume_state(state)
    assert state_data is not None
    assert state_data.code_verifier == "test_verifier"
    assert state_data.redirect_after == "/dashboard"


# =============================================================================
# 3. INVALID STATE REJECTION
# =============================================================================

def test_03_invalid_state_rejection():
    """Test 3: Verify that an invalid or non-existent state is rejected."""
    manager = SessionManager()
    manager.create_oauth_state(code_verifier="valid_verifier")

    assert manager.validate_and_consume_state("completely_invalid_state") is None
    assert manager.validate_and_consume_state(None) is None
    assert manager.validate_and_consume_state("") is None


# =============================================================================
# 4. REPLAYED STATE REJECTION
# =============================================================================

def test_04_replayed_state_rejection():
    """Test 4: Verify that a state cannot be replayed (strictly single-use)."""
    manager = SessionManager()
    state = manager.create_oauth_state(code_verifier="verifier_1")

    # First consumption succeeds
    first_attempt = manager.validate_and_consume_state(state)
    assert first_attempt is not None

    # Second consumption must fail (replay attack prevented)
    second_attempt = manager.validate_and_consume_state(state)
    assert second_attempt is None


# =============================================================================
# 5. AUTHORIZATION CALLBACK
# =============================================================================

@pytest.mark.asyncio
async def test_05_authorization_callback(mock_bot):
    """Test 5: Verify authorization callback exchanges code and issues session redirect."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    app = server.app

    state = server.session_manager.create_oauth_state(
        code_verifier="test_pkce_verifier", redirect_after="/dashboard"
    )
    server.oauth_client.exchange_code = AsyncMock(
        return_value={"access_token": "valid_token_xyz", "expires_in": 3600}
    )
    server.oauth_client.fetch_user_profile = AsyncMock(
        return_value={"id": "555666777", "username": "DiscordMaster", "avatar": "hash_123"}
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get(
            f"/callback?code=mock_discord_code&state={state}",
            allow_redirects=False,
        )
        assert resp.status == 302
        assert resp.headers["Location"] == "/dashboard"
        assert SESSION_COOKIE_NAME in resp.cookies
    finally:
        await client.close()


# =============================================================================
# 6. INVALID AUTHORIZATION CODE HANDLING
# =============================================================================

@pytest.mark.asyncio
async def test_06_invalid_authorization_code_handling(mock_bot):
    """Test 6: Verify error handling when authorization code exchange fails."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    app = server.app

    state = server.session_manager.create_oauth_state(code_verifier="verifier")
    server.oauth_client.exchange_code = AsyncMock(return_value=None)  # Discord rejected code

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get(
            f"/callback?code=bad_code&state={state}",
            allow_redirects=False,
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["error"] == "TokenExchangeFailed"
    finally:
        await client.close()


# =============================================================================
# 7. SESSION CREATION AND ROTATION
# =============================================================================

def test_07_session_creation_and_rotation():
    """Test 7: Verify session creation, token isolation, and session ID rotation."""
    manager = SessionManager()
    session = manager.create_session(
        user_id=111222333,
        username="KrovexUser",
        avatar="avatar_hash",
        access_token="mock_access_token",
    )

    old_session_id = session.session_id
    assert manager.get_session(old_session_id) is not None

    new_session = manager.rotate_session(old_session_id)
    assert new_session is not None
    assert new_session.session_id != old_session_id
    assert new_session.user_id == 111222333

    assert manager.get_session(old_session_id) is None
    assert manager.get_session(new_session.session_id) is not None


# =============================================================================
# 8. SESSION EXPIRATION
# =============================================================================

def test_08_session_expiration():
    """Test 8: Verify that expired sessions return None and are purged."""
    manager = SessionManager(default_ttl_seconds=0.1)
    session = manager.create_session(user_id=123, username="EphemeralUser")

    assert manager.get_session(session.session_id) is not None

    time.sleep(0.15)

    assert manager.get_session(session.session_id) is None
    assert manager.active_session_count == 0


# =============================================================================
# 9. LOGOUT SECURITY & INVALIDATION (PHASE 2A.9.1.1 PATCH)
# =============================================================================

@pytest.mark.asyncio
async def test_09a_get_logout_cannot_destroy_session(mock_bot):
    """Test 9a: Verify GET /logout is rejected (405 Method Not Allowed) and leaves session intact."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    app = server.app

    session = server.session_manager.create_session(user_id=123, username="LogoutUser")
    session_id = session.session_id

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        client.session.cookie_jar.update_cookies({SESSION_COOKIE_NAME: session_id})

        # GET /logout must be rejected and cannot destroy session
        resp = await client.get("/logout")
        assert resp.status == 405  # Method Not Allowed

        # Session must remain fully intact in memory
        assert server.session_manager.get_session(session_id) is not None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_09b_post_logout_without_auth_rejected(mock_bot):
    """Test 9b: Verify POST /logout without session authentication is rejected (401)."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        resp = await client.post("/logout")
        assert resp.status == 401
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_09c_post_logout_without_csrf_rejected(mock_bot):
    """Test 9c: Verify POST /logout without valid CSRF token is rejected (403) and session preserved."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    session = server.session_manager.create_session(user_id=123, username="LogoutUser")
    session_id = session.session_id

    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        client.session.cookie_jar.update_cookies({SESSION_COOKIE_NAME: session_id})

        # Missing CSRF
        resp_no_csrf = await client.post("/logout")
        assert resp_no_csrf.status == 403

        # Invalid CSRF
        resp_bad_csrf = await client.post("/logout", headers={"X-CSRF-Token": "bad_token"})
        assert resp_bad_csrf.status == 403

        # Session remains intact
        assert server.session_manager.get_session(session_id) is not None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_09d_post_logout_with_valid_auth_and_csrf_succeeds(mock_bot):
    """Test 9d: Verify POST /logout with valid auth and CSRF destroys session and clears cookie."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    session = server.session_manager.create_session(user_id=123, username="LogoutUser")
    session_id = session.session_id

    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        client.session.cookie_jar.update_cookies({SESSION_COOKIE_NAME: session_id})

        resp = await client.post(
            "/logout",
            headers={"X-CSRF-Token": session.csrf_token, "Accept": "application/json"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True

        # Server session destroyed
        assert server.session_manager.get_session(session_id) is None

        # Cookie deleted
        assert SESSION_COOKIE_NAME in resp.cookies
        cookie = resp.cookies[SESSION_COOKIE_NAME]
        assert cookie.value == "" or cookie["max-age"] == "0"
    finally:
        await client.close()


# =============================================================================
# 10. COOKIE SECURITY ATTRIBUTES
# =============================================================================

@pytest.mark.asyncio
async def test_10_cookie_security_attributes(mock_bot):
    """Test 10: Verify HttpOnly, SameSite, and path attributes on session cookies."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    app = server.app

    state = server.session_manager.create_oauth_state(code_verifier="test_verifier")
    server.oauth_client.exchange_code = AsyncMock(
        return_value={"access_token": "tok", "expires_in": 3600}
    )
    server.oauth_client.fetch_user_profile = AsyncMock(
        return_value={"id": "999", "username": "User", "avatar": "av"}
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get(f"/callback?code=code123&state={state}", allow_redirects=False)
        assert SESSION_COOKIE_NAME in resp.cookies
        cookie = resp.cookies[SESSION_COOKIE_NAME]
        assert cookie["httponly"] is True
        assert cookie["samesite"] == "Lax"
        assert cookie["path"] == "/"
    finally:
        await client.close()


# =============================================================================
# 11. UNAUTHORIZED ROUTE REJECTION
# =============================================================================

@pytest.mark.asyncio
async def test_11_unauthorized_route_rejection(mock_bot):
    """Test 11: Verify protected route rejects requests without valid session cookie."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    app = server.app

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/api/auth/me")
        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "Unauthorized"
    finally:
        await client.close()


# =============================================================================
# 12. GUILD MEMBERSHIP VERIFICATION
# =============================================================================

@pytest.mark.asyncio
async def test_12_guild_membership_verification(mock_bot):
    """Test 12: Verify user guilds are retrieved and annotated with bot presence."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    app = server.app

    session = server.session_manager.create_session(
        user_id=888, username="GuildOwner", access_token="tok_guild"
    )
    server.oauth_client.fetch_user_guilds = AsyncMock(
        return_value=[
            {"id": "999888777", "name": "Krovex Test Guild", "owner": True, "permissions": "0"},
            {"id": "111222333", "name": "Foreign Guild", "owner": False, "permissions": "0"},
        ]
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        client.session.cookie_jar.update_cookies({SESSION_COOKIE_NAME: session.session_id})
        resp = await client.get("/api/auth/guilds")
        assert resp.status == 200
        data = await resp.json()
        guilds = data["guilds"]

        # Guild 999888777 has bot
        g1 = next(g for g in guilds if g["id"] == "999888777")
        assert g1["has_bot"] is True
        assert g1["can_manage"] is True

        # Guild 111222333 does not have bot
        g2 = next(g for g in guilds if g["id"] == "111222333")
        assert g2["has_bot"] is False
        assert g2["can_manage"] is False
    finally:
        await client.close()


# =============================================================================
# 13. MANAGE SERVER PERMISSION VERIFICATION
# =============================================================================

def test_13_manage_server_permission_verification():
    """Test 13: Verify exact bitfield logic for Administrator (0x8) and Manage Guild (0x20)."""
    assert has_manage_guild_permission({"owner": True, "permissions": "0"}) is True
    assert has_manage_guild_permission({"owner": False, "permissions": str(PERM_ADMINISTRATOR)}) is True
    assert has_manage_guild_permission({"owner": False, "permissions": str(PERM_MANAGE_GUILD)}) is True
    assert has_manage_guild_permission({"owner": False, "permissions": "0"}) is False
    assert has_manage_guild_permission({"owner": False, "permissions": "invalid"}) is False


# =============================================================================
# 14. CROSS-SERVER ACCESS REJECTION
# =============================================================================

@pytest.mark.asyncio
async def test_14_cross_server_access_rejection(mock_bot):
    """Test 14: Verify user cannot access/configure guild where they lack Manage Server."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    app = server.app

    session = server.session_manager.create_session(
        user_id=1001, username="RestrictedUser", access_token="token_restricted"
    )
    server.oauth_client.fetch_user_guilds = AsyncMock(
        return_value=[
            {"id": "111", "name": "Guild One", "owner": False, "permissions": "0"},
            {"id": "222", "name": "Guild Two", "owner": False, "permissions": str(PERM_MANAGE_GUILD)},
        ]
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        client.session.cookie_jar.update_cookies({SESSION_COOKIE_NAME: session.session_id})

        # Request permissions for guild 111 (unauthorized) -> 403
        resp_denied = await client.get("/api/guilds/111/permissions")
        assert resp_denied.status == 403

        # Request permissions for guild 222 (authorized) -> 200
        resp_allowed = await client.get("/api/guilds/222/permissions")
        assert resp_allowed.status == 200

        # Request permissions for foreign guild 333 (not in guild list) -> 403
        resp_foreign = await client.get("/api/guilds/333/permissions")
        assert resp_foreign.status == 403
    finally:
        await client.close()


# =============================================================================
# 15. DISCORD API FAILURE HANDLING
# =============================================================================

@pytest.mark.asyncio
async def test_15_discord_api_failure_handling(mock_bot):
    """Test 15: Verify 502 Bad Gateway is returned when Discord API fails or times out."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    app = server.app

    session = server.session_manager.create_session(
        user_id=1002, username="APIUser", access_token="token_api"
    )
    server.oauth_client.fetch_user_guilds = AsyncMock(return_value=None)  # Discord API down

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        client.session.cookie_jar.update_cookies({SESSION_COOKIE_NAME: session.session_id})
        resp = await client.get("/api/auth/guilds")
        assert resp.status == 502
        data = await resp.json()
        assert data["error"] == "DiscordAPIError"
    finally:
        await client.close()


# =============================================================================
# 16. CSRF REJECTION
# =============================================================================

@pytest.mark.asyncio
async def test_16_csrf_rejection(mock_bot):
    """Test 16: Verify that endpoints decorated with @require_csrf reject invalid or missing CSRF tokens."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)

    @require_auth
    @require_csrf
    async def dummy_state_change(request: web.Request):
        return web.json_response({"status": "updated"})

    server.app.router.add_post("/api/test/csrf", dummy_state_change)

    session = server.session_manager.create_session(user_id=1003, username="CSRFUser")
    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        client.session.cookie_jar.update_cookies({SESSION_COOKIE_NAME: session.session_id})

        # No CSRF token -> 403
        resp_no_token = await client.post("/api/test/csrf")
        assert resp_no_token.status == 403

        # Invalid CSRF token -> 403
        resp_bad_token = await client.post(
            "/api/test/csrf", headers={"X-CSRF-Token": "forged_token_val"}
        )
        assert resp_bad_token.status == 403

        # Valid CSRF token -> 200
        resp_valid_token = await client.post(
            "/api/test/csrf", headers={"X-CSRF-Token": session.csrf_token}
        )
        assert resp_valid_token.status == 200
        data = await resp_valid_token.json()
        assert data["status"] == "updated"
    finally:
        await client.close()


# =============================================================================
# 17. WEB SERVER STARTUP
# =============================================================================

@pytest.mark.asyncio
async def test_17_web_server_startup(mock_bot):
    """Test 17: Verify AppRunner & TCPSite startup and state tracking."""
    sock = socket.socket()
    sock.bind(("", 0))
    free_port = sock.getsockname()[1]
    sock.close()

    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=free_port)
    assert server.is_running is False

    started = await server.start()
    assert started is True
    assert server.is_running is True

    # Redundant startup check
    assert await server.start() is True
    await server.stop()


# =============================================================================
# 18. WEB SERVER SHUTDOWN
# =============================================================================

@pytest.mark.asyncio
async def test_18_web_server_shutdown(mock_bot):
    """Test 18: Verify graceful shutdown and resource cleanup."""
    sock = socket.socket()
    sock.bind(("", 0))
    free_port = sock.getsockname()[1]
    sock.close()

    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=free_port)
    await server.start()
    assert server.is_running is True

    await server.stop()
    assert server.is_running is False

    # Redundant stop check
    await server.stop()
    assert server.is_running is False


# =============================================================================
# 19. PORT CONFLICT HANDLING
# =============================================================================

@pytest.mark.asyncio
async def test_19_port_conflict_handling(mock_bot):
    """Test 19: Verify graceful handling when the target port is already occupied."""
    conflict_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conflict_sock.bind(("127.0.0.1", 0))
    occupied_port = conflict_sock.getsockname()[1]

    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=occupied_port)

    try:
        success = await server.start()
        assert success is False
        assert server.is_running is False
    finally:
        conflict_sock.close()
        await server.stop()


# =============================================================================
# 20. MINIMAL PUBLIC HEALTH ENDPOINT (PHASE 2A.9.1.1 PATCH)
# =============================================================================

@pytest.mark.asyncio
async def test_20_minimal_public_health_endpoint(mock_bot):
    """Test 20: Verify /health returns minimal public status and does not leak session data."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    server.session_manager.create_session(user_id=999, username="ActiveUser")

    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        resp = await client.get("/health")
        assert resp.status == 200
        data = await resp.json()

        # Minimal response
        assert data == {"status": "ok"}

        # Absolutely no operational metric or internal state leakage
        assert "active_sessions" not in data
        assert "bot_online" not in data
        assert "user" not in data
        assert "tokens" not in data
    finally:
        await client.close()


# =============================================================================
# 21. VERCEL CORS & PREFLIGHT HANDLING
# =============================================================================

@pytest.mark.asyncio
async def test_21_cors_preflight_and_headers(mock_bot):
    """Test 21: Verify CORS preflight OPTIONS and response headers for Vercel origin."""
    server = DashboardServer(bot=mock_bot, host="127.0.0.1", port=0)
    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        # Preflight OPTIONS
        preflight = await client.options(
            "/api/auth/me",
            headers={"Origin": "https://krovex.vercel.app"},
        )
        assert preflight.status == 204
        assert preflight.headers.get("Access-Control-Allow-Origin") == "https://krovex.vercel.app"
        assert preflight.headers.get("Access-Control-Allow-Credentials") == "true"

        # Standard GET with Origin
        resp = await client.get(
            "/health",
            headers={"Origin": "https://krovex.bot"},
        )
        assert resp.status == 200
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://krovex.bot"
        assert resp.headers.get("Access-Control-Allow-Credentials") == "true"
    finally:
        await client.close()
