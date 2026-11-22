"""Configuration management for Death Bot.

Handles loading, validating, and protecting environment variables with
informative error messages, sensible defaults, and secret masking.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv

# Automatically load .env if present
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)


class ConfigurationError(Exception):
    """Raised when mandatory configuration variables are missing or invalid."""
    pass


@dataclass(frozen=True)
class BotConfig:
    """Immutable, strongly-typed bot configuration."""

    # Discord credentials
    token: str
    client_id: Optional[int]
    dev_guild_id: Optional[int]
    owner_ids: List[int] = field(default_factory=list)

    # Database
    mongodb_uri: str = ""
    mongodb_database: str = "death_bot"

    # Core settings
    default_prefix: str = "!"
    environment: str = "development"
    log_level: str = "INFO"

    # Visual Identity & Typography
    color_primary: int = 0x8B5CF6
    color_secondary: int = 0x22D3EE
    color_success: int = 0x22C55E
    color_error: int = 0xEF4444
    color_warning: int = 0xF59E0B
    color_info: int = 0x3B82F6
    ui_font_body: str = "Inter"
    ui_font_heading: str = "Oxanium"
    ui_font_monospace: str = "Chakra Petch"

    # Music system defaults
    lavalink_enabled: bool = False
    lavalink_host: str = "127.0.0.1"
    lavalink_port: int = 2333
    lavalink_password: str = "youshallnotpass"
    max_queue_size: int = 500
    default_volume: int = 100

    # Voice status system defaults
    voice_status_update_interval: int = 60

    # Welcome system defaults
    invite_tracking_enabled: bool = True

    # Dashboard & Web Server configuration (Stage 2A.9.1)
    dashboard_enabled: bool = False
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8080
    discord_client_secret: Optional[str] = None
    dashboard_redirect_uri: Optional[str] = None
    session_secret_key: Optional[str] = None

    # KROVEX SOUL & AI Engine configuration (Phase 2)
    gemini_api_key: Optional[str] = None
    soul_enabled: bool = False
    soul_model: str = "gemini-3.5-flash-lite"
    soul_timeout: float = 12.0
    soul_max_turns: int = 10
    soul_cooldown_seconds: float = 3.0

    # Spotify Web API configuration
    spotify_client_id: Optional[str] = None
    spotify_client_secret: Optional[str] = None

    # Extended Branding & Activity Configuration (.env sync)
    bot_name: str = "KROVEX"
    bot_description: str = "An All-in-One Discord Bot"
    bot_tagline: str = "Your Ultimate Discord Companion"
    bot_author_name: str = "KROVEX"
    bot_footer_text: str = "Powered by KROVEX"
    bot_status: str = "online"
    bot_status_rotation: bool = True
    bot_status_rotation_interval: int = 15
    bot_activity_type: str = "watching"
    bot_activity_text: str = "over your server"
    status_rotation_activities: str = "playing:KROVEX | /help;watching:over the server;listening:your commands;competing:for the best community"
    status_rotation_random: bool = False

    # Maintenance & Debug
    maintenance_mode: bool = False
    maintenance_message: str = "KROVEX is undergoing maintenance."
    maintenance_allow_owners: bool = True
    debug_mode: bool = False
    error_reporting: bool = True
    health_check_enabled: bool = True

    # Feature Toggles
    feature_music: bool = True
    feature_ownervc: bool = True
    feature_security: bool = True
    feature_moderation: bool = True
    feature_leveling: bool = True
    feature_economy: bool = True
    feature_tickets: bool = True
    feature_welcome: bool = True
    feature_automod: bool = True
    feature_logging: bool = True
    feature_giveaways: bool = True
    feature_soul_ai: bool = True

    # OwnerVC & Moderation Policy
    ownervc_loop_enabled: bool = True
    ownervc_loop_require_opt_in: bool = True
    ownervc_loop_cooldown: int = 30
    ownervc_confirm_bulk_actions: bool = True
    ownervc_default_bitrate: int = 64000
    ownervc_default_limit: int = 0
    bulk_action_confirmation: bool = True
    max_purge_limit: int = 100
    moderation_audit_logging: bool = True
    default_timeout_seconds: int = 600

    # Presentation & Embeds
    embed_footer: bool = True
    embed_timestamp: bool = True
    custom_emojis_enabled: bool = True

    # URLs & Links
    support_server_url: str = "https://discord.gg/89tXm2ZEqR"
    website_url: str = "https://krovex.bot"
    invite_url: str = ""
    documentation_url: str = ""
    bug_report_url: str = ""

    # Command synchronization behavior
    sync_commands_on_startup: bool = True

    @property
    def spotify_configured(self) -> bool:
        """Check if Spotify API credentials are configured."""
        return bool(self.spotify_client_id and self.spotify_client_secret)

    @property
    def support_url(self) -> str:
        """Alias for support_server_url."""
        return self.support_server_url

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment.lower() == "production"

    @property
    def application_id(self) -> Optional[int]:
        """Backward-compatible alias for client_id."""
        return self.client_id

    @classmethod
    def from_env(cls, validate: bool = True) -> BotConfig:
        """Construct configuration from environment variables.

        Args:
            validate: When True, raises ConfigurationError for missing mandatory settings.
        """
        token = os.getenv("DISCORD_TOKEN", "").strip()

        if validate:
            missing: List[str] = []
            if not token or token == "your_bot_token_here":
                missing.append("DISCORD_TOKEN")

            if missing:
                raise ConfigurationError(
                    f"Missing or invalid required environment variable(s): {', '.join(missing)}.\n"
                    f"Please copy .env.example to .env and configure the required values."
                )

        # Parse integer fields safely
        client_id_val = os.getenv("DISCORD_CLIENT_ID", "").strip()
        client_id = int(client_id_val) if client_id_val.isdigit() else None

        dev_guild_val = os.getenv("DEV_GUILD_ID", "").strip()
        dev_guild_id = int(dev_guild_val) if dev_guild_val.isdigit() else None

        # Parse owner IDs
        owner_ids_raw = os.getenv("OWNER_IDS", "")
        owner_ids: List[int] = []
        for item in owner_ids_raw.replace(";", ",").split(","):
            cleaned = item.strip().strip("'\"[]")
            if cleaned.isdigit():
                owner_ids.append(int(cleaned))

        # Parse hex colors safely
        def parse_color(env_var: str, default: int) -> int:
            val = os.getenv(env_var, "").strip()
            if not val:
                return default
            try:
                if val.startswith("0x") or val.startswith("0X"):
                    return int(val, 16)
                if val.startswith("#"):
                    return int(val[1:], 16)
                return int(val, 16)
            except ValueError:
                return default

        # Parse bools safely
        def parse_bool(env_var: str, default: bool) -> bool:
            val = os.getenv(env_var, "").strip().lower()
            if not val:
                return default
            return val in ("true", "1", "yes", "on")

        # Parse ints safely
        def parse_int(env_var: str, default: int) -> int:
            val = os.getenv(env_var, "").strip()
            if not val:
                return default
            try:
                return int(val)
            except ValueError:
                return default

        mongodb_uri = os.getenv("MONGODB_URI", "").strip()
        return cls(
            token=token,
            client_id=client_id,
            dev_guild_id=dev_guild_id,
            owner_ids=owner_ids,
            mongodb_uri=mongodb_uri,
            mongodb_database=os.getenv("MONGODB_DATABASE", "death_bot").strip() or "death_bot",
            default_prefix=os.getenv("DEFAULT_PREFIX", "!").strip() or "!",
            environment=os.getenv("ENVIRONMENT", "development").strip().lower(),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            color_primary=parse_color("COLOR_PRIMARY", 0x8B5CF6),
            color_secondary=parse_color("COLOR_SECONDARY", 0x22D3EE),
            color_success=parse_color("COLOR_SUCCESS", 0x22C55E),
            color_error=parse_color("COLOR_ERROR", 0xEF4444),
            color_warning=parse_color("COLOR_WARNING", 0xF59E0B),
            color_info=parse_color("COLOR_INFO", 0x3B82F6),
            ui_font_body=os.getenv("UI_FONT_BODY", "Inter").strip() or "Inter",
            ui_font_heading=os.getenv("UI_FONT_HEADING", "Oxanium").strip() or "Oxanium",
            ui_font_monospace=os.getenv("UI_FONT_MONOSPACE", "Chakra Petch").strip() or "Chakra Petch",
            lavalink_enabled=parse_bool("LAVALINK_ENABLED", False),
            lavalink_host=os.getenv("LAVALINK_HOST", "127.0.0.1").strip(),
            lavalink_port=parse_int("LAVALINK_PORT", 2333),
            lavalink_password=os.getenv("LAVALINK_PASSWORD", "youshallnotpass").strip(),
            max_queue_size=parse_int("MAX_QUEUE_SIZE", 500),
            default_volume=parse_int("DEFAULT_VOLUME", 100),
            voice_status_update_interval=parse_int("VOICE_STATUS_UPDATE_INTERVAL", 60),
            invite_tracking_enabled=parse_bool("INVITE_TRACKING_ENABLED", True),
            dashboard_enabled=parse_bool("DASHBOARD_ENABLED", False),
            dashboard_host=os.getenv("DASHBOARD_HOST", "0.0.0.0").strip() or "0.0.0.0",
            dashboard_port=parse_int("DASHBOARD_PORT", 8080),
            discord_client_secret=os.getenv("DISCORD_CLIENT_SECRET", "").strip() or None,
            dashboard_redirect_uri=os.getenv("DASHBOARD_REDIRECT_URI", "").strip() or None,
            session_secret_key=os.getenv("SESSION_SECRET_KEY", "").strip() or None,
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip() or None,
            soul_enabled=parse_bool("SOUL_ENABLED", False),
            soul_model=os.getenv("SOUL_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite",
            soul_timeout=float(os.getenv("SOUL_TIMEOUT", "12.0")),
            soul_max_turns=parse_int("SOUL_MAX_TURNS", 10),
            soul_cooldown_seconds=float(os.getenv("SOUL_COOLDOWN_SECONDS", "3.0")),
            support_server_url=(
                os.getenv("SUPPORT_SERVER_URL", "").strip()
                or os.getenv("SUPPORT_URL", "").strip()
                or "https://discord.gg/89tXm2ZEqR"
            ),
            website_url=os.getenv("WEBSITE_URL", "").strip() or "https://krovex.bot",
            invite_url=os.getenv("INVITE_URL", "").strip(),
            documentation_url=os.getenv("DOCUMENTATION_URL", "").strip(),
            bug_report_url=os.getenv("BUG_REPORT_URL", "").strip(),
            spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", "").strip() or None,
            spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", "").strip() or None,
            sync_commands_on_startup=parse_bool("SYNC_COMMANDS_ON_STARTUP", True),

            # Extended Branding & Activity Configuration
            bot_name=os.getenv("BOT_NAME", "KROVEX").strip() or "KROVEX",
            bot_description=os.getenv("BOT_DESCRIPTION", "An All-in-One Discord Bot").strip(),
            bot_tagline=os.getenv("BOT_TAGLINE", "Your Ultimate Discord Companion").strip(),
            bot_author_name=os.getenv("BOT_AUTHOR_NAME", "KROVEX").strip() or "KROVEX",
            bot_footer_text=os.getenv("BOT_FOOTER_TEXT", "Powered by KROVEX").strip() or "Powered by KROVEX",
            bot_status=os.getenv("BOT_STATUS", "online").strip().lower() or "online",
            bot_status_rotation=parse_bool("BOT_STATUS_ROTATION", parse_bool("STATUS_ROTATION", True)),
            bot_status_rotation_interval=parse_int("BOT_STATUS_ROTATION_INTERVAL", parse_int("STATUS_ROTATION_INTERVAL", 15)),
            bot_activity_type=os.getenv("BOT_ACTIVITY_TYPE", "watching").strip().lower() or "watching",
            bot_activity_text=os.getenv("BOT_ACTIVITY_TEXT", "over your server").strip(),
            status_rotation_activities=os.getenv(
                "STATUS_ROTATION_ACTIVITIES",
                "playing:KROVEX | /help;watching:over the server;listening:your commands;competing:for the best community",
            ).strip(),
            status_rotation_random=parse_bool("STATUS_ROTATION_RANDOM", False),

            # Maintenance & Debug
            maintenance_mode=parse_bool("MAINTENANCE_MODE", False),
            maintenance_message=os.getenv("MAINTENANCE_MESSAGE", "KROVEX is undergoing maintenance.").strip(),
            maintenance_allow_owners=parse_bool("MAINTENANCE_ALLOW_OWNERS", True),
            debug_mode=parse_bool("DEBUG_MODE", False),
            error_reporting=parse_bool("ERROR_REPORTING", True),
            health_check_enabled=parse_bool("HEALTH_CHECK_ENABLED", True),

            # Feature Toggles
            feature_music=parse_bool("FEATURE_MUSIC", True),
            feature_ownervc=parse_bool("FEATURE_OWNERVC", True),
            feature_security=parse_bool("FEATURE_SECURITY", True),
            feature_moderation=parse_bool("FEATURE_MODERATION", True),
            feature_leveling=parse_bool("FEATURE_LEVELING", True),
            feature_economy=parse_bool("FEATURE_ECONOMY", True),
            feature_tickets=parse_bool("FEATURE_TICKETS", True),
            feature_welcome=parse_bool("FEATURE_WELCOME", True),
            feature_automod=parse_bool("FEATURE_AUTOMOD", True),
            feature_logging=parse_bool("FEATURE_LOGGING", True),
            feature_giveaways=parse_bool("FEATURE_GIVEAWAYS", True),
            feature_soul_ai=parse_bool("FEATURE_SOUL_AI", True),

            # OwnerVC & Moderation Policy
            ownervc_loop_enabled=parse_bool("OWNERVC_LOOP_ENABLED", True),
            ownervc_loop_require_opt_in=parse_bool("OWNERVC_LOOP_REQUIRE_OPT_IN", True),
            ownervc_loop_cooldown=parse_int("OWNERVC_LOOP_COOLDOWN", 30),
            ownervc_confirm_bulk_actions=parse_bool("OWNERVC_CONFIRM_BULK_ACTIONS", parse_bool("BULK_ACTION_CONFIRMATION", True)),
            ownervc_default_bitrate=parse_int("OWNERVC_DEFAULT_BITRATE", 64000),
            ownervc_default_limit=parse_int("OWNERVC_DEFAULT_LIMIT", 0),
            bulk_action_confirmation=parse_bool("BULK_ACTION_CONFIRMATION", True),
            max_purge_limit=parse_int("MAX_PURGE_LIMIT", 100),
            moderation_audit_logging=parse_bool("MODERATION_AUDIT_LOGGING", True),
            default_timeout_seconds=parse_int("DEFAULT_TIMEOUT_SECONDS", 600),

            # Presentation & Embeds
            embed_footer=parse_bool("EMBED_FOOTER", True),
            embed_timestamp=parse_bool("EMBED_TIMESTAMP", True),
            custom_emojis_enabled=parse_bool("CUSTOM_EMOJIS_ENABLED", True),
        )

    def safe_repr(self) -> dict[str, Any]:
        """Return a dictionary representation with sensitive secrets masked."""
        return {
            "token": "***REDACTED***" if self.token else "NOT_SET",
            "client_id": self.client_id,
            "dev_guild_id": self.dev_guild_id,
            "owner_ids": self.owner_ids,
            "mongodb_uri": (
                re.sub(r"://([^@]+)@", "://***REDACTED***@", self.mongodb_uri)
                if self.mongodb_uri
                else "NOT_SET"
            ),
            "mongodb_database": self.mongodb_database,
            "default_prefix": self.default_prefix,
            "environment": self.environment,
            "log_level": self.log_level,
            "color_primary": hex(self.color_primary),
            "color_secondary": hex(self.color_secondary),
            "ui_font_body": self.ui_font_body,
            "ui_font_heading": self.ui_font_heading,
            "ui_font_monospace": self.ui_font_monospace,
            "lavalink_enabled": self.lavalink_enabled,
            "max_queue_size": self.max_queue_size,
            "voice_status_update_interval": self.voice_status_update_interval,
            "invite_tracking_enabled": self.invite_tracking_enabled,
            "dashboard_enabled": self.dashboard_enabled,
            "dashboard_host": self.dashboard_host,
            "dashboard_port": self.dashboard_port,
            "discord_client_secret": "***REDACTED***" if self.discord_client_secret else "NOT_SET",
            "dashboard_redirect_uri": self.dashboard_redirect_uri,
            "session_secret_key": "***REDACTED***" if self.session_secret_key else "NOT_SET",
            "gemini_api_key": "***REDACTED***" if self.gemini_api_key else "NOT_SET",
            "spotify_client_id": self.spotify_client_id or "NOT_SET",
            "spotify_client_secret": "***REDACTED***" if self.spotify_client_secret else "NOT_SET",
            "soul_enabled": self.soul_enabled,
            "soul_model": self.soul_model,
            "soul_timeout": self.soul_timeout,
            "soul_max_turns": self.soul_max_turns,
            "soul_cooldown_seconds": self.soul_cooldown_seconds,
            "sync_commands_on_startup": self.sync_commands_on_startup,
        }

    def __repr__(self) -> str:
        items = [f"{k}={v}" for k, v in self.safe_repr().items()]
        return f"BotConfig({', '.join(items)})"

