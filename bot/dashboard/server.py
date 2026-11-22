"""Asynchronous web server engine, routes, middleware, and lifecycle manager for KROVEX."""
from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from aiohttp import web

from bot.dashboard.oauth import (
    DiscordOAuth2Client,
    generate_pkce_pair,
    has_manage_guild_permission,
)
from bot.dashboard.session import Session, SessionManager
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.dashboard.server")
SESSION_COOKIE_NAME = "krovex_session"

# App and Request Keys for clean typed storage without warnings
DASHBOARD_SERVER_KEY = web.AppKey("dashboard_server", Any)
SESSION_KEY = web.RequestKey("session", Optional[Session])
USER_ID_KEY = web.RequestKey("user_id", Optional[int])


# =============================================================================
# MIDDLEWARE & DECORATORS
# =============================================================================

ALLOWED_ORIGINS = {
    "https://krovex.bot",
    "https://krovex.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
}


@web.middleware
async def cors_middleware(request: web.Request, handler: Callable) -> web.StreamResponse:
    """Handle Cross-Origin Resource Sharing (CORS) and preflight requests for Vercel."""
    origin = request.headers.get("Origin", "")
    is_allowed = origin in ALLOWED_ORIGINS or origin.endswith(".vercel.app") or origin.endswith("krovex.bot")

    if request.method == "OPTIONS":
        resp = web.Response(status=204)
        if is_allowed and origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-CSRF-Token"
            resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    response = await handler(request)
    if is_allowed and origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-CSRF-Token"
    return response


@web.middleware
async def session_middleware(request: web.Request, handler: Callable) -> web.StreamResponse:
    """Extract and validate server-side session from secure HTTP-only cookie."""
    server: DashboardServer = request.app[DASHBOARD_SERVER_KEY]
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    session = server.session_manager.get_session(session_id)
    request[SESSION_KEY] = session
    request[USER_ID_KEY] = session.user_id if session else None
    return await handler(request)


def require_auth(handler: Callable) -> Callable:
    """Ensure endpoint can only be accessed with a valid, unexpired session."""
    @functools.wraps(handler)
    async def wrapper(*args: Any, **kwargs: Any) -> web.StreamResponse:
        request: web.Request = args[-1]
        session: Optional[Session] = request.get(SESSION_KEY)
        if not session or session.is_expired:
            return web.json_response(
                {"error": "Unauthorized", "message": "Authentication required"},
                status=401,
            )
        return await handler(*args, **kwargs)
    return wrapper


def require_csrf(handler: Callable) -> Callable:
    """Protect state-changing authenticated endpoints against Cross-Site Request Forgery."""
    @functools.wraps(handler)
    async def wrapper(*args: Any, **kwargs: Any) -> web.StreamResponse:
        request: web.Request = args[-1]
        session: Optional[Session] = request.get(SESSION_KEY)
        if not session:
            return web.json_response({"error": "Unauthorized"}, status=401)

        candidate_token = request.headers.get("X-CSRF-Token")
        if not candidate_token:
            # Also check JSON body if present
            if request.can_read_body and request.content_type == "application/json":
                try:
                    body = await request.clone().json()
                    candidate_token = body.get("csrf_token")
                except Exception:
                    pass

        if not session.validate_csrf(candidate_token):
            return web.json_response(
                {"error": "Forbidden", "message": "Invalid or missing CSRF token"},
                status=403,
            )
        return await handler(*args, **kwargs)
    return wrapper


# =============================================================================
# DASHBOARD WEB SERVER
# =============================================================================

