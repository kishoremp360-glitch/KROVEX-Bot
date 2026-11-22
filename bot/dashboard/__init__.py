"""Dashboard module package."""
from bot.dashboard.oauth import DiscordOAuth2Client, has_manage_guild_permission
from bot.dashboard.panels import UnifiedDashboardView
from bot.dashboard.router import DashboardAPI
from bot.dashboard.server import (
    DashboardServer,
    SESSION_COOKIE_NAME,
    require_auth,
    require_csrf,
)
from bot.dashboard.session import Session, SessionManager

__all__ = [
    "UnifiedDashboardView",
    "DashboardAPI",
    "DashboardServer",
    "DiscordOAuth2Client",
    "SessionManager",
    "Session",
    "SESSION_COOKIE_NAME",
    "require_auth",
    "require_csrf",
    "has_manage_guild_permission",
]
