"""Data models and schemas for MongoDB collections in Death Bot.

Ensures strict typing, standard field names (guild_id, user_id), and defaults.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass
class GuildSettings:
    """Settings schema for guild_settings collection."""
    guild_id: int
    prefix: str = "!"
    dj_role_ids: List[int] = field(default_factory=list)
    disabled_commands: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GuildSettings:
        return cls(
            guild_id=int(data["guild_id"]),
            prefix=str(data.get("prefix", "!")),
            dj_role_ids=[int(r) for r in data.get("dj_role_ids", [])],
            disabled_commands=list(data.get("disabled_commands", [])),
            created_at=data.get("created_at", utc_now()),
            updated_at=data.get("updated_at", utc_now()),
        )


@dataclass
class UserProfile:
    """User profile schema for user_profiles collection."""
    user_id: int
    xp: int = 0
    level: int = 1
    balance: int = 0
    bio: str = "A mysterious user."
    badges: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UserProfile:
        return cls(
            user_id=int(data["user_id"]),
            xp=int(data.get("xp", 0)),
            level=int(data.get("level", 1)),
            balance=int(data.get("balance", 0)),
            bio=str(data.get("bio", "A mysterious user.")),
            badges=list(data.get("badges", [])),
            created_at=data.get("created_at", utc_now()),
            updated_at=data.get("updated_at", utc_now()),
        )


@dataclass
class MusicSettings:
    """Music system settings schema for music_settings collection."""
    guild_id: int
    default_volume: int = 100
    max_queue_size: int = 500
    autoplay: bool = False
    loop_mode: str = "off"  # 'off', 'track', 'queue'
    dj_role_id: Optional[int] = None
    dj_only: bool = False
    twenty_four_seven: bool = False
    vote_skip_ratio: float = 0.5
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MusicSettings:
        return cls(
            guild_id=int(data["guild_id"]),
            default_volume=int(data.get("default_volume", 100)),
            max_queue_size=int(data.get("max_queue_size", 500)),
            autoplay=bool(data.get("autoplay", False)),
            loop_mode=str(data.get("loop_mode", "off")),
            dj_role_id=int(data["dj_role_id"]) if data.get("dj_role_id") else None,
            dj_only=bool(data.get("dj_only", False)),
            twenty_four_seven=bool(data.get("twenty_four_seven", False)),
            vote_skip_ratio=float(data.get("vote_skip_ratio", 0.5)),
            created_at=data.get("created_at", utc_now()),
            updated_at=data.get("updated_at", utc_now()),
        )


@dataclass
class VoiceSettings:
    """Voice channel activity tracking settings schema for voice_settings collection."""
    guild_id: int
    enabled: bool = False
    status_channel_id: Optional[int] = None
    status_message_id: Optional[int] = None
    update_interval: int = 60
    track_active_time: bool = True
    notify_channel_id: Optional[int] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VoiceSettings:
        return cls(
            guild_id=int(data["guild_id"]),
            enabled=bool(data.get("enabled", False)),
            status_channel_id=int(data["status_channel_id"]) if data.get("status_channel_id") else None,
            status_message_id=int(data["status_message_id"]) if data.get("status_message_id") else None,
            update_interval=int(data.get("update_interval", 60)),
            track_active_time=bool(data.get("track_active_time", True)),
            notify_channel_id=int(data["notify_channel_id"]) if data.get("notify_channel_id") else None,
            created_at=data.get("created_at", utc_now()),
            updated_at=data.get("updated_at", utc_now()),
        )


@dataclass
class VoiceSession:
    """Active or historical voice session schema for voice_sessions collection."""
    guild_id: int
    user_id: int
    channel_id: int
    joined_at: datetime = field(default_factory=utc_now)
    left_at: Optional[datetime] = None
    duration_seconds: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VoiceSession:
        return cls(
            guild_id=int(data["guild_id"]),
            user_id=int(data["user_id"]),
            channel_id=int(data["channel_id"]),
            joined_at=data.get("joined_at", utc_now()),
            left_at=data.get("left_at"),
            duration_seconds=int(data.get("duration_seconds", 0)),
        )


@dataclass
class WelcomeSettings:
    """Welcome and goodbye system settings schema for welcome_settings collection."""
    guild_id: int
    enabled: bool = False
    channel_id: Optional[int] = None
    message_template: str = "Welcome {user} to **{server}**! You are member #{member_count}."
    embed_enabled: bool = True
    custom_image_enabled: bool = False
    auto_role_ids: List[int] = field(default_factory=list)
    dm_enabled: bool = False
    dm_template: str = "Welcome to {server}, {user}! Enjoy your stay."
    send_goodbye: bool = False
    goodbye_channel_id: Optional[int] = None
    goodbye_template: str = "Goodbye {user}, we'll miss you!"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WelcomeSettings:
        return cls(
            guild_id=int(data["guild_id"]),
            enabled=bool(data.get("enabled", False)),
            channel_id=int(data["channel_id"]) if data.get("channel_id") else None,
            message_template=str(data.get("message_template", "Welcome {user} to **{server}**! You are member #{member_count}.")),
            embed_enabled=bool(data.get("embed_enabled", True)),
            custom_image_enabled=bool(data.get("custom_image_enabled", False)),
            auto_role_ids=[int(r) for r in data.get("auto_role_ids", [])],
            dm_enabled=bool(data.get("dm_enabled", False)),
            dm_template=str(data.get("dm_template", "Welcome to {server}, {user}! Enjoy your stay.")),
            send_goodbye=bool(data.get("send_goodbye", False)),
            goodbye_channel_id=int(data["goodbye_channel_id"]) if data.get("goodbye_channel_id") else None,
            goodbye_template=str(data.get("goodbye_template", "Goodbye {user}, we'll miss you!")),
            created_at=data.get("created_at", utc_now()),
            updated_at=data.get("updated_at", utc_now()),
        )


@dataclass
class CommandUsage:
    """Command telemetry and analytics schema for command_usage collection."""
    command_name: str
    command_type: str  # 'slash' or 'prefix'
    guild_id: Optional[int]
    user_id: int
    channel_id: int
    success: bool
    execution_time_ms: float
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModerationLog:
    """Audit and moderation action schema for moderation_logs collection."""
    guild_id: int
    case_id: int
    user_id: int
    moderator_id: int
    action: str  # 'warn', 'kick', 'ban', 'unban', 'timeout'
    reason: str = "No reason provided"
    duration_seconds: Optional[int] = None
    timestamp: datetime = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CustomCommandModel:
    """Schema for custom_commands table."""
    guild_id: int
    name: str
    response_type: str = "text"  # 'text' or 'embed'
    content: Optional[str] = None
    embed_data: Optional[Dict[str, Any]] = None
    permission_level: str = "everyone"  # 'everyone', 'moderator', 'administrator'
    required_role_ids: List[int] = field(default_factory=list)
    cooldown_seconds: int = 0
    is_enabled: bool = True
    creator_id: int = 0
    uses: int = 0
    last_used_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> CustomCommandModel:
        """Construct model from SQLite row dictionary."""
        embed_raw = row.get("embed_data")
        embed_dict = None
        if embed_raw:
            try:
                embed_dict = json.loads(embed_raw) if isinstance(embed_raw, str) else embed_raw
            except (json.JSONDecodeError, TypeError):
                embed_dict = None

        roles_raw = row.get("required_role_ids")
        role_ids = []
        if roles_raw:
            try:
                role_ids = json.loads(roles_raw) if isinstance(roles_raw, str) else roles_raw
            except (json.JSONDecodeError, TypeError):
                role_ids = []

        return cls(
            guild_id=int(row["guild_id"]),
            name=str(row["name"]),
            response_type=str(row.get("response_type", "text")),
            content=row.get("content"),
            embed_data=embed_dict,
            permission_level=str(row.get("permission_level", "everyone")),
            required_role_ids=[int(r) for r in role_ids if str(r).isdigit()],
            cooldown_seconds=int(row.get("cooldown_seconds", 0)),
            is_enabled=bool(row.get("is_enabled", 1)),
            creator_id=int(row.get("creator_id", 0)),
            uses=int(row.get("uses", 0)),
            last_used_at=row.get("last_used_at"),
            created_at=row.get("created_at", utc_now()),
            updated_at=row.get("updated_at", utc_now()),
        )


@dataclass
class CustomCommandAliasModel:
    """Schema for custom_command_aliases table."""
    guild_id: int
    alias: str
    target_command: str
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> CustomCommandAliasModel:
        return cls(
            guild_id=int(row["guild_id"]),
            alias=str(row["alias"]),
            target_command=str(row["target_command"]),
            created_at=row.get("created_at", utc_now()),
        )


@dataclass
class SoulSessionModel:
    """Schema for soul_sessions table."""
    session_id: str
    guild_id: int
    channel_id: int
    user_id: int
    last_activity_at: Any = field(default_factory=utc_now)
    created_at: Any = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> SoulSessionModel:
        return cls(
            session_id=str(row["session_id"]),
            guild_id=int(row["guild_id"]),
            channel_id=int(row["channel_id"]),
            user_id=int(row["user_id"]),
            last_activity_at=row.get("last_activity_at", utc_now()),
            created_at=row.get("created_at", utc_now()),
        )


@dataclass
class SoulMessageModel:
    """Schema for soul_messages table."""
    session_id: str
    role: str  # 'user', 'model', or 'system'
    content: str
    id: Optional[int] = None
    created_at: Any = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> SoulMessageModel:
        return cls(
            id=int(row["id"]) if row.get("id") is not None else None,
            session_id=str(row["session_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            created_at=row.get("created_at", utc_now()),
        )


@dataclass
class SoulGuildSettingsModel:
    """Schema for soul_guild_settings table."""
    guild_id: int
    enabled: bool = True
    allowed_channels: List[int] = field(default_factory=list)
    personality_style: str = "tanglish_bro"
    cooldown_seconds: float = 3.0
    max_history_turns: int = 10
    daily_quota_limit: int = 500
    updated_at: Any = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> SoulGuildSettingsModel:
        channels_raw = row.get("allowed_channels")
        channels = []
        if channels_raw:
            try:
                channels = json.loads(channels_raw) if isinstance(channels_raw, str) else channels_raw
            except (json.JSONDecodeError, TypeError):
                channels = []

        return cls(
            guild_id=int(row["guild_id"]),
            enabled=bool(row.get("enabled", 1)),
            allowed_channels=[int(c) for c in channels if str(c).isdigit()],
            personality_style=str(row.get("personality_style", "tanglish_bro")),
            cooldown_seconds=float(row.get("cooldown_seconds", 3.0)),
            max_history_turns=int(row.get("max_history_turns", 10)),
            daily_quota_limit=int(row.get("daily_quota_limit", 500)),
            updated_at=row.get("updated_at", utc_now()),
        )

