"""SQLite repository layer providing clean async accessors for all Death Bot subsystems."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bot.database.models import (
    CommandUsage,
    GuildSettings,
    ModerationLog,
    MusicSettings,
    UserProfile,
    VoiceSession,
    VoiceSettings,
    WelcomeSettings,
    utc_now,
)
from bot.database.sqlite_manager import SQLiteDatabaseManager


class GuildRepository:
    """Repository handling guild-level configuration in SQLite."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_or_create(self, guild_id: int, default_prefix: str = "!") -> GuildSettings:
        """Fetch guild settings or insert defaults."""
        row = await self.db.fetchone("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        if not row:
            await self.db.execute(
                "INSERT OR IGNORE INTO guild_settings (guild_id, prefix) VALUES (?, ?)",
                (guild_id, default_prefix),
            )
            row = await self.db.fetchone("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        if row:
            return GuildSettings(
                guild_id=row["guild_id"],
                prefix=row["prefix"],
                dj_role_ids=[],
                disabled_commands=json.loads(row["disabled_commands"]) if isinstance(row.get("disabled_commands"), str) else [],
            )
        return GuildSettings(guild_id=guild_id, prefix=default_prefix)

    async def get_prefix(self, guild_id: int, default: str = "!") -> str:
        row = await self.db.fetchone("SELECT prefix FROM guild_settings WHERE guild_id = ?", (guild_id,))
        return row["prefix"] if row else default

    async def set_prefix(self, guild_id: int, prefix: str) -> None:
        await self.db.execute(
            """INSERT INTO guild_settings (guild_id, prefix, updated_at) 
               VALUES (?, ?, CURRENT_TIMESTAMP) 
               ON CONFLICT(guild_id) DO UPDATE SET prefix = excluded.prefix, updated_at = CURRENT_TIMESTAMP""",
            (guild_id, prefix),
        )

    async def update_settings(self, guild_id: int, **kwargs: Any) -> bool:
        await self.get_or_create(guild_id)
        updates = []
        params = []
        for k, v in kwargs.items():
            updates.append(f"{k} = ?")
            params.append(json.dumps(v) if isinstance(v, (list, dict)) else v)
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(guild_id)
        await self.db.execute(f"UPDATE guild_settings SET {', '.join(updates)} WHERE guild_id = ?", tuple(params))
        return True


class UserRepository:
    """Repository handling persistent user profiles, balances, and XP."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_or_create(self, user_id: int) -> UserProfile:
        row = await self.db.fetchone("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)", (user_id,))
            row = await self.db.fetchone("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
        if row:
            return UserProfile(
                user_id=row["user_id"],
                balance=row.get("balance", 0),
                bio=row.get("bio", "A mysterious user."),
                badges=json.loads(row["badges"]) if isinstance(row.get("badges"), str) else [],
            )
        return UserProfile(user_id=user_id)

    async def update_balance(self, user_id: int, delta: int) -> int:
        await self.get_or_create(user_id)
        await self.db.execute(
            """UPDATE user_profiles 
               SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP 
               WHERE user_id = ?""",
            (delta, user_id),
        )
        row = await self.db.fetchone("SELECT balance FROM user_profiles WHERE user_id = ?", (user_id,))
        return row["balance"] if row else 0

    async def add_xp(self, user_id: int, xp_amount: int) -> UserProfile:
        # User profile / level handling
        profile = await self.get_or_create(user_id)
        return profile


class MusicRepository:
    """Repository handling guild music player settings."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_or_create(self, guild_id: int) -> MusicSettings:
        row = await self.db.fetchone("SELECT * FROM music_settings WHERE guild_id = ?", (guild_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO music_settings (guild_id) VALUES (?)", (guild_id,))
            row = await self.db.fetchone("SELECT * FROM music_settings WHERE guild_id = ?", (guild_id,))
        if row:
            return MusicSettings(
                guild_id=row["guild_id"],
                default_volume=row.get("default_volume", 100),
                max_queue_size=row.get("max_queue_size", 500),
                loop_mode=row.get("loop_mode", "off"),
                twenty_four_seven=bool(row.get("twenty_four_seven", 0)),
                dj_role_id=row.get("dj_role_id"),
                vote_skip_ratio=row.get("vote_skip_ratio", 0.5),
            )
        return MusicSettings(guild_id=guild_id)

    async def update_settings(self, guild_id: int, **kwargs: Any) -> bool:
        await self.get_or_create(guild_id)
        updates = []
        params = []
        for k, v in kwargs.items():
            if k == "dj_role_ids" and isinstance(v, list):
                k = "dj_role_id"
                v = v[0] if v else None
            updates.append(f"{k} = ?")
            params.append(1 if v is True else (0 if v is False else v))
        params.append(guild_id)
        await self.db.execute(f"UPDATE music_settings SET {', '.join(updates)} WHERE guild_id = ?", tuple(params))
        return True


class VoiceRepository:
    """Repository handling voice settings and live voice sessions."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_or_create_settings(self, guild_id: int) -> VoiceSettings:
        row = await self.db.fetchone("SELECT * FROM voice_settings WHERE guild_id = ?", (guild_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO voice_settings (guild_id) VALUES (?)", (guild_id,))
            row = await self.db.fetchone("SELECT * FROM voice_settings WHERE guild_id = ?", (guild_id,))
        if row:
            data = dict(row)
            return VoiceSettings(
                guild_id=data["guild_id"],
                enabled=bool(data.get("enabled", 1)),
                status_channel_id=data.get("status_channel_id"),
                status_message_id=data.get("status_message_id"),
                update_interval=data.get("update_interval") or data.get("auto_refresh_seconds", 60),
                track_active_time=bool(data.get("track_active_time", True)),
                notify_channel_id=data.get("notify_channel_id") or data.get("log_channel_id"),
            )
        return VoiceSettings(guild_id=guild_id)

    async def update_settings(self, guild_id: int, **kwargs: Any) -> bool:
        await self.get_or_create_settings(guild_id)
        updates = []
        params = []
        for k, v in kwargs.items():
            updates.append(f"{k} = ?")
            params.append(json.dumps(v) if isinstance(v, (list, dict)) else v)
        params.append(guild_id)
        await self.db.execute(f"UPDATE voice_settings SET {', '.join(updates)} WHERE guild_id = ?", tuple(params))
        return True

    async def start_session(self, guild_id: int, user_id: int, channel_id: int) -> VoiceSession:
        await self.end_session(guild_id, user_id)
        now = utc_now()
        await self.db.execute(
            "INSERT INTO voice_sessions (guild_id, user_id, channel_id, joined_at) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, channel_id, now.isoformat()),
        )
        return VoiceSession(guild_id=guild_id, user_id=user_id, channel_id=channel_id, joined_at=now)

    async def end_session(self, guild_id: int, user_id: int) -> Optional[VoiceSession]:
        row = await self.db.fetchone(
            "SELECT * FROM voice_sessions WHERE guild_id = ? AND user_id = ? AND left_at IS NULL ORDER BY joined_at DESC LIMIT 1",
            (guild_id, user_id),
        )
        if not row:
            return None

        now = utc_now()
        joined_str = row["joined_at"]
        try:
            joined_at = datetime.fromisoformat(joined_str) if isinstance(joined_str, str) else joined_str
            if joined_at.tzinfo is None:
                joined_at = joined_at.replace(tzinfo=timezone.utc)
            duration = int((now - joined_at).total_seconds())
        except Exception:
            duration = 0

        await self.db.execute(
            "UPDATE voice_sessions SET left_at = ?, duration_seconds = ? WHERE session_id = ?",
            (now.isoformat(), max(0, duration), row["session_id"]),
        )
        return VoiceSession(
            guild_id=guild_id,
            user_id=user_id,
            channel_id=row["channel_id"],
            joined_at=joined_at,
            left_at=now,
            duration_seconds=max(0, duration),
        )

    async def get_total_voice_time(self, guild_id: int, user_id: int) -> int:
        row = await self.db.fetchone(
            "SELECT SUM(duration_seconds) as total FROM voice_sessions WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return int(row["total"]) if row and row["total"] else 0


class WelcomeRepository:
    """Repository handling welcome/goodbye settings."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_or_create(self, guild_id: int) -> WelcomeSettings:
        row = await self.db.fetchone("SELECT * FROM welcome_settings WHERE guild_id = ?", (guild_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO welcome_settings (guild_id) VALUES (?)", (guild_id,))
            row = await self.db.fetchone("SELECT * FROM welcome_settings WHERE guild_id = ?", (guild_id,))
        if row:
            return WelcomeSettings(
                guild_id=row["guild_id"],
                enabled=bool(row.get("enabled", 0)),
                channel_id=row.get("channel_id"),
                message_template=row.get("message_template", "Welcome {user} to {server}!"),
                embed_enabled=bool(row.get("use_embed", 1)),
                auto_role_ids=json.loads(row["auto_roles"]) if isinstance(row.get("auto_roles"), str) else [],
                dm_enabled=bool(row.get("send_dm", 0)),
                dm_template=row.get("dm_template", "Welcome to {server}!"),
                send_goodbye=bool(row.get("goodbye_enabled", 0)),
                goodbye_channel_id=row.get("goodbye_channel_id"),
                goodbye_template=row.get("goodbye_template", "{user} left the server."),
            )
        return WelcomeSettings(guild_id=guild_id)

    async def update_settings(self, guild_id: int, **kwargs: Any) -> bool:
        await self.get_or_create(guild_id)
        updates = []
        params = []
        for k, v in kwargs.items():
            if k == "auto_role_ids":
                k = "auto_roles"
            elif k == "embed_enabled":
                k = "use_embed"
            elif k == "dm_enabled":
                k = "send_dm"
            elif k == "send_goodbye":
                k = "goodbye_enabled"
            updates.append(f"{k} = ?")
            params.append(json.dumps(v) if isinstance(v, (list, dict)) else (1 if v is True else (0 if v is False else v)))
        params.append(guild_id)
        await self.db.execute(f"UPDATE welcome_settings SET {', '.join(updates)} WHERE guild_id = ?", tuple(params))
        return True


class PlaylistRepository:
    """Repository handling custom playlists in SQLite."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def create_playlist(self, guild_id: int, user_id: int, name: str) -> bool:
        clean_name = name.strip().lower()
        try:
            await self.db.execute(
                "INSERT INTO playlists (guild_id, user_id, name, tracks) VALUES (?, ?, ?, '[]')",
                (guild_id, user_id, clean_name),
            )
            return True
        except Exception:
            return False

    async def get_playlist(self, guild_id: int, user_id: int, name: str) -> Optional[Dict[str, Any]]:
        clean_name = name.strip().lower()
        row = await self.db.fetchone(
            "SELECT * FROM playlists WHERE guild_id = ? AND user_id = ? AND name = ?",
            (guild_id, user_id, clean_name),
        )
        if not row:
            return None
        res = dict(row)
        if isinstance(res.get("tracks"), str):
            res["tracks"] = json.loads(res["tracks"])
        return res

    async def list_playlists(self, guild_id: int, user_id: int) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM playlists WHERE guild_id = ? AND user_id = ? ORDER BY name ASC",
            (guild_id, user_id),
        )
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("tracks"), str):
                d["tracks"] = json.loads(d["tracks"])
            result.append(d)
        return result

    async def add_track(self, guild_id: int, user_id: int, name: str, track_data: Dict[str, Any], max_tracks: int = 100) -> bool:
        pl = await self.get_playlist(guild_id, user_id, name)
        if not pl:
            return False
        tracks = pl.get("tracks", [])
        if len(tracks) >= max_tracks:
            return False
        tracks.append(track_data)
        clean_name = name.strip().lower()
        await self.db.execute(
            "UPDATE playlists SET tracks = ?, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ? AND user_id = ? AND name = ?",
            (json.dumps(tracks), guild_id, user_id, clean_name),
        )
        return True

    async def remove_track(self, guild_id: int, user_id: int, name: str, index: int) -> bool:
        pl = await self.get_playlist(guild_id, user_id, name)
        if not pl:
            return False
        tracks = pl.get("tracks", [])
        idx = index - 1
        if 0 <= idx < len(tracks):
            tracks.pop(idx)
            clean_name = name.strip().lower()
            await self.db.execute(
                "UPDATE playlists SET tracks = ?, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ? AND user_id = ? AND name = ?",
                (json.dumps(tracks), guild_id, user_id, clean_name),
            )
            return True
        return False

    async def delete_playlist(self, guild_id: int, user_id: int, name: str) -> bool:
        clean_name = name.strip().lower()
        cursor = await self.db.execute(
            "DELETE FROM playlists WHERE guild_id = ? AND user_id = ? AND name = ?",
            (guild_id, user_id, clean_name),
        )
        return cursor.rowcount > 0


class VCRepository:
    """Repository for voice channel bans, ownership, and temp channels."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_vc_bans(self, guild_id: int, channel_id: int) -> List[Dict]:
        return await self.db.fetchall(
            "SELECT * FROM vc_bans WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )

    async def add_vc_ban(self, guild_id: int, channel_id: int, user_id: int,
                          banned_by: int, reason: str = "No reason provided") -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO vc_bans (guild_id, channel_id, user_id, banned_by, reason) VALUES (?,?,?,?,?)",
            (guild_id, channel_id, user_id, banned_by, reason),
        )

    async def remove_vc_ban(self, guild_id: int, channel_id: int, user_id: int) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM vc_bans WHERE guild_id=? AND channel_id=? AND user_id=?",
            (guild_id, channel_id, user_id),
        )
        return cursor.rowcount > 0

    async def is_vc_banned(self, guild_id: int, channel_id: int, user_id: int) -> bool:
        row = await self.db.fetchone(
            "SELECT 1 FROM vc_bans WHERE guild_id=? AND channel_id=? AND user_id=?",
            (guild_id, channel_id, user_id),
        )
        return row is not None

    async def clear_all_vc_bans(self, guild_id: int, channel_id: int) -> int:
        cursor = await self.db.execute(
            "DELETE FROM vc_bans WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        return cursor.rowcount

    async def set_vc_loop(self, guild_id: int, channel_id: int, user_id: int, activated_by: int) -> None:
        """Activate or update a member's VC Loop destination channel."""
        await self.db.execute(
            "INSERT OR REPLACE INTO vc_loops (guild_id, channel_id, user_id, activated_by, active) VALUES (?,?,?,?,1)",
            (guild_id, channel_id, user_id, activated_by),
        )

    async def get_vc_loop(self, guild_id: int, user_id: int) -> Optional[Dict]:
        """Fetch active VC Loop configuration for a user in a guild."""
        return await self.db.fetchone(
            "SELECT * FROM vc_loops WHERE guild_id=? AND user_id=? AND active=1",
            (guild_id, user_id),
        )

    async def remove_vc_loop(self, guild_id: int, user_id: int) -> bool:
        """Stop/remove active VC Loop for a member."""
        cursor = await self.db.execute(
            "DELETE FROM vc_loops WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        return cursor.rowcount > 0

    async def get_channel_vc_loops(self, guild_id: int, channel_id: int) -> List[Dict]:
        """List all active VC Loops pointing to a destination voice channel."""
        return await self.db.fetchall(
            "SELECT * FROM vc_loops WHERE guild_id=? AND channel_id=? AND active=1",
            (guild_id, channel_id),
        )

    async def set_vc_loop_optout(self, guild_id: int, user_id: int) -> None:
        """Record member opt-out from VC loops."""
        await self.db.execute(
            "INSERT OR REPLACE INTO vc_loop_optouts (guild_id, user_id) VALUES (?,?)",
            (guild_id, user_id),
        )

    async def is_vc_loop_opted_out(self, guild_id: int, user_id: int) -> bool:
        """Check if user has opted out of automated VC movement."""
        row = await self.db.fetchone(
            "SELECT 1 FROM vc_loop_optouts WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        return row is not None

    async def remove_vc_loop_optout(self, guild_id: int, user_id: int) -> bool:
        """Clear member opt-out allowing VC loop automation again."""
        cursor = await self.db.execute(
            "DELETE FROM vc_loop_optouts WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        return cursor.rowcount > 0

    async def get_vc_owner(self, guild_id: int, channel_id: int) -> Optional[Dict]:
        return await self.db.fetchone(
            "SELECT * FROM vc_ownership WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )

    async def set_vc_owner(self, guild_id: int, channel_id: int, owner_id: int) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO vc_ownership (guild_id, channel_id, owner_id) VALUES (?,?,?)",
            (guild_id, channel_id, owner_id),
        )

    async def clear_vc_owner(self, guild_id: int, channel_id: int) -> None:
        await self.db.execute(
            "DELETE FROM vc_ownership WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )

    async def get_dashboard_panel(self, guild_id: int, panel_type: str) -> Optional[Dict]:
        return await self.db.fetchone(
            "SELECT * FROM dashboard_panels WHERE guild_id=? AND panel_type=?",
            (guild_id, panel_type),
        )

    async def set_dashboard_panel(self, guild_id: int, panel_type: str, channel_id: int, message_id: int) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO dashboard_panels (guild_id, panel_type, channel_id, message_id) VALUES (?,?,?,?)",
            (guild_id, panel_type, channel_id, message_id),
        )

    async def register_temp_channel(self, guild_id: int, channel_id: int, owner_id: int) -> None:
        """Register a temporary voice channel and record initial ownership."""
        await self.db.execute(
            "INSERT OR REPLACE INTO vc_temp_channels (guild_id, channel_id, owner_id) VALUES (?,?,?)",
            (guild_id, channel_id, owner_id),
        )
        await self.set_vc_owner(guild_id, channel_id, owner_id)

    async def is_temp_channel(self, guild_id: int, channel_id: int) -> bool:
        """Check if a voice channel is registered as temporary."""
        row = await self.db.fetchone(
            "SELECT 1 FROM vc_temp_channels WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        return row is not None

    async def remove_temp_channel(self, guild_id: int, channel_id: int) -> None:
        """Deregister a temporary voice channel and remove ownership."""
        await self.db.execute(
            "DELETE FROM vc_temp_channels WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        await self.clear_vc_owner(guild_id, channel_id)

    async def get_temp_channels(self, guild_id: int) -> List[int]:
        """Fetch all registered temporary voice channel IDs for a guild."""
        rows = await self.db.fetchall(
            "SELECT channel_id FROM vc_temp_channels WHERE guild_id=?",
            (guild_id,),
        )
        return [r["channel_id"] for r in rows if "channel_id" in r]

    async def add_staff_role(self, guild_id: int, role_id: int, added_by: int) -> bool:
        """Register an authorized VC staff role for a guild."""
        cursor = await self.db.execute(
            "INSERT OR IGNORE INTO vc_staff_roles (guild_id, role_id, added_by) VALUES (?,?,?)",
            (guild_id, role_id, added_by),
        )
        rowcount = getattr(cursor, "rowcount", 0)
        return isinstance(rowcount, int) and rowcount > 0

    async def remove_staff_role(self, guild_id: int, role_id: int) -> bool:
        """Revoke a VC staff role for a guild."""
        cursor = await self.db.execute(
            "DELETE FROM vc_staff_roles WHERE guild_id=? AND role_id=?",
            (guild_id, role_id),
        )
        rowcount = getattr(cursor, "rowcount", 0)
        return isinstance(rowcount, int) and rowcount > 0

    async def get_staff_roles(self, guild_id: int) -> List[int]:
        """Fetch all authorized VC staff role IDs for a guild."""
        rows = await self.db.fetchall(
            "SELECT role_id FROM vc_staff_roles WHERE guild_id=?",
            (guild_id,),
        )
        return [r["role_id"] for r in rows if "role_id" in r]

    async def get_staff_role_records(self, guild_id: int) -> List[Dict[str, Any]]:
        """Fetch detailed records of authorized VC staff roles."""
        return await self.db.fetchall(
            "SELECT role_id, added_by, added_at FROM vc_staff_roles WHERE guild_id=? ORDER BY added_at ASC",
            (guild_id,),
        )

    async def is_staff(self, guild_id: int, role_ids: List[int]) -> bool:
        """Check if any of the provided role IDs has authorized VC staff permissions."""
        if not role_ids:
            return False
        placeholders = ",".join("?" for _ in role_ids)
        row = await self.db.fetchone(
            f"SELECT 1 FROM vc_staff_roles WHERE guild_id=? AND role_id IN ({placeholders}) LIMIT 1",
            (guild_id, *role_ids),
        )
        return row is not None

    async def get_staff_bulk_actions_allowed(self, guild_id: int) -> bool:
        """Check if staff bulk VC actions (mute/deafen/kick/clear bans) are enabled by the owner. Defaults to False."""
        row = await self.db.fetchone(
            "SELECT allow_bulk_actions FROM vc_staff_settings WHERE guild_id=?",
            (guild_id,),
        )
        if not row:
            return False
        return bool(row.get("allow_bulk_actions", 0))

    async def set_staff_bulk_actions_allowed(self, guild_id: int, allowed: bool, updated_by: int) -> None:
        """Update owner setting for staff bulk VC actions."""
        val = 1 if allowed else 0
        await self.db.execute(
            """INSERT INTO vc_staff_settings (guild_id, allow_bulk_actions, updated_by, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(guild_id) DO UPDATE SET
                   allow_bulk_actions=excluded.allow_bulk_actions,
                   updated_by=excluded.updated_by,
                   updated_at=CURRENT_TIMESTAMP""",
            (guild_id, val, updated_by),
        )

    # ----------------------------------------------------
    # KROVEX Voice Control Centre Repositories
    # ----------------------------------------------------
    async def log_action(
        self,
        guild_id: int,
        executor_id: int,
        action_type: str,
        scope: str,
        source_channel_id: Optional[int] = None,
        destination_channel_id: Optional[int] = None,
        target_count: int = 0,
        success_count: int = 0,
        fail_count: int = 0,
        details: str = "",
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO vc_action_logs 
               (guild_id, executor_id, action_type, scope, source_channel_id, destination_channel_id, target_count, success_count, fail_count, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, executor_id, action_type, scope, source_channel_id, destination_channel_id, target_count, success_count, fail_count, details),
        )
        return getattr(cursor, "lastrowid", 0) or 0

    async def get_action_logs(
        self,
        guild_id: int,
        limit: int = 15,
        offset: int = 0,
        filter_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if filter_type and filter_type != "all":
            if filter_type == "failed":
                return await self.db.fetchall(
                    "SELECT * FROM vc_action_logs WHERE guild_id=? AND fail_count > 0 ORDER BY id DESC LIMIT ? OFFSET ?",
                    (guild_id, limit, offset),
                )
            elif filter_type == "bulk":
                return await self.db.fetchall(
                    "SELECT * FROM vc_action_logs WHERE guild_id=? AND (scope IN ('server_wide', 'current_vc', 'selected_channels') OR target_count > 1) ORDER BY id DESC LIMIT ? OFFSET ?",
                    (guild_id, limit, offset),
                )
            elif filter_type == "voice":
                return await self.db.fetchall(
                    "SELECT * FROM vc_action_logs WHERE guild_id=? AND (action_type LIKE '%voice%' OR action_type LIKE '%channel%') ORDER BY id DESC LIMIT ? OFFSET ?",
                    (guild_id, limit, offset),
                )
            elif filter_type == "member":
                return await self.db.fetchall(
                    "SELECT * FROM vc_action_logs WHERE guild_id=? AND action_type IN ('mute', 'unmute', 'deafen', 'undeafen', 'move', 'disconnect') ORDER BY id DESC LIMIT ? OFFSET ?",
                    (guild_id, limit, offset),
                )
            else:
                return await self.db.fetchall(
                    "SELECT * FROM vc_action_logs WHERE guild_id=? AND action_type=? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (guild_id, filter_type, limit, offset),
                )
        return await self.db.fetchall(
            "SELECT * FROM vc_action_logs WHERE guild_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (guild_id, limit, offset),
        )

    async def get_action_log_count(self, guild_id: int, filter_type: Optional[str] = None) -> int:
        if filter_type and filter_type != "all":
            if filter_type == "failed":
                row = await self.db.fetchone(
                    "SELECT COUNT(*) as c FROM vc_action_logs WHERE guild_id=? AND fail_count > 0",
                    (guild_id,),
                )
            elif filter_type == "bulk":
                row = await self.db.fetchone(
                    "SELECT COUNT(*) as c FROM vc_action_logs WHERE guild_id=? AND (scope IN ('server_wide', 'current_vc', 'selected_channels') OR target_count > 1)",
                    (guild_id,),
                )
            else:
                row = await self.db.fetchone(
                    "SELECT COUNT(*) as c FROM vc_action_logs WHERE guild_id=? AND action_type=?",
                    (guild_id, filter_type),
                )
        else:
            row = await self.db.fetchone(
                "SELECT COUNT(*) as c FROM vc_action_logs WHERE guild_id=?",
                (guild_id,),
            )
        return row["c"] if row else 0

    async def get_presets(self, guild_id: int) -> List[Dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM vc_presets WHERE guild_id=? ORDER BY preset_name ASC",
            (guild_id,),
        )

    async def get_preset(self, guild_id: int, preset_name: str) -> Optional[Dict[str, Any]]:
        return await self.db.fetchone(
            "SELECT * FROM vc_presets WHERE guild_id=? AND preset_name=?",
            (guild_id, preset_name),
        )

    async def save_preset(
        self,
        guild_id: int,
        preset_name: str,
        description: str,
        config_json: str,
        created_by: int,
    ) -> None:
        await self.db.execute(
            """INSERT INTO vc_presets (guild_id, preset_name, description, config_json, created_by, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(guild_id, preset_name) DO UPDATE SET
                   description=excluded.description,
                   config_json=excluded.config_json,
                   updated_at=CURRENT_TIMESTAMP""",
            (guild_id, preset_name, description, config_json, created_by),
        )

    async def delete_preset(self, guild_id: int, preset_name: str) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM vc_presets WHERE guild_id=? AND preset_name=?",
            (guild_id, preset_name),
        )
        return getattr(cursor, "rowcount", 0) > 0

    async def save_temp_action(
        self,
        guild_id: int,
        action_type: str,
        target_id: int,
        revert_data: str,
        expires_at: float,
        created_by: int,
    ) -> int:
        now = time.time()
        cursor = await self.db.execute(
            """INSERT INTO vc_temporary_actions 
               (guild_id, action_type, target_id, revert_data, expires_at, created_by, created_at, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (guild_id, action_type, target_id, revert_data, expires_at, created_by, now),
        )
        return getattr(cursor, "lastrowid", 0) or 0

    async def get_active_temp_actions(self) -> List[Dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM vc_temporary_actions WHERE active=1 ORDER BY expires_at ASC"
        )

    async def deactivate_temp_action(self, action_id: int) -> bool:
        cursor = await self.db.execute(
            "UPDATE vc_temporary_actions SET active=0 WHERE id=?",
            (action_id,),
        )
        return getattr(cursor, "rowcount", 0) > 0

    async def save_permission_backup(
        self,
        guild_id: int,
        channel_id: int,
        backup_type: str,
        overwrites_json: str,
    ) -> None:
        await self.db.execute(
            """INSERT INTO vc_channel_permission_backups (guild_id, channel_id, backup_type, overwrites_json, saved_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (guild_id, channel_id, backup_type, overwrites_json),
        )

    async def get_permission_backup(
        self,
        guild_id: int,
        channel_id: int,
        backup_type: str,
    ) -> Optional[Dict[str, Any]]:
        return await self.db.fetchone(
            "SELECT * FROM vc_channel_permission_backups WHERE guild_id=? AND channel_id=? AND backup_type=? ORDER BY id DESC LIMIT 1",
            (guild_id, channel_id, backup_type),
        )

    async def delete_permission_backup(
        self,
        guild_id: int,
        channel_id: int,
        backup_type: str,
    ) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM vc_channel_permission_backups WHERE guild_id=? AND channel_id=? AND backup_type=?",
            (guild_id, channel_id, backup_type),
        )
        return getattr(cursor, "rowcount", 0) > 0

    async def get_control_settings(self, guild_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone(
            "SELECT * FROM vc_control_settings WHERE guild_id=?",
            (guild_id,),
        )
        if not row:
            return {
                "guild_id": guild_id,
                "afk_channel_id": None,
                "afk_timeout_seconds": 300,
                "meeting_exempt_roles": [],
                "announcement_speakers": [],
                "staff_roles": [],
            }
        res = dict(row)
        for key in ["meeting_exempt_roles", "announcement_speakers", "staff_roles"]:
            if key in res and isinstance(res[key], str):
                try:
                    res[key] = json.loads(res[key])
                except Exception:
                    res[key] = []
        return res

    async def update_control_settings(
        self,
        guild_id: int,
        afk_channel_id: Optional[int] = None,
        afk_timeout_seconds: Optional[int] = None,
        meeting_exempt_roles: Optional[List[int]] = None,
        announcement_speakers: Optional[List[int]] = None,
        staff_roles: Optional[List[int]] = None,
        updated_by: Optional[int] = None,
    ) -> None:
        curr = await self.get_control_settings(guild_id)
        new_afk = afk_channel_id if afk_channel_id is not None else curr.get("afk_channel_id")
        new_timeout = afk_timeout_seconds if afk_timeout_seconds is not None else curr.get("afk_timeout_seconds", 300)
        new_exempt = json.dumps(meeting_exempt_roles if meeting_exempt_roles is not None else curr.get("meeting_exempt_roles", []))
        new_speakers = json.dumps(announcement_speakers if announcement_speakers is not None else curr.get("announcement_speakers", []))
        new_staff = json.dumps(staff_roles if staff_roles is not None else curr.get("staff_roles", []))

        await self.db.execute(
            """INSERT INTO vc_control_settings 
               (guild_id, afk_channel_id, afk_timeout_seconds, meeting_exempt_roles, announcement_speakers, staff_roles, updated_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(guild_id) DO UPDATE SET
                   afk_channel_id=excluded.afk_channel_id,
                   afk_timeout_seconds=excluded.afk_timeout_seconds,
                   meeting_exempt_roles=excluded.meeting_exempt_roles,
                   announcement_speakers=excluded.announcement_speakers,
                   staff_roles=excluded.staff_roles,
                   updated_by=excluded.updated_by,
                   updated_at=CURRENT_TIMESTAMP""",
            (guild_id, new_afk, new_timeout, new_exempt, new_speakers, new_staff, updated_by),
        )


class AutomodRepository:
    """Repository handling automod rules and settings."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_settings(self, guild_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM automod_settings WHERE guild_id = ?", (guild_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO automod_settings (guild_id) VALUES (?)", (guild_id,))
            row = await self.db.fetchone("SELECT * FROM automod_settings WHERE guild_id = ?", (guild_id,))
        res = dict(row) if row else {}
        for f in ["bad_words_list", "exempt_roles", "exempt_channels"]:
            if f in res and isinstance(res[f], str):
                try:
                    res[f] = json.loads(res[f])
                except Exception:
                    res[f] = []
        return res

    async def update_settings(self, guild_id: int, **kwargs: Any) -> None:
        await self.get_settings(guild_id)
        updates = []
        params = []
        for k, v in kwargs.items():
            updates.append(f"{k} = ?")
            params.append(json.dumps(v) if isinstance(v, (list, dict)) else v)
        params.append(guild_id)
        await self.db.execute(f"UPDATE automod_settings SET {', '.join(updates)} WHERE guild_id = ?", tuple(params))


class InviteRepository:
    """Repository handling invite counts and inviter logs."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_settings(self, guild_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM invite_settings WHERE guild_id = ?", (guild_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO invite_settings (guild_id) VALUES (?)", (guild_id,))
            row = await self.db.fetchone("SELECT * FROM invite_settings WHERE guild_id = ?", (guild_id,))
        return dict(row) if row else {}

    async def get_user_invites(self, guild_id: int, user_id: int) -> Dict[str, int]:
        row = await self.db.fetchone("SELECT * FROM invite_counts WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        if not row:
            return {"regular": 0, "bonus": 0, "fake": 0, "leaves": 0, "total": 0}
        total = row["regular"] + row["bonus"] - row["fake"] - row["leaves"]
        return {
            "regular": row["regular"],
            "bonus": row["bonus"],
            "fake": row["fake"],
            "leaves": row["leaves"],
            "total": max(0, total),
        }

    async def add_invite(self, guild_id: int, user_id: int, inviter_id: int, code: str, is_fake: bool = False) -> None:
        await self.db.execute(
            "INSERT INTO invite_history (guild_id, user_id, inviter_id, code, is_fake) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, inviter_id, code, 1 if is_fake else 0),
        )
        field = "fake" if is_fake else "regular"
        await self.db.execute(
            f"""INSERT INTO invite_counts (guild_id, user_id, {field}) 
               VALUES (?, ?, 1) 
               ON CONFLICT(guild_id, user_id) DO UPDATE SET {field} = {field} + 1""",
            (guild_id, inviter_id),
        )

    async def get_leaderboard(self, guild_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall(
            """SELECT user_id, regular, bonus, fake, leaves, (regular + bonus - fake - leaves) AS total 
               FROM invite_counts WHERE guild_id = ? ORDER BY total DESC LIMIT ?""",
            (guild_id, limit),
        )
        return rows


class LevelRepository:
    """Repository handling XP, level progression, rewards, exemptions, and leaderboards."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_settings(self, guild_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM leveling_settings WHERE guild_id = ?", (guild_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO leveling_settings (guild_id) VALUES (?)", (guild_id,))
            row = await self.db.fetchone("SELECT * FROM leveling_settings WHERE guild_id = ?", (guild_id,))
        return dict(row) if row else {}

    async def update_settings(self, guild_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return
        keys = list(kwargs.keys())
        set_clause = ", ".join(f"{k} = ?" for k in keys)
        values = list(kwargs.values()) + [guild_id]
        await self.get_settings(guild_id)
        await self.db.execute(f"UPDATE leveling_settings SET {set_clause} WHERE guild_id = ?", tuple(values))

    async def get_member(self, guild_id: int, user_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT xp, level, messages_count, last_xp_at FROM member_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        if row:
            return dict(row)
        return {"xp": 0, "level": 0, "messages_count": 0, "last_xp_at": None}

    async def add_xp(self, guild_id: int, user_id: int, xp_amount: int) -> Tuple[int, int, bool]:
        row = await self.db.fetchone("SELECT xp, level, messages_count FROM member_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        current_xp = row["xp"] if row else 0
        current_lvl = row["level"] if row else 0
        msg_count = row["messages_count"] if row else 0

        new_xp = current_xp + xp_amount
        needed_for_next = (current_lvl + 1) * 150
        leveled_up = False
        new_lvl = current_lvl

        if new_xp >= needed_for_next:
            new_lvl += 1
            leveled_up = True

        await self.db.execute(
            """INSERT INTO member_levels (guild_id, user_id, xp, level, messages_count, last_xp_at) 
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) 
               ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = ?, level = ?, messages_count = messages_count + 1, last_xp_at = CURRENT_TIMESTAMP""",
            (guild_id, user_id, new_xp, new_lvl, msg_count + 1, new_xp, new_lvl),
        )
        return new_xp, new_lvl, leveled_up

    async def set_xp(self, guild_id: int, user_id: int, xp: int, level: Optional[int] = None) -> None:
        if level is None:
            level = max(0, xp // 150)
        await self.db.execute(
            """INSERT INTO member_levels (guild_id, user_id, xp, level, messages_count, last_xp_at)
               VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = ?, level = ?""",
            (guild_id, user_id, xp, level, xp, level),
        )

    async def remove_xp(self, guild_id: int, user_id: int, amount: int) -> Tuple[int, int]:
        member = await self.get_member(guild_id, user_id)
        new_xp = max(0, member["xp"] - amount)
        new_lvl = max(0, new_xp // 150)
        await self.set_xp(guild_id, user_id, new_xp, new_lvl)
        return new_xp, new_lvl

    async def reset_member(self, guild_id: int, user_id: int) -> None:
        await self.db.execute("DELETE FROM member_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))

    async def reset_guild(self, guild_id: int) -> int:
        cursor = await self.db.execute("DELETE FROM member_levels WHERE guild_id = ?", (guild_id,))
        return cursor.rowcount

    async def get_rank(self, guild_id: int, user_id: int) -> int:
        member = await self.get_member(guild_id, user_id)
        row = await self.db.fetchone("SELECT COUNT(*) as rank_count FROM member_levels WHERE guild_id = ? AND xp > ?", (guild_id, member["xp"]))
        return (row["rank_count"] if row else 0) + 1

    async def get_leaderboard(self, guild_id: int, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall("SELECT user_id, xp, level, messages_count FROM member_levels WHERE guild_id = ? ORDER BY xp DESC LIMIT ? OFFSET ?", (guild_id, limit, offset))
        return [dict(r) for r in rows]

    async def add_reward(self, guild_id: int, level: int, role_id: int) -> None:
        await self.db.execute("INSERT OR REPLACE INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?)", (guild_id, level, role_id))

    async def remove_reward(self, guild_id: int, level: int) -> bool:
        cursor = await self.db.execute("DELETE FROM level_rewards WHERE guild_id = ? AND level = ?", (guild_id, level))
        return cursor.rowcount > 0

    async def get_rewards(self, guild_id: int) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall("SELECT level, role_id FROM level_rewards WHERE guild_id = ? ORDER BY level ASC", (guild_id,))
        return [dict(r) for r in rows]

    async def add_exemption(self, guild_id: int, target_id: int, target_type: str) -> None:
        await self.db.execute("INSERT OR IGNORE INTO level_exemptions (guild_id, target_id, target_type) VALUES (?, ?, ?)", (guild_id, target_id, target_type))

    async def remove_exemption(self, guild_id: int, target_id: int, target_type: str) -> bool:
        cursor = await self.db.execute("DELETE FROM level_exemptions WHERE guild_id = ? AND target_id = ? AND target_type = ?", (guild_id, target_id, target_type))
        return cursor.rowcount > 0

    async def is_exempt(self, guild_id: int, channel_id: int, role_ids: List[int]) -> bool:
        ch_row = await self.db.fetchone("SELECT 1 FROM level_exemptions WHERE guild_id = ? AND target_id = ? AND target_type = 'channel'", (guild_id, channel_id))
        if ch_row:
            return True
        if role_ids:
            placeholders = ",".join("?" for _ in role_ids)
            role_row = await self.db.fetchone(f"SELECT 1 FROM level_exemptions WHERE guild_id = ? AND target_type = 'role' AND target_id IN ({placeholders})", tuple([guild_id] + role_ids))
            if role_row:
                return True
        return False

    async def get_guild_stats(self, guild_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT COUNT(*) as total_users, SUM(xp) as total_xp, SUM(messages_count) as total_msgs, MAX(level) as highest_level FROM member_levels WHERE guild_id = ?", (guild_id,))
        return dict(row) if row else {"total_users": 0, "total_xp": 0, "total_msgs": 0, "highest_level": 0}


class TicketRepository:
    """Repository handling support tickets, categories, participants, ratings, and stats."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_settings(self, guild_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM ticket_settings WHERE guild_id = ?", (guild_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO ticket_settings (guild_id) VALUES (?)", (guild_id,))
            row = await self.db.fetchone("SELECT * FROM ticket_settings WHERE guild_id = ?", (guild_id,))
        return dict(row) if row else {}

    async def update_settings(self, guild_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return
        keys = list(kwargs.keys())
        set_clause = ", ".join(f"{k} = ?" for k in keys)
        values = list(kwargs.values()) + [guild_id]
        await self.get_settings(guild_id)
        await self.db.execute(f"UPDATE ticket_settings SET {set_clause} WHERE guild_id = ?", tuple(values))

    async def create_category(
        self,
        guild_id: int,
        name: str,
        emoji: str = "🎫",
        description: str = "",
        category_channel_id: Optional[int] = None,
        staff_role_id: Optional[int] = None,
        naming_scheme: str = "ticket-{number}",
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO ticket_categories (guild_id, name, emoji, description, category_channel_id, staff_role_id, naming_scheme)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, name, emoji, description, category_channel_id, staff_role_id, naming_scheme),
        )
        return cursor.lastrowid

    async def get_categories(self, guild_id: int) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall("SELECT * FROM ticket_categories WHERE guild_id = ? ORDER BY id ASC", (guild_id,))
        return [dict(r) for r in rows]

    async def get_category(self, category_id: int) -> Optional[Dict[str, Any]]:
        row = await self.db.fetchone("SELECT * FROM ticket_categories WHERE id = ?", (category_id,))
        return dict(row) if row else None

    async def delete_category(self, guild_id: int, name_or_id: Any) -> bool:
        if str(name_or_id).isdigit():
            cursor = await self.db.execute("DELETE FROM ticket_categories WHERE guild_id = ? AND id = ?", (guild_id, int(name_or_id)))
        else:
            cursor = await self.db.execute("DELETE FROM ticket_categories WHERE guild_id = ? AND name = ?", (guild_id, str(name_or_id)))
        return cursor.rowcount > 0

    async def create_ticket(
        self,
        guild_id: int,
        channel_id: int,
        creator_id: int,
        category_id: Optional[int] = None,
    ) -> int:
        settings = await self.get_settings(guild_id)
        ticket_number = (settings.get("ticket_counter") or 0) + 1
        await self.db.execute("UPDATE ticket_settings SET ticket_counter = ? WHERE guild_id = ?", (ticket_number, guild_id))

        cursor = await self.db.execute(
            """INSERT INTO tickets (guild_id, channel_id, creator_id, category_id, ticket_number, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'open', CURRENT_TIMESTAMP)""",
            (guild_id, channel_id, creator_id, category_id, ticket_number),
        )
        ticket_id = cursor.lastrowid
        await self.add_participant(ticket_id, creator_id, creator_id)
        return ticket_id

    async def get_ticket_by_channel(self, channel_id: int) -> Optional[Dict[str, Any]]:
        row = await self.db.fetchone("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,))
        return dict(row) if row else None

    async def get_ticket(self, ticket_id: int) -> Optional[Dict[str, Any]]:
        row = await self.db.fetchone("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
        return dict(row) if row else None

    async def get_user_open_tickets(self, guild_id: int, user_id: int) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall("SELECT * FROM tickets WHERE guild_id = ? AND creator_id = ? AND status != 'closed'", (guild_id, user_id))
        return [dict(r) for r in rows]

    async def close_ticket(self, channel_id: int, closed_by: int, reason: Optional[str] = None) -> bool:
        cursor = await self.db.execute(
            "UPDATE tickets SET status = 'closed', closed_by = ?, close_reason = ?, closed_at = CURRENT_TIMESTAMP WHERE channel_id = ?",
            (closed_by, reason or "No reason provided", channel_id),
        )
        return cursor.rowcount > 0

    async def reopen_ticket(self, channel_id: int) -> bool:
        cursor = await self.db.execute(
            "UPDATE tickets SET status = 'open', closed_by = NULL, close_reason = NULL, closed_at = NULL WHERE channel_id = ?",
            (channel_id,),
        )
        return cursor.rowcount > 0

    async def claim_ticket(self, channel_id: int, staff_id: int) -> bool:
        cursor = await self.db.execute(
            "UPDATE tickets SET claimed_by = ?, status = 'claimed' WHERE channel_id = ?",
            (staff_id, channel_id),
        )
        return cursor.rowcount > 0

    async def unclaim_ticket(self, channel_id: int) -> bool:
        cursor = await self.db.execute(
            "UPDATE tickets SET claimed_by = NULL, status = 'open' WHERE channel_id = ?",
            (channel_id,),
        )
        return cursor.rowcount > 0

    async def lock_ticket(self, channel_id: int) -> bool:
        cursor = await self.db.execute("UPDATE tickets SET status = 'locked' WHERE channel_id = ?", (channel_id,))
        return cursor.rowcount > 0

    async def unlock_ticket(self, channel_id: int) -> bool:
        cursor = await self.db.execute("UPDATE tickets SET status = 'open' WHERE channel_id = ?", (channel_id,))
        return cursor.rowcount > 0

    async def set_reason(self, channel_id: int, reason: str) -> bool:
        cursor = await self.db.execute("UPDATE tickets SET close_reason = ? WHERE channel_id = ?", (reason, channel_id))
        return cursor.rowcount > 0

    async def set_rating(self, channel_id: int, rating: int, feedback: Optional[str] = None) -> bool:
        cursor = await self.db.execute(
            "UPDATE tickets SET rating = ?, rating_feedback = ? WHERE channel_id = ? AND rating IS NULL",
            (rating, feedback, channel_id),
        )
        return cursor.rowcount > 0

    async def add_participant(self, ticket_id: int, user_id: int, added_by: int) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO ticket_participants (ticket_id, user_id, added_by) VALUES (?, ?, ?)",
            (ticket_id, user_id, added_by),
        )

    async def remove_participant(self, ticket_id: int, user_id: int) -> None:
        await self.db.execute("DELETE FROM ticket_participants WHERE ticket_id = ? AND user_id = ?", (ticket_id, user_id))

    async def get_participants(self, ticket_id: int) -> List[int]:
        rows = await self.db.fetchall("SELECT user_id FROM ticket_participants WHERE ticket_id = ?", (ticket_id,))
        return [r["user_id"] for r in rows]

    async def blacklist_user(self, guild_id: int, user_id: int, reason: str, blacklisted_by: int) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO ticket_blacklists (guild_id, user_id, reason, blacklisted_by) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, reason, blacklisted_by),
        )

    async def unblacklist_user(self, guild_id: int, user_id: int) -> bool:
        cursor = await self.db.execute("DELETE FROM ticket_blacklists WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        return cursor.rowcount > 0

    async def is_blacklisted(self, guild_id: int, user_id: int) -> bool:
        row = await self.db.fetchone("SELECT 1 FROM ticket_blacklists WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        return bool(row)

    async def get_ticket_stats(self, guild_id: int) -> Dict[str, Any]:
        total = await self.db.fetchone("SELECT COUNT(*) as count FROM tickets WHERE guild_id = ?", (guild_id,))
        open_c = await self.db.fetchone("SELECT COUNT(*) as count FROM tickets WHERE guild_id = ? AND status = 'open'", (guild_id,))
        claimed_c = await self.db.fetchone("SELECT COUNT(*) as count FROM tickets WHERE guild_id = ? AND status = 'claimed'", (guild_id,))
        closed_c = await self.db.fetchone("SELECT COUNT(*) as count FROM tickets WHERE guild_id = ? AND status = 'closed'", (guild_id,))
        avg_rating = await self.db.fetchone("SELECT AVG(rating) as avg_r FROM tickets WHERE guild_id = ? AND rating IS NOT NULL", (guild_id,))
        return {
            "total": total["count"] if total else 0,
            "open": open_c["count"] if open_c else 0,
            "claimed": claimed_c["count"] if claimed_c else 0,
            "closed": closed_c["count"] if closed_c else 0,
            "avg_rating": round(avg_rating["avg_r"], 2) if avg_rating and avg_rating["avg_r"] else 0.0,
        }


class ReactionRoleRepository:
    """Repository handling reaction roles, button panels, and dropdown menus."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def create_panel(
        self,
        message_id: int,
        guild_id: int,
        channel_id: int,
        panel_type: str = "button",
        title: str = "Role Selection",
        description: str = "Select roles below",
        max_roles: int = 0,
        exclusive: bool = False,
        required_role_id: Optional[int] = None,
    ) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO reaction_role_panels 
               (message_id, guild_id, channel_id, panel_type, title, description, max_roles, exclusive, required_role_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (message_id, guild_id, channel_id, panel_type, title, description, max_roles, 1 if exclusive else 0, required_role_id),
        )

    async def get_panel(self, message_id: int) -> Optional[Dict[str, Any]]:
        return await self.db.fetchone("SELECT * FROM reaction_role_panels WHERE message_id = ?", (message_id,))

    async def get_panels(self, guild_id: int) -> List[Dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM reaction_role_panels WHERE guild_id = ? ORDER BY created_at DESC", (guild_id,))

    async def delete_panel(self, message_id: int) -> bool:
        await self.db.execute("DELETE FROM reaction_role_items WHERE message_id = ?", (message_id,))
        cursor = await self.db.execute("DELETE FROM reaction_role_panels WHERE message_id = ?", (message_id,))
        return cursor.rowcount > 0

    async def update_panel(self, message_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return
        updates = [f"{k} = ?" for k in kwargs]
        params = list(kwargs.values()) + [message_id]
        await self.db.execute(f"UPDATE reaction_role_panels SET {', '.join(updates)} WHERE message_id = ?", tuple(params))

    async def add_item(
        self,
        message_id: int,
        guild_id: int,
        role_id: int,
        emoji: Optional[str] = None,
        label: Optional[str] = None,
        description: Optional[str] = None,
        style: str = "primary",
    ) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO reaction_role_items 
               (message_id, guild_id, role_id, emoji, label, description, style)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (message_id, guild_id, role_id, emoji, label, description, style),
        )

    async def remove_item(self, message_id: int, role_id: int) -> bool:
        cursor = await self.db.execute("DELETE FROM reaction_role_items WHERE message_id = ? AND role_id = ?", (message_id, role_id))
        return cursor.rowcount > 0

    async def get_items(self, message_id: int) -> List[Dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM reaction_role_items WHERE message_id = ?", (message_id,))


class ServerAdminRepository:
    """Repository handling custom guild rules and prefix overrides."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def add_rule(self, guild_id: int, rule_index: int, title: str, content: str) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO server_rules (guild_id, rule_index, title, content)
               VALUES (?, ?, ?, ?)""",
            (guild_id, rule_index, title, content),
        )

    async def remove_rule(self, guild_id: int, rule_index: int) -> bool:
        cursor = await self.db.execute("DELETE FROM server_rules WHERE guild_id = ? AND rule_index = ?", (guild_id, rule_index))
        return cursor.rowcount > 0

    async def get_rules(self, guild_id: int) -> List[Dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM server_rules WHERE guild_id = ? ORDER BY rule_index ASC", (guild_id,))

    async def set_prefix(self, guild_id: int, prefix: str) -> None:
        await self.db.execute(
            """INSERT INTO guild_settings (guild_id, prefix) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET prefix = ?, updated_at = CURRENT_TIMESTAMP""",
            (guild_id, prefix, prefix),
        )


class LoggingRepository:
    """Repository handling audit logging channels, toggles, and incident records."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_settings(self, guild_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM logging_settings WHERE guild_id = ?", (guild_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO logging_settings (guild_id) VALUES (?)", (guild_id,))
            row = await self.db.fetchone("SELECT * FROM logging_settings WHERE guild_id = ?", (guild_id,))
        return dict(row) if row else {}

    async def update_settings(self, guild_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return
        await self.get_settings(guild_id)
        updates = [f"{k} = ?" for k in kwargs]
        params = list(kwargs.values()) + [guild_id]
        await self.db.execute(f"UPDATE logging_settings SET {', '.join(updates)} WHERE guild_id = ?", tuple(params))

    async def toggle_event(self, guild_id: int, event_name: str, enabled: bool) -> None:
        await self.db.execute(
            """INSERT INTO logging_event_toggles (guild_id, event_name, enabled) VALUES (?, ?, ?)
               ON CONFLICT(guild_id, event_name) DO UPDATE SET enabled = ?""",
            (guild_id, event_name, 1 if enabled else 0, 1 if enabled else 0),
        )

    async def is_event_enabled(self, guild_id: int, event_name: str, default: bool = True) -> bool:
        row = await self.db.fetchone("SELECT enabled FROM logging_event_toggles WHERE guild_id = ? AND event_name = ?", (guild_id, event_name))
        return bool(row["enabled"]) if row else default

    async def get_event_toggles(self, guild_id: int) -> Dict[str, bool]:
        rows = await self.db.fetchall("SELECT event_name, enabled FROM logging_event_toggles WHERE guild_id = ?", (guild_id,))
        return {r["event_name"]: bool(r["enabled"]) for r in rows}

    async def add_filter(self, guild_id: int, filter_type: str, target: str) -> None:
        await self.db.execute("INSERT INTO logging_filters (guild_id, filter_type, target) VALUES (?, ?, ?)", (guild_id, filter_type, target))

    async def remove_filter(self, guild_id: int, filter_type: str, target: str) -> bool:
        cursor = await self.db.execute("DELETE FROM logging_filters WHERE guild_id = ? AND filter_type = ? AND target = ?", (guild_id, filter_type, target))
        return cursor.rowcount > 0

    async def get_filters(self, guild_id: int) -> List[Dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM logging_filters WHERE guild_id = ?", (guild_id,))

    async def log_event(
        self,
        guild_id: int,
        event_type: str,
        details: str,
        actor_id: Optional[int] = None,
        target_id: Optional[int] = None,
    ) -> None:
        await self.db.execute(
            """INSERT INTO audit_event_logs (guild_id, event_type, actor_id, target_id, details)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, event_type, actor_id, target_id, details),
        )

    async def get_recent_logs(self, guild_id: int, limit: int = 20, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        if event_type:
            return await self.db.fetchall(
                "SELECT * FROM audit_event_logs WHERE guild_id = ? AND event_type = ? ORDER BY timestamp DESC LIMIT ?",
                (guild_id, event_type, limit),
            )
        return await self.db.fetchall(
            "SELECT * FROM audit_event_logs WHERE guild_id = ? ORDER BY timestamp DESC LIMIT ?",
            (guild_id, limit),
        )

    async def clear_logs(self, guild_id: int, event_type: Optional[str] = None) -> int:
        if event_type:
            cursor = await self.db.execute("DELETE FROM audit_event_logs WHERE guild_id = ? AND event_type = ?", (guild_id, event_type))
        else:
            cursor = await self.db.execute("DELETE FROM audit_event_logs WHERE guild_id = ?", (guild_id,))
        return cursor.rowcount > 0

    async def reset_settings(self, guild_id: int) -> None:
        """Reset logging channels and toggles back to default. NEVER touches audit_event_logs."""
        await self.get_settings(guild_id)
        await self.db.execute(
            """UPDATE logging_settings SET
               mod_log_channel = NULL,
               message_log_channel = NULL,
               member_log_channel = NULL,
               server_log_channel = NULL,
               voice_log_channel = NULL,
               status_log_channel = NULL,
               invite_log_channel = NULL,
               logging_enabled = 1
               WHERE guild_id = ?""",
            (guild_id,),
        )
        await self.db.execute("DELETE FROM logging_event_toggles WHERE guild_id = ?", (guild_id,))

    async def set_logging_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.get_settings(guild_id)
        await self.db.execute(
            "UPDATE logging_settings SET logging_enabled = ? WHERE guild_id = ?",
            (1 if enabled else 0, guild_id),
        )

    async def is_logging_enabled(self, guild_id: int) -> bool:
        settings = await self.get_settings(guild_id)
        return bool(settings.get("logging_enabled", 1))


class MimicRepository:
    """Repository handling per-guild bot identity, custom nickname, and avatar profiles."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_profile(self, guild_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM guild_mimic_profiles WHERE guild_id = ?", (guild_id,))
        return dict(row) if row else {}

    async def set_nickname(self, guild_id: int, nickname: Optional[str], original_name: Optional[str] = None) -> None:
        await self.db.execute(
            """INSERT INTO guild_mimic_profiles (guild_id, nickname, original_name, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(guild_id) DO UPDATE SET nickname = ?, updated_at = CURRENT_TIMESTAMP""",
            (guild_id, nickname, original_name, nickname),
        )

    async def set_avatar(self, guild_id: int, avatar_url: Optional[str]) -> None:
        await self.db.execute(
            """INSERT INTO guild_mimic_profiles (guild_id, avatar_url, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(guild_id) DO UPDATE SET avatar_url = ?, updated_at = CURRENT_TIMESTAMP""",
            (guild_id, avatar_url, avatar_url),
        )

    async def reset_profile(self, guild_id: int) -> bool:
        cursor = await self.db.execute("DELETE FROM guild_mimic_profiles WHERE guild_id = ?", (guild_id,))
        return cursor.rowcount > 0


class ModerationRepository:
    """Repository handling moderation cases and audit logs."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def add_case(self, case: ModerationLog) -> int:
        duration = getattr(case, "duration_seconds", None)
        cursor = await self.db.execute(
            """INSERT INTO moderation_logs (guild_id, user_id, moderator_id, action, reason, duration_seconds) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (case.guild_id, case.user_id, case.moderator_id, case.action, case.reason, duration),
        )
        return cursor.lastrowid

    async def get_user_cases(self, guild_id: int, user_id: int) -> List[ModerationLog]:
        rows = await self.db.fetchall(
            "SELECT * FROM moderation_logs WHERE guild_id = ? AND user_id = ? ORDER BY case_id DESC",
            (guild_id, user_id),
        )
        return [
            ModerationLog(
                guild_id=r["guild_id"],
                case_id=r["case_id"],
                user_id=r["user_id"],
                moderator_id=r["moderator_id"],
                action=r["action"],
                reason=r.get("reason", "No reason provided"),
                duration_seconds=r.get("duration_seconds"),
            )
            for r in rows
        ]

    async def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
        """Record a formal warning in SQLite and register a moderation case."""
        cursor = await self.db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason),
        )
        rowid = getattr(cursor, "lastrowid", 0)
        await self.add_case(ModerationLog(
            guild_id=guild_id,
            case_id=rowid or 0,
            user_id=user_id,
            moderator_id=moderator_id,
            action="WARN",
            reason=reason,
        ))
        return rowid if isinstance(rowid, int) else 0

    async def get_warnings(self, guild_id: int, user_id: int) -> List[Dict[str, Any]]:
        """Fetch warning history for a guild member."""
        return await self.db.fetchall(
            "SELECT warn_id, guild_id, user_id, moderator_id, reason, created_at FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY warn_id DESC",
            (guild_id, user_id),
        )

    async def clear_warnings(self, guild_id: int, user_id: int) -> int:
        """Clear warning records for a guild member."""
        cursor = await self.db.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        count = getattr(cursor, "rowcount", 0)
        return count if isinstance(count, int) else 0


class CommandUsageRepository:
    """Repository logging command executions."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def log_usage(self, usage: CommandUsage) -> None:
        await self.db.execute(
            "INSERT INTO command_usage (guild_id, user_id, command_name, is_slash, success) VALUES (?, ?, ?, ?, ?)",
            (usage.guild_id, usage.user_id, usage.command_name, 1 if usage.is_slash else 0, 1 if usage.success else 0),
        )

    async def get_top_commands(self, limit: int = 10) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT command_name as _id, COUNT(*) as count FROM command_usage GROUP BY command_name ORDER BY count DESC LIMIT ?",
            (limit,),
        )
        return rows


class SecurityRepository:
    """Repository handling Anti-Nuke and Security settings."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_settings(self, guild_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM security_settings WHERE guild_id = ?", (guild_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO security_settings (guild_id) VALUES (?)", (guild_id,))
            row = await self.db.fetchone("SELECT * FROM security_settings WHERE guild_id = ?", (guild_id,))
        res = dict(row) if row else {}
        for f in ["whitelist_users", "whitelist_roles"]:
            if f in res and isinstance(res[f], str):
                try:
                    res[f] = json.loads(res[f])
                except Exception:
                    res[f] = []
        if "event_punishments" in res and isinstance(res["event_punishments"], str):
            try:
                res["event_punishments"] = json.loads(res["event_punishments"])
            except Exception:
                res["event_punishments"] = {}
        elif "event_punishments" not in res:
            res["event_punishments"] = {}
        return res

    async def get_or_create_settings(self, guild_id: int) -> Dict[str, Any]:
        return await self.get_settings(guild_id)

    async def get_event_punishment(self, guild_id: int, event_name: str) -> str:
        """Return the configured punishment for a security event, defaulting to 'not_configured'."""
        settings = await self.get_settings(guild_id)
        event_punishments = settings.get("event_punishments") or {}
        return event_punishments.get(event_name, "not_configured")

    async def set_event_punishment(self, guild_id: int, event_name: str, punishment: str) -> None:
        """Set the punishment for a specific security event independently."""
        settings = await self.get_settings(guild_id)
        event_punishments = settings.get("event_punishments") or {}
        if punishment.lower() in ["not_configured", "none", "reset"]:
            event_punishments.pop(event_name, None)
        else:
            event_punishments[event_name] = punishment.lower()
        await self.update_settings(guild_id, event_punishments=event_punishments)

    async def update_settings(self, guild_id: int, **kwargs: Any) -> None:
        await self.get_settings(guild_id)
        updates = []
        params = []
        for k, v in kwargs.items():
            updates.append(f"{k} = ?")
            params.append(json.dumps(v) if isinstance(v, (list, dict)) else v)
        params.append(guild_id)
        sql = f"UPDATE security_settings SET {', '.join(updates)} WHERE guild_id = ?"
        await self.db.execute(sql, tuple(params))

    async def get_trusted_users(self, guild_id: int) -> List[Dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM trusted_users WHERE guild_id=?",
            (guild_id,),
        )

    async def add_trusted_user(self, guild_id: int, user_id: int, added_by: int) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO trusted_users (guild_id, user_id, added_by) VALUES (?,?,?)",
            (guild_id, user_id, added_by),
        )

    async def remove_trusted_user(self, guild_id: int, user_id: int) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM trusted_users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        return bool(cursor.rowcount)

    async def is_trusted(self, guild_id: int, user_id: int) -> bool:
        row = await self.db.fetchone(
            "SELECT 1 FROM trusted_users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        return row is not None

    async def get_whitelist_roles(self, guild_id: int) -> List[int]:
        """Return the list of whitelisted role IDs for the guild."""
        settings = await self.get_settings(guild_id)
        return list(settings.get("whitelist_roles") or [])

    async def add_whitelist_role(self, guild_id: int, role_id: int) -> None:
        """Add a role ID to the guild's security whitelist."""
        settings = await self.get_settings(guild_id)
        roles = list(settings.get("whitelist_roles") or [])
        if role_id not in roles:
            roles.append(role_id)
            await self.update_settings(guild_id, whitelist_roles=roles)

    async def remove_whitelist_role(self, guild_id: int, role_id: int) -> bool:
        """Remove a role ID from the guild's security whitelist."""
        settings = await self.get_settings(guild_id)
        roles = list(settings.get("whitelist_roles") or [])
        if role_id in roles:
            roles.remove(role_id)
            await self.update_settings(guild_id, whitelist_roles=roles)
            return True
        return False

    async def log_incident(
        self,
        guild_id: int,
        actor_id: int,
        action_type: str,
        details: str,
        punishment: str = "none",
    ) -> None:
        await self.db.execute(
            "INSERT INTO security_incidents (guild_id, actor_id, action_type, details, punishment) VALUES (?,?,?,?,?)",
            (guild_id, actor_id, action_type, details, punishment),
        )

    async def get_recent_incidents(self, guild_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM security_incidents WHERE guild_id=? ORDER BY timestamp DESC LIMIT ?",
            (guild_id, limit),
        )

    async def log_security_event(
        self,
        guild_id: int,
        actor_id: int,
        action_type: str,
        details: str,
        action_taken: str,
    ) -> None:
        await self.db.execute(
            "INSERT INTO security_logs (guild_id, actor_id, action_type, details, action_taken) VALUES (?, ?, ?, ?, ?)",
            (guild_id, actor_id, action_type, details, action_taken),
        )

    async def get_security_logs(self, guild_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM security_logs WHERE guild_id = ? ORDER BY timestamp DESC LIMIT ?",
            (guild_id, limit),
        )



class EconomyRepository:
    """Repository handling server virtual economy, wallets, bank balances, transactions, and cooldowns."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db
        self._lock = asyncio.Lock()

    async def get_settings(self, guild_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM economy_settings WHERE guild_id = ?", (guild_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO economy_settings (guild_id) VALUES (?)", (guild_id,))
            row = await self.db.fetchone("SELECT * FROM economy_settings WHERE guild_id = ?", (guild_id,))
        return dict(row) if row else {}

    async def update_settings(self, guild_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return
        keys = list(kwargs.keys())
        set_clause = ", ".join(f"{k} = ?" for k in keys)
        values = list(kwargs.values()) + [guild_id]
        await self.get_settings(guild_id)
        await self.db.execute(f"UPDATE economy_settings SET {set_clause} WHERE guild_id = ?", tuple(values))

    async def get_balance(self, guild_id: int, user_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM server_economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO server_economy (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
            row = await self.db.fetchone("SELECT * FROM server_economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        return dict(row) if row else {"wallet": 0, "bank": 0, "daily_streak": 0}

    async def deposit(self, guild_id: int, user_id: int, amount: int) -> Tuple[bool, str, int, int]:
        bal = await self.get_balance(guild_id, user_id)
        wallet = bal["wallet"]
        bank = bal["bank"]

        if amount <= 0:
            return False, "Deposit amount must be greater than zero.", wallet, bank
        if wallet < amount:
            return False, f"Insufficient funds in wallet. You only have `{wallet}` coins.", wallet, bank

        new_wallet = wallet - amount
        new_bank = bank + amount
        await self.db.execute(
            "UPDATE server_economy SET wallet = ?, bank = ? WHERE guild_id = ? AND user_id = ?",
            (new_wallet, new_bank, guild_id, user_id),
        )
        await self.log_transaction(guild_id, user_id, None, "deposit", amount, "bank")
        return True, f"Successfully deposited `{amount}` coins into your bank.", new_wallet, new_bank

    async def withdraw(self, guild_id: int, user_id: int, amount: int) -> Tuple[bool, str, int, int]:
        bal = await self.get_balance(guild_id, user_id)
        wallet = bal["wallet"]
        bank = bal["bank"]

        if amount <= 0:
            return False, "Withdrawal amount must be greater than zero.", wallet, bank
        if bank < amount:
            return False, f"Insufficient funds in bank. You only have `{bank}` coins in your vault.", wallet, bank

        new_wallet = wallet + amount
        new_bank = bank - amount
        await self.db.execute(
            "UPDATE server_economy SET wallet = ?, bank = ? WHERE guild_id = ? AND user_id = ?",
            (new_wallet, new_bank, guild_id, user_id),
        )
        await self.log_transaction(guild_id, user_id, None, "withdraw", amount, "bank")
        return True, f"Successfully withdrew `{amount}` coins from your bank.", new_wallet, new_bank

    async def transfer(self, guild_id: int, sender_id: int, receiver_id: int, amount: int) -> Tuple[bool, str]:
        if not guild_id or not sender_id or not receiver_id:
            return False, "Invalid guild or member identifiers."
        if sender_id == receiver_id:
            return False, "You cannot transfer currency to yourself."
        if amount <= 0:
            return False, "Transfer amount must be greater than zero."

        async with self._lock:
            # Ensure recipient record exists in server_economy
            await self.db.connection.execute(
                "INSERT OR IGNORE INTO server_economy (guild_id, user_id) VALUES (?, ?)",
                (guild_id, receiver_id),
            )

            try:
                # Atomic conditional debit directly at database level
                cursor = await self.db.connection.execute(
                    "UPDATE server_economy SET wallet = wallet - ? WHERE guild_id = ? AND user_id = ? AND wallet >= ?",
                    (amount, guild_id, sender_id, amount),
                )
                if cursor.rowcount == 0:
                    await self.db.connection.rollback()
                    sender_bal = await self.get_balance(guild_id, sender_id)
                    return False, f"Insufficient wallet balance. You need `{amount}` coins, but have `{sender_bal.get('wallet', 0)}`."

                # Credit recipient only after verified successful debit
                await self.db.connection.execute(
                    "UPDATE server_economy SET wallet = wallet + ? WHERE guild_id = ? AND user_id = ?",
                    (amount, guild_id, receiver_id),
                )

                # Record atomic ledger logs within the same transaction
                await self.db.connection.execute(
                    """INSERT INTO economy_transactions (guild_id, user_id, target_id, action, amount, source)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (guild_id, sender_id, receiver_id, "transfer_out", amount, "p2p"),
                )
                await self.db.connection.execute(
                    """INSERT INTO economy_transactions (guild_id, user_id, target_id, action, amount, source)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (guild_id, receiver_id, sender_id, "transfer_in", amount, "p2p"),
                )

                await self.db.connection.commit()
                return True, f"Successfully transferred `{amount}` coins."
            except Exception as e:
                await self.db.connection.rollback()
                return False, f"Failed to complete transfer: {e}"

    async def claim_daily(self, guild_id: int, user_id: int) -> Tuple[bool, str, int, int]:
        import random, datetime
        bal = await self.get_balance(guild_id, user_id)
        settings = await self.get_settings(guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)

        last_str = bal.get("last_daily")
        streak = bal.get("daily_streak") or 0

        if last_str:
            try:
                last_time = datetime.datetime.fromisoformat(last_str.replace("Z", "+00:00"))
                diff = (now - last_time).total_seconds()
                if diff < 86400:
                    remaining = int(86400 - diff)
                    hours = remaining // 3600
                    minutes = (remaining % 3600) // 60
                    return False, f"Daily reward already claimed. Cooldown active: `{hours}h {minutes}m` left.", 0, streak
                elif diff < 172800:
                    streak += 1
                else:
                    streak = 1
            except Exception:
                streak = 1
        else:
            streak = 1

        d_min = settings.get("daily_min") or 100
        d_max = settings.get("daily_max") or 300
        base_reward = random.randint(d_min, d_max)
        streak_bonus = min(streak * 20, 500)
        total_reward = base_reward + streak_bonus

        new_wallet = bal["wallet"] + total_reward
        await self.db.execute(
            "UPDATE server_economy SET wallet = ?, daily_streak = ?, last_daily = ? WHERE guild_id = ? AND user_id = ?",
            (new_wallet, streak, now.isoformat(), guild_id, user_id),
        )
        await self.log_transaction(guild_id, user_id, None, "daily_claim", total_reward, "system")
        return True, f"Claimed **+{total_reward}** coins! (Base: {base_reward}, Streak Bonus: +{streak_bonus})", total_reward, streak

    async def claim_weekly(self, guild_id: int, user_id: int) -> Tuple[bool, str, int]:
        import random, datetime
        bal = await self.get_balance(guild_id, user_id)
        settings = await self.get_settings(guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)

        last_str = bal.get("last_weekly")
        if last_str:
            try:
                last_time = datetime.datetime.fromisoformat(last_str.replace("Z", "+00:00"))
                diff = (now - last_time).total_seconds()
                if diff < 604800:  # 7 days
                    remaining = int(604800 - diff)
                    days = remaining // 86400
                    hours = (remaining % 86400) // 3600
                    return False, f"Weekly reward already claimed. Cooldown active: `{days}d {hours}h` remaining.", 0
            except Exception:
                pass

        w_min = settings.get("weekly_min") or 1000
        w_max = settings.get("weekly_max") or 2500
        reward = random.randint(w_min, w_max)

        new_wallet = bal["wallet"] + reward
        await self.db.execute(
            "UPDATE server_economy SET wallet = ?, last_weekly = ? WHERE guild_id = ? AND user_id = ?",
            (new_wallet, now.isoformat(), guild_id, user_id),
        )
        await self.log_transaction(guild_id, user_id, None, "weekly_claim", reward, "system")
        return True, f"Claimed **+{reward}** coins for your weekly allowance!", reward

    async def work(self, guild_id: int, user_id: int) -> Tuple[bool, str, int, str]:
        import random, datetime
        bal = await self.get_balance(guild_id, user_id)
        settings = await self.get_settings(guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)

        last_str = bal.get("last_work")
        if last_str:
            try:
                last_time = datetime.datetime.fromisoformat(last_str.replace("Z", "+00:00"))
                diff = (now - last_time).total_seconds()
                if diff < 3600:  # 1 hour
                    rem = int(3600 - diff)
                    return False, f"You are exhausted from your last shift! Rest for `{rem // 60}m {rem % 60}s`.", 0, ""
            except Exception:
                pass

        jobs = [
            ("Cybersecurity Analyst", "prevented a major DDoS attack on the mainframe"),
            ("Discord Moderator", "purged 500 spam bots from the server"),
            ("Software Engineer", "shipped a zero-bug backend API feature"),
            ("Crypto Miner", "mined a rare cryptographic block"),
            ("Mechanic", "overhauled a high-performance engine"),
            ("Barista", "served 40 specialty caffeinated beverages"),
            ("Data Scientist", "trained a model that predicted market movements"),
        ]
        job_title, task = random.choice(jobs)
        w_min = settings.get("work_min") or 50
        w_max = settings.get("work_max") or 200
        payout = random.randint(w_min, w_max)

        new_wallet = bal["wallet"] + payout
        await self.db.execute(
            "UPDATE server_economy SET wallet = ?, last_work = ? WHERE guild_id = ? AND user_id = ?",
            (new_wallet, now.isoformat(), guild_id, user_id),
        )
        await self.log_transaction(guild_id, user_id, None, "work_income", payout, "system")
        return True, f"Worked as a **{job_title}** and {task}. Earned **+{payout}** coins!", payout, job_title

    async def crime(self, guild_id: int, user_id: int) -> Tuple[bool, str, int, str]:
        import random, datetime
        bal = await self.get_balance(guild_id, user_id)
        settings = await self.get_settings(guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)

        last_str = bal.get("last_crime")
        if last_str:
            try:
                last_time = datetime.datetime.fromisoformat(last_str.replace("Z", "+00:00"))
                diff = (now - last_time).total_seconds()
                if diff < 7200:  # 2 hours
                    rem = int(7200 - diff)
                    return False, f"The police are actively searching for you! Lay low for `{rem // 60}m {rem % 60}s`.", 0, ""
            except Exception:
                pass

        success = random.random() < 0.60
        c_min = settings.get("crime_min") or 200
        c_max = settings.get("crime_max") or 800

        if success:
            heists = [
                "hacked into a central bank branch server",
                "hijacked an armored convoy carrying luxury tokens",
                "infiltrated an underground counterfeit vault",
                "executed a coordinated digital casino heist",
            ]
            action = random.choice(heists)
            loot = random.randint(c_min, c_max)
            new_wallet = bal["wallet"] + loot
            await self.db.execute(
                "UPDATE server_economy SET wallet = ?, last_crime = ? WHERE guild_id = ? AND user_id = ?",
                (new_wallet, now.isoformat(), guild_id, user_id),
            )
            await self.log_transaction(guild_id, user_id, None, "crime_loot", loot, "heist")
            return True, f"Success! You {action} and walked away with **+{loot}** coins!", loot, "success"
        else:
            busts = [
                "got caught red-handed picking a secure vault",
                "triggered the silent alarm and SWAT surrounded you",
                "left your cyber fingerprint on the mainframe server",
            ]
            action = random.choice(busts)
            fine = random.randint(c_min // 2, c_max // 2)
            actual_fine = min(bal["wallet"], fine)
            new_wallet = max(0, bal["wallet"] - actual_fine)
            await self.db.execute(
                "UPDATE server_economy SET wallet = ?, last_crime = ? WHERE guild_id = ? AND user_id = ?",
                (new_wallet, now.isoformat(), guild_id, user_id),
            )
            await self.log_transaction(guild_id, user_id, None, "crime_fine", -actual_fine, "police")
            return False, f"Busted! You {action} and paid a fine of **-{actual_fine}** coins!", actual_fine, "failed"

    async def rob(self, guild_id: int, robber_id: int, victim_id: int) -> Tuple[bool, str, int]:
        import random, datetime
        if robber_id == victim_id:
            return False, "You cannot rob yourself.", 0

        robber_bal = await self.get_balance(guild_id, robber_id)
        victim_bal = await self.get_balance(guild_id, victim_id)
        now = datetime.datetime.now(datetime.timezone.utc)

        if robber_bal["wallet"] < 100:
            return False, "You need at least `100` wallet coins to risk attempting a robbery.", 0
        if victim_bal["wallet"] < 50:
            return False, "Target has almost no cash on hand to steal. Find a richer target!", 0

        last_str = robber_bal.get("last_rob")
        if last_str:
            try:
                last_time = datetime.datetime.fromisoformat(last_str.replace("Z", "+00:00"))
                diff = (now - last_time).total_seconds()
                if diff < 7200:
                    rem = int(7200 - diff)
                    return False, f"Robbery cooldown active! Wait `{rem // 60}m {rem % 60}s`.", 0
            except Exception:
                pass

        success = random.random() < 0.45
        if success:
            steal_pct = random.uniform(0.2, 0.5)
            stolen = max(1, int(victim_bal["wallet"] * steal_pct))
            new_robber = robber_bal["wallet"] + stolen
            new_victim = victim_bal["wallet"] - stolen

            await self.db.execute("UPDATE server_economy SET wallet = ?, last_rob = ? WHERE guild_id = ? AND user_id = ?", (new_robber, now.isoformat(), guild_id, robber_id))
            await self.db.execute("UPDATE server_economy SET wallet = ? WHERE guild_id = ? AND user_id = ?", (new_victim, guild_id, victim_id))

            await self.log_transaction(guild_id, robber_id, victim_id, "rob_success", stolen, "robbery")
            return True, f"Sneaky strike! You pickpocketed **+{stolen}** coins from <@{victim_id}>!", stolen
        else:
            fine = random.randint(50, min(300, robber_bal["wallet"]))
            new_robber = max(0, robber_bal["wallet"] - fine)
            new_victim = victim_bal["wallet"] + fine

            await self.db.execute("UPDATE server_economy SET wallet = ?, last_rob = ? WHERE guild_id = ? AND user_id = ?", (new_robber, now.isoformat(), guild_id, robber_id))
            await self.db.execute("UPDATE server_economy SET wallet = ? WHERE guild_id = ? AND user_id = ?", (new_victim, guild_id, victim_id))

            await self.log_transaction(guild_id, robber_id, victim_id, "rob_failed", -fine, "robbery")
            return False, f"Caught! You were caught trying to rob <@{victim_id}> and paid them **{fine}** coins in compensation!", fine

    async def add_money(self, guild_id: int, user_id: int, amount: int, where: str = "wallet") -> int:
        bal = await self.get_balance(guild_id, user_id)
        if where == "bank":
            new_val = bal["bank"] + amount
            await self.db.execute("UPDATE server_economy SET bank = ? WHERE guild_id = ? AND user_id = ?", (new_val, guild_id, user_id))
        else:
            new_val = bal["wallet"] + amount
            await self.db.execute("UPDATE server_economy SET wallet = ? WHERE guild_id = ? AND user_id = ?", (new_val, guild_id, user_id))
        await self.log_transaction(guild_id, user_id, None, f"admin_add_{where}", amount, "admin")
        return new_val

    async def remove_money(self, guild_id: int, user_id: int, amount: int, where: str = "wallet") -> int:
        bal = await self.get_balance(guild_id, user_id)
        if where == "bank":
            new_val = max(0, bal["bank"] - amount)
            await self.db.execute("UPDATE server_economy SET bank = ? WHERE guild_id = ? AND user_id = ?", (new_val, guild_id, user_id))
        else:
            new_val = max(0, bal["wallet"] - amount)
            await self.db.execute("UPDATE server_economy SET wallet = ? WHERE guild_id = ? AND user_id = ?", (new_val, guild_id, user_id))
        await self.log_transaction(guild_id, user_id, None, f"admin_remove_{where}", -amount, "admin")
        return new_val

    async def set_money(self, guild_id: int, user_id: int, wallet: int, bank: Optional[int] = None) -> None:
        bal = await self.get_balance(guild_id, user_id)
        new_bank = bank if bank is not None else bal["bank"]
        await self.db.execute("UPDATE server_economy SET wallet = ?, bank = ? WHERE guild_id = ? AND user_id = ?", (wallet, new_bank, guild_id, user_id))
        await self.log_transaction(guild_id, user_id, None, "admin_set", wallet, "admin")

    async def reset_economy(self, guild_id: int, user_id: Optional[int] = None) -> int:
        if user_id:
            cursor = await self.db.execute("DELETE FROM server_economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        else:
            cursor = await self.db.execute("DELETE FROM server_economy WHERE guild_id = ?", (guild_id,))
        return cursor.rowcount

    async def get_leaderboard(self, guild_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT user_id, wallet, bank, (wallet + bank) as net_worth FROM server_economy WHERE guild_id = ? ORDER BY net_worth DESC LIMIT ?",
            (guild_id, limit),
        )
        return [dict(r) for r in rows]

    async def log_transaction(self, guild_id: int, user_id: int, target_id: Optional[int], action: str, amount: int, source: str = "system") -> None:
        await self.db.execute(
            """INSERT INTO economy_transactions (guild_id, user_id, target_id, action, amount, source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (guild_id, user_id, target_id, action, amount, source),
        )

    async def get_transaction_logs(self, guild_id: int, user_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
        if user_id:
            rows = await self.db.fetchall(
                "SELECT * FROM economy_transactions WHERE guild_id = ? AND (user_id = ? OR target_id = ?) ORDER BY timestamp DESC LIMIT ?",
                (guild_id, user_id, user_id, limit),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM economy_transactions WHERE guild_id = ? ORDER BY timestamp DESC LIMIT ?",
                (guild_id, limit),
            )
        return [dict(r) for r in rows]

    async def get_inventory(self, guild_id: int, user_id: int) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall(
            """SELECT ui.item_id, ui.quantity, si.name, si.description, si.price, si.role_id 
               FROM user_inventory ui 
               JOIN shop_items si ON ui.item_id = si.item_id 
               WHERE ui.guild_id = ? AND ui.user_id = ? AND ui.quantity > 0""",
            (guild_id, user_id),
        )
        return [dict(r) for r in rows]

    async def add_to_inventory(self, guild_id: int, user_id: int, item_id: int, quantity: int = 1) -> None:
        await self.db.execute(
            """INSERT INTO user_inventory (guild_id, user_id, item_id, quantity)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id, item_id) DO UPDATE SET quantity = quantity + ?""",
            (guild_id, user_id, item_id, quantity, quantity),
        )

    async def remove_from_inventory(self, guild_id: int, user_id: int, item_id: int, quantity: int = 1) -> bool:
        row = await self.db.fetchone("SELECT quantity FROM user_inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?", (guild_id, user_id, item_id))
        if not row or row["quantity"] < quantity:
            return False
        new_q = row["quantity"] - quantity
        if new_q <= 0:
            await self.db.execute("DELETE FROM user_inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?", (guild_id, user_id, item_id))
        else:
            await self.db.execute("UPDATE user_inventory SET quantity = ? WHERE guild_id = ? AND user_id = ? AND item_id = ?", (new_q, guild_id, user_id, item_id))
        return True

    async def get_economy_stats(self, guild_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone(
            "SELECT COUNT(*) as total_accounts, SUM(wallet) as total_wallet, SUM(bank) as total_bank, MAX(wallet + bank) as highest_net_worth FROM server_economy WHERE guild_id = ?",
            (guild_id,),
        )
        tx_row = await self.db.fetchone("SELECT COUNT(*) as total_tx FROM economy_transactions WHERE guild_id = ?", (guild_id,))
        return {
            "total_accounts": row["total_accounts"] if row else 0,
            "total_wallet": row["total_wallet"] if row and row["total_wallet"] else 0,
            "total_bank": row["total_bank"] if row and row["total_bank"] else 0,
            "highest_net_worth": row["highest_net_worth"] if row and row["highest_net_worth"] else 0,
            "total_transactions": tx_row["total_tx"] if tx_row else 0,
        }


class ShopRepository:
    """Repository handling server shop categories, catalog items, purchases, stock, and refunds."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db
        self._lock = asyncio.Lock()

    async def create_category(self, guild_id: int, name: str, description: str = "") -> int:
        cursor = await self.db.execute(
            "INSERT INTO shop_categories (guild_id, name, description) VALUES (?, ?, ?)",
            (guild_id, name, description),
        )
        return cursor.lastrowid

    async def get_categories(self, guild_id: int) -> List[Dict[str, Any]]:
        rows = await self.db.fetchall("SELECT * FROM shop_categories WHERE guild_id = ? ORDER BY category_id ASC", (guild_id,))
        return [dict(r) for r in rows]

    async def delete_category(self, guild_id: int, category_id: int) -> bool:
        cursor = await self.db.execute("DELETE FROM shop_categories WHERE guild_id = ? AND category_id = ?", (guild_id, category_id))
        return cursor.rowcount > 0

    async def create_item(
        self,
        guild_id: int,
        name: str,
        description: str,
        price: int,
        role_id: Optional[int] = None,
        stock: int = -1,
        category_id: Optional[int] = None,
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO shop_items (guild_id, name, description, price, role_id, stock, category_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, name, description, price, role_id, stock, category_id),
        )
        return cursor.lastrowid

    async def edit_item(self, item_id: int, **kwargs: Any) -> bool:
        if not kwargs:
            return False
        keys = list(kwargs.keys())
        set_clause = ", ".join(f"{k} = ?" for k in keys)
        values = list(kwargs.values()) + [item_id]
        cursor = await self.db.execute(f"UPDATE shop_items SET {set_clause} WHERE item_id = ?", tuple(values))
        return cursor.rowcount > 0

    async def delete_item(self, guild_id: int, item_id: int) -> bool:
        cursor = await self.db.execute("DELETE FROM shop_items WHERE guild_id = ? AND item_id = ?", (guild_id, item_id))
        return cursor.rowcount > 0

    async def get_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        row = await self.db.fetchone("SELECT * FROM shop_items WHERE item_id = ?", (item_id,))
        return dict(row) if row else None

    async def get_items(self, guild_id: int, category_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if category_id:
            rows = await self.db.fetchall("SELECT * FROM shop_items WHERE guild_id = ? AND category_id = ? ORDER BY price ASC", (guild_id, category_id))
        else:
            rows = await self.db.fetchall("SELECT * FROM shop_items WHERE guild_id = ? ORDER BY price ASC", (guild_id,))
        return [dict(r) for r in rows]

    async def buy_item(self, guild_id: int, user_id: int, item_id: int) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        item = await self.get_item(item_id)
        if not item or item["guild_id"] != guild_id:
            return False, "Item not found in this server's shop.", None
        if not item["is_buyable"]:
            return False, f"**{item['name']}** is currently unavailable for purchase.", None
        if item["stock"] == 0:
            return False, f"**{item['name']}** is currently out of stock!", None

        # Check user balance
        bal_row = await self.db.fetchone("SELECT wallet FROM server_economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        wallet = bal_row["wallet"] if bal_row else 0
        if wallet < item["price"]:
            return False, f"Insufficient funds. **{item['name']}** costs `{item['price']}` coins, but your wallet has `{wallet}`.", None

        # Atomic transaction: decrement wallet, decrement stock if limited, add to inventory, record purchase
        new_wallet = wallet - item["price"]
        await self.db.execute("UPDATE server_economy SET wallet = ? WHERE guild_id = ? AND user_id = ?", (new_wallet, guild_id, user_id))

        if item["stock"] > 0:
            await self.db.execute("UPDATE shop_items SET stock = stock - 1 WHERE item_id = ?", (item_id,))

        await self.db.execute(
            """INSERT INTO user_inventory (guild_id, user_id, item_id, quantity)
               VALUES (?, ?, ?, 1)
               ON CONFLICT(guild_id, user_id, item_id) DO UPDATE SET quantity = quantity + 1""",
            (guild_id, user_id, item_id),
        )

        cursor = await self.db.execute(
            "INSERT INTO shop_purchases (guild_id, user_id, item_id, price_paid) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, item_id, item["price"]),
        )
        purchase_id = cursor.lastrowid
        purchase_data = dict(item)
        purchase_data["purchase_id"] = purchase_id
        return True, f"Successfully purchased **{item['name']}** for `{item['price']}` coins!", purchase_data

    async def sell_item(self, guild_id: int, user_id: int, item_id: int, refund_rate: float = 0.5) -> Tuple[bool, str, int]:
        inv_row = await self.db.fetchone("SELECT quantity FROM user_inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?", (guild_id, user_id, item_id))
        if not inv_row or inv_row["quantity"] < 1:
            return False, "You do not own this item in your inventory.", 0

        item = await self.get_item(item_id)
        if not item:
            return False, "Item catalog record not found.", 0

        refund_coins = max(1, int(item["price"] * refund_rate))

        # Decrement inventory
        new_q = inv_row["quantity"] - 1
        if new_q <= 0:
            await self.db.execute("DELETE FROM user_inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?", (guild_id, user_id, item_id))
        else:
            await self.db.execute("UPDATE user_inventory SET quantity = ? WHERE guild_id = ? AND user_id = ? AND item_id = ?", (new_q, guild_id, user_id, item_id))

        # Credit wallet
        await self.db.execute(
            """INSERT INTO server_economy (guild_id, user_id, wallet) VALUES (?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET wallet = wallet + ?""",
            (guild_id, user_id, refund_coins, refund_coins),
        )
        return True, f"Sold **{item['name']}** back to the shop for **+{refund_coins}** coins!", refund_coins

    async def refund_purchase(self, guild_id: int, purchase_id: int) -> Tuple[bool, str]:
        async with self._lock:
            row = await self.db.fetchone("SELECT * FROM shop_purchases WHERE purchase_id = ? AND guild_id = ?", (purchase_id, guild_id))
            if not row:
                return False, "Purchase record not found."
            if row["status"] == "refunded":
                return False, "This purchase has already been refunded."

            user_id = row["user_id"]
            item_id = row["item_id"]
            price = row["price_paid"]

            try:
                # 1. Restore buyer's currency in server_economy
                await self.db.connection.execute(
                    "UPDATE server_economy SET wallet = wallet + ? WHERE guild_id = ? AND user_id = ?",
                    (price, guild_id, user_id),
                )

                # 2. Remove from user_inventory if present
                async with self.db.connection.execute(
                    "SELECT quantity FROM user_inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?",
                    (guild_id, user_id, item_id),
                ) as cursor:
                    inv_row = await cursor.fetchone()

                if inv_row and dict(inv_row).get("quantity", 1) > 1:
                    await self.db.connection.execute(
                        "UPDATE user_inventory SET quantity = quantity - 1 WHERE guild_id = ? AND user_id = ? AND item_id = ?",
                        (guild_id, user_id, item_id),
                    )
                elif inv_row:
                    await self.db.connection.execute(
                        "DELETE FROM user_inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?",
                        (guild_id, user_id, item_id),
                    )

                # 3. Restore one unit of stock for limited-stock items (stock >= 0, preserves -1 for unlimited)
                await self.db.connection.execute(
                    "UPDATE shop_items SET stock = stock + 1 WHERE item_id = ? AND stock >= 0",
                    (item_id,),
                )

                # 4. Update status to refunded
                await self.db.connection.execute(
                    "UPDATE shop_purchases SET status = 'refunded' WHERE purchase_id = ?",
                    (purchase_id,),
                )

                # 5. Record refund transaction in economy_transactions
                await self.db.connection.execute(
                    """INSERT INTO economy_transactions (guild_id, user_id, target_id, action, amount, source)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (guild_id, user_id, None, "refund", price, f"purchase_{purchase_id}"),
                )

                await self.db.connection.commit()
                return True, f"Successfully refunded purchase #{purchase_id} and restored `{price}` coins to <@{user_id}>."
            except Exception as e:
                await self.db.connection.rollback()
                return False, f"Failed to process refund: {e}"

    async def get_purchases(self, guild_id: int, user_id: Optional[int] = None, limit: int = 20) -> List[Dict[str, Any]]:
        if user_id:
            rows = await self.db.fetchall(
                """SELECT sp.*, si.name as item_name FROM shop_purchases sp
                   JOIN shop_items si ON sp.item_id = si.item_id
                   WHERE sp.guild_id = ? AND sp.user_id = ? ORDER BY sp.purchased_at DESC LIMIT ?""",
                (guild_id, user_id, limit),
            )
        else:
            rows = await self.db.fetchall(
                """SELECT sp.*, si.name as item_name FROM shop_purchases sp
                   JOIN shop_items si ON sp.item_id = si.item_id
                   WHERE sp.guild_id = ? ORDER BY sp.purchased_at DESC LIMIT ?""",
                (guild_id, limit),
            )
        return [dict(r) for r in rows]

    async def get_shop_stats(self, guild_id: int) -> Dict[str, Any]:
        item_c = await self.db.fetchone("SELECT COUNT(*) as count FROM shop_items WHERE guild_id = ?", (guild_id,))
        order_c = await self.db.fetchone("SELECT COUNT(*) as count, SUM(price_paid) as revenue FROM shop_purchases WHERE guild_id = ? AND status = 'completed'", (guild_id,))
        return {
            "total_items": item_c["count"] if item_c else 0,
            "total_purchases": order_c["count"] if order_c else 0,
            "total_revenue": order_c["revenue"] if order_c and order_c["revenue"] else 0,
        }


class MinigameRepository:
    """Repository handling interactive minigame configuration, statistics, leaderboards, and daily challenges."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def get_settings(self, guild_id: int) -> Dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM minigame_settings WHERE guild_id = ?", (guild_id,))
        if not row:
            await self.db.execute("INSERT OR IGNORE INTO minigame_settings (guild_id) VALUES (?)", (guild_id,))
            row = await self.db.fetchone("SELECT * FROM minigame_settings WHERE guild_id = ?", (guild_id,))
        return dict(row) if row else {}

    async def update_settings(self, guild_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return
        keys = list(kwargs.keys())
        set_clause = ", ".join(f"{k} = ?" for k in keys)
        values = list(kwargs.values()) + [guild_id]
        await self.get_settings(guild_id)
        await self.db.execute(f"UPDATE minigame_settings SET {set_clause} WHERE guild_id = ?", tuple(values))

    async def record_game(
        self,
        guild_id: int,
        user_id: int,
        game_type: str,
        won: bool,
        drawn: bool = False,
        coins_delta: int = 0,
        score: int = 0,
    ) -> None:
        win_inc = 1 if won else 0
        loss_inc = 1 if (not won and not drawn) else 0
        draw_inc = 1 if drawn else 0
        coins_won = max(0, coins_delta)
        coins_lost = abs(min(0, coins_delta))

        await self.db.execute(
            """INSERT INTO minigame_stats (guild_id, user_id, game_type, wins, losses, draws, coins_won, coins_lost, high_score, last_played)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(guild_id, user_id, game_type) DO UPDATE SET
                   wins = wins + ?,
                   losses = losses + ?,
                   draws = draws + ?,
                   coins_won = coins_won + ?,
                   coins_lost = coins_lost + ?,
                   high_score = MAX(high_score, ?),
                   last_played = CURRENT_TIMESTAMP""",
            (guild_id, user_id, game_type, win_inc, loss_inc, draw_inc, coins_won, coins_lost, score, win_inc, loss_inc, draw_inc, coins_won, coins_lost, score),
        )

    async def get_stats(self, guild_id: int, user_id: int, game_type: Optional[str] = None) -> Dict[str, Any]:
        if game_type:
            row = await self.db.fetchone(
                "SELECT * FROM minigame_stats WHERE guild_id = ? AND user_id = ? AND game_type = ?",
                (guild_id, user_id, game_type),
            )
            return dict(row) if row else {"wins": 0, "losses": 0, "draws": 0, "coins_won": 0, "coins_lost": 0, "high_score": 0}
        else:
            row = await self.db.fetchone(
                """SELECT SUM(wins) as total_wins, SUM(losses) as total_losses, SUM(draws) as total_draws,
                          SUM(coins_won) as total_coins_won, SUM(coins_lost) as total_coins_lost,
                          MAX(high_score) as peak_score
                   FROM minigame_stats WHERE guild_id = ? AND user_id = ?""",
                (guild_id, user_id),
            )
            return dict(row) if row and row["total_wins"] is not None else {"total_wins": 0, "total_losses": 0, "total_draws": 0, "total_coins_won": 0, "total_coins_lost": 0, "peak_score": 0}

    async def get_leaderboard(self, guild_id: int, game_type: Optional[str] = None, metric: str = "wins", limit: int = 10) -> List[Dict[str, Any]]:
        order_col = "wins" if metric == "wins" else "coins_won"
        if game_type:
            rows = await self.db.fetchall(
                f"SELECT user_id, wins, losses, draws, coins_won, high_score FROM minigame_stats WHERE guild_id = ? AND game_type = ? ORDER BY {order_col} DESC LIMIT ?",
                (guild_id, game_type, limit),
            )
        else:
            rows = await self.db.fetchall(
                f"""SELECT user_id, SUM(wins) as wins, SUM(losses) as losses, SUM(draws) as draws, SUM(coins_won) as coins_won
                   FROM minigame_stats WHERE guild_id = ? GROUP BY user_id ORDER BY {order_col} DESC LIMIT ?""",
                (guild_id, limit),
            )
        return [dict(r) for r in rows]

    async def get_daily_challenge(self, guild_id: int, date_str: str) -> Optional[Dict[str, Any]]:
        row = await self.db.fetchone("SELECT * FROM minigame_daily_challenges WHERE guild_id = ? AND day_date = ?", (guild_id, date_str))
        return dict(row) if row else None

    async def create_daily_challenge(self, guild_id: int, date_str: str, challenge_type: str, target: int = 3, reward: int = 500) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO minigame_daily_challenges (guild_id, day_date, challenge_type, target_count, reward_coins)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, date_str, challenge_type, target, reward),
        )


class MentionSettingsRepository:
    """Repository managing user opt-in / opt-out preferences for real-time mention DMs."""

    def __init__(self, db: SQLiteDatabaseManager) -> None:
        self.db = db

    async def is_enabled(self, user_id: int) -> bool:
        """Return True if mention notifications are enabled for the user (default: True)."""
        row = await self.db.fetchone("SELECT enabled FROM user_mention_settings WHERE user_id = ?", (user_id,))
        if not row:
            return True
        return bool(row["enabled"])

    async def set_enabled(self, user_id: int, enabled: bool) -> None:
        """Set mention notifications enabled/disabled state for a user."""
        await self.db.execute(
            """INSERT INTO user_mention_settings (user_id, enabled, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET enabled = ?, updated_at = CURRENT_TIMESTAMP""",
            (user_id, 1 if enabled else 0, 1 if enabled else 0),
        )

    async def toggle(self, user_id: int) -> bool:
        """Toggle the user's notification preference and return the new state."""
        current = await self.is_enabled(user_id)
        new_state = not current
        await self.set_enabled(user_id, new_state)
        return new_state

