"""Core bot engine package."""

from bot.core.bot import DeathBot
from bot.core.checks import is_bot_owner, require_voice_channel
from bot.core.context import UnifiedContext
from bot.core.error_handler import GlobalErrorHandler
from bot.core.event_handler import EventHandler

__all__ = [
    "DeathBot",
    "UnifiedContext",
    "GlobalErrorHandler",
    "EventHandler",
    "is_bot_owner",
    "require_voice_channel",
]