class DashboardServer:
    """Asynchronous web server engine powering KROVEX authentication and REST API."""

    def __init__(
        self,
        bot: "DeathBot",
        host: str = "0.0.0.0",
        port: int = 8080,
        session_manager: Optional[SessionManager] = None,
        oauth_client: Optional[DiscordOAuth2Client] = None,
    ) -> None:
        self.bot = bot
        self.host = host
        self.port = port
        self.session_manager = session_manager or SessionManager()
        self.oauth_client = oauth_client or DiscordOAuth2Client(
            client_id=bot.config.client_id,
            client_secret=bot.config.discord_client_secret,
            redirect_uri=bot.config.dashboard_redirect_uri,
            session=bot.session,
        )

        self.app = web.Application(middlewares=[cors_middleware, session_middleware])
        self.app[DASHBOARD_SERVER_KEY] = self
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._running: bool = False

        self._register_routes()

    @property
    def is_running(self) -> bool:
        """Return True if the web server site is actively running."""
        return self._running

    def _register_routes(self) -> None:
        """Register API and OAuth2 endpoints."""
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/login", self.handle_login)
        self.app.router.add_get("/callback", self.handle_callback)
        self.app.router.add_post("/logout", self.handle_logout)
        self.app.router.add_get("/api/auth/me", self.handle_api_me)
        self.app.router.add_get("/api/auth/guilds", self.handle_api_guilds)
        self.app.router.add_get("/api/guilds/{guild_id}/permissions", self.handle_guild_permissions)

    # =========================================================================
    # ROUTE HANDLERS
    # =========================================================================

    async def handle_health(self, request: web.Request) -> web.Response:
        """Minimal public health check endpoint."""
        return web.json_response({"status": "ok"})

    async def handle_login(self, request: web.Request) -> web.Response:
        """Initiate OAuth2 handshake: generate PKCE pair and secure state, redirect to Discord."""
        code_verifier, code_challenge = generate_pkce_pair()
        redirect_after = request.query.get("redirect", "/dashboard")
        state = self.session_manager.create_oauth_state(
            code_verifier=code_verifier, redirect_after=redirect_after
        )

        try:
            auth_url = self.oauth_client.get_authorization_url(
                state=state, code_challenge=code_challenge
            )
            raise web.HTTPFound(location=auth_url)
        except web.HTTPException:
            raise
        except Exception as err:
            logger.error("Failed to generate authorization URL: %s", err)
            return web.json_response(
                {"error": "ConfigurationError", "message": "OAuth2 configuration is incomplete"},
                status=500,
            )

    async def handle_callback(self, request: web.Request) -> web.Response:
        """Process Discord authorization callback, validate state, and establish session."""
        # 1. Check for Discord error response (e.g. user cancelled)
        error = request.query.get("error")
        if error:
            error_desc = request.query.get("error_description", "Authorization cancelled")
            logger.warning("OAuth2 callback received error: %s (%s)", error, error_desc)
            raise web.HTTPFound(location=f"/?auth_error={error}")

        code = request.query.get("code")
        state = request.query.get("state")
        if not code or not state:
            return web.json_response(
                {"error": "BadRequest", "message": "Missing authorization code or state"},
                status=400,
            )

        # 2. Validate and atomically consume state (single-use, prevents replay attacks)
        state_data = self.session_manager.validate_and_consume_state(state)
        if not state_data:
            return web.json_response(
                {"error": "InvalidState", "message": "Invalid, expired, or replayed state token"},
                status=400,
            )

        # 3. Exchange code for access token using stored PKCE code_verifier
        token_data = await self.oauth_client.exchange_code(
            code=code, code_verifier=state_data.code_verifier
        )
        if not token_data or "access_token" not in token_data:
            return web.json_response(
                {"error": "TokenExchangeFailed", "message": "Failed to exchange authorization code"},
                status=400,
            )

        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = float(token_data.get("expires_in", 604800.0))

        # 4. Fetch authenticated user profile
        user_data = await self.oauth_client.fetch_user_profile(access_token)
        if not user_data or "id" not in user_data:
            return web.json_response(
                {"error": "ProfileFetchFailed", "message": "Failed to retrieve Discord user profile"},
                status=502,
            )

        # 5. Destroy any pre-existing session associated with the request cookie to prevent fixation
        existing_session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if existing_session_id:
            self.session_manager.destroy_session(existing_session_id)

        # 6. Issue a new server-side session with fresh session ID and CSRF token
        session = self.session_manager.create_session(
            user_id=int(user_data["id"]),
            username=user_data.get("username", "Unknown"),
            discriminator=user_data.get("discriminator", "0"),
            avatar=user_data.get("avatar"),
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_in=expires_in,
        )

        redirect_target = state_data.redirect_after or "/dashboard"
        response = web.HTTPFound(location=redirect_target)
        self._set_session_cookie(response, session.session_id)
        raise response

    @require_auth
    @require_csrf
    async def handle_logout(self, request: web.Request) -> web.Response:
        """Invalidate server-side session and clear client session cookie via authenticated POST."""
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if session_id:
            self.session_manager.destroy_session(session_id)

        response = web.json_response({"success": True, "message": "Logged out successfully"})
        self._clear_session_cookie(response)
        return response

    @require_auth
    async def handle_api_me(self, request: web.Request) -> web.Response:
        """Return authenticated user profile and CSRF token (never exposes OAuth tokens)."""
        session: Session = request[SESSION_KEY]  # type: ignore
        return web.json_response(
            {
                "user": {
                    "id": str(session.user_id),
                    "username": session.username,
                    "discriminator": session.discriminator,
                    "avatar": session.avatar,
                    "csrf_token": session.csrf_token,
                }
            }
        )

    @require_auth
    async def handle_api_guilds(self, request: web.Request) -> web.Response:
        """Fetch user's Discord guilds and annotate with bot presence and management rights."""
        session: Session = request[SESSION_KEY]  # type: ignore
        guilds = await self.oauth_client.fetch_user_guilds(session.access_token)
        if guilds is None:
            return web.json_response(
                {"error": "DiscordAPIError", "message": "Failed to fetch guilds from Discord"},
                status=502,
            )

        annotated_guilds: List[Dict[str, Any]] = []
        for g in guilds:
            g_id = int(g["id"])
            can_manage = has_manage_guild_permission(g)
            bot_present = (
                self.bot.get_guild(g_id) is not None if hasattr(self.bot, "get_guild") else False
            )
            annotated_guilds.append(
                {
                    "id": str(g_id),
                    "name": g.get("name"),
                    "icon": g.get("icon"),
                    "owner": g.get("owner", False),
                    "can_manage": can_manage,
                    "has_bot": bot_present,
                }
            )

        return web.json_response({"guilds": annotated_guilds})

    @require_auth
    async def handle_guild_permissions(self, request: web.Request) -> web.Response:
        """Validate whether current session user has Manage Server rights on a specific guild."""
        session: Session = request[SESSION_KEY]  # type: ignore
        guild_id_str = request.match_info.get("guild_id")
        try:
            guild_id = int(guild_id_str)  # type: ignore
        except (ValueError, TypeError):
            return web.json_response(
                {"error": "BadRequest", "message": "Invalid guild ID"}, status=400
            )

        guilds = await self.oauth_client.fetch_user_guilds(session.access_token)
        if guilds is None:
            return web.json_response(
                {"error": "DiscordAPIError", "message": "Unable to verify permissions with Discord"},
                status=502,
            )

        matched_guild = next((g for g in guilds if int(g["id"]) == guild_id), None)
        if not matched_guild or not has_manage_guild_permission(matched_guild):
            return web.json_response(
                {
                    "error": "Forbidden",
                    "message": "You lack Administrator or Manage Server permissions for this guild",
                },
                status=403,
            )

        bot_present = (
            self.bot.get_guild(guild_id) is not None if hasattr(self.bot, "get_guild") else False
        )
        return web.json_response(
            {
                "guild_id": str(guild_id),
                "can_manage": True,
                "has_bot": bot_present,
            }
        )

    # =========================================================================
    # COOKIE MANAGEMENT & LIFECYCLE
    # =========================================================================

    def _set_session_cookie(self, response: web.StreamResponse, session_id: str) -> None:
        """Set secure, HttpOnly, SameSite session cookie."""
        secure_cookie = (
            self.bot.config.is_production
            if hasattr(self.bot, "config") and hasattr(self.bot.config, "is_production")
            else False
        )
        response.set_cookie(
            name=SESSION_COOKIE_NAME,
            value=session_id,
            max_age=86400,
            httponly=True,
            samesite="Lax",
            secure=secure_cookie,
            path="/",
        )

    def _clear_session_cookie(self, response: web.StreamResponse) -> None:
        """Explicitly expire session cookie."""
        response.del_cookie(
            name=SESSION_COOKIE_NAME,
            path="/",
        )

    async def start(self) -> bool:
        """Start aiohttp AppRunner and TCPSite listener."""
        if self._running:
            logger.info("Dashboard web server is already running.")
            return True

        try:
            self._runner = web.AppRunner(self.app, access_log=None)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, host=self.host, port=self.port)
            await self._site.start()
            self._running = True
            logger.info("KROVEX Dashboard web server started on http://%s:%d", self.host, self.port)
            return True
        except OSError as os_err:
            logger.error(
                "Could not bind dashboard web server to %s:%d: %s. Port may be occupied.",
                self.host,
                self.port,
                os_err,
            )
            if self._runner:
                await self._runner.cleanup()
                self._runner = None
            self._running = False
            return False
        except Exception as err:
            logger.error("Unexpected error starting dashboard web server: %s", err, exc_info=True)
            if self._runner:
                await self._runner.cleanup()
                self._runner = None
            self._running = False
            return False

    async def stop(self) -> None:
        """Gracefully terminate HTTP listener and runner resources."""
        if not self._running:
            return

        logger.info("Stopping KROVEX Dashboard web server...")
        if self._site:
            try:
                await self._site.stop()
            except Exception as e:
                logger.warning("Error stopping TCPSite: %s", e)
            self._site = None

        if self._runner:
            try:
                await self._runner.cleanup()
            except Exception as e:
                logger.warning("Error cleaning up AppRunner: %s", e)
            self._runner = None

        self._running = False
        logger.info("KROVEX Dashboard web server stopped.")
