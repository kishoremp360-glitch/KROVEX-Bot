"""Music service architecture and domain models for Death Bot.

Provides types, state management, queue definitions, source representations,
and orchestrates per-guild audio players, non-blocking resolvers, and lyrics.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from bot.services.music.lyrics import LyricsService
from bot.services.music.player import GuildAudioPlayer
from bot.services.music.resolver import AudioResolver
from bot.services.music.source import AudioFilter, AudioSourceInfo, LoopMode, PlayerState, Track
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.music_service")

# Re-export for backward compatibility with existing tests and imports
__all__ = [
    "AudioFilter",
    "AudioSourceInfo",
    "GuildAudioPlayer",
    "LoopMode",
    "LyricsService",
    "MusicService",
    "PlayerState",
    "Track",
]


class MusicService:
    """Core domain service orchestrating guild players, queue management, and audio extraction."""

    def __init__(self, bot: Optional[DeathBot] = None) -> None:
        self.bot = bot
        cfg = getattr(bot, "config", None)
        self.resolver = AudioResolver(
            client_id=getattr(cfg, "spotify_client_id", None) if cfg else None,
            client_secret=getattr(cfg, "spotify_client_secret", None) if cfg else None,
            cookie_path=getattr(cfg, "youtube_cookie_path", None) if cfg else None,
            cookies_content=getattr(cfg, "youtube_cookies_content", None) if cfg else None,
            po_token=getattr(cfg, "youtube_po_token", None) if cfg else None,
            visitor_data=getattr(cfg, "youtube_visitor_data", None) if cfg else None,
        )
        self.lyrics_service = LyricsService(session=bot.session if bot else None)

        # Guild players registry keyed by guild_id
        self._players: Dict[int, GuildAudioPlayer] = {}

        # Backward compatibility state storage for unit tests or standalone service testing
        self._queues: Dict[int, List[Track]] = {}
        self._current_track: Dict[int, Optional[Track]] = {}
        self._loop_modes: Dict[int, LoopMode] = {}
        self._volumes: Dict[int, int] = {}
        self._states: Dict[int, PlayerState] = {}

    def get_player(self, guild_id: int) -> GuildAudioPlayer:
        """Get or instantiate a per-guild audio player."""
        if guild_id not in self._players:
            self._players[guild_id] = GuildAudioPlayer(
                bot=self.bot,
                guild_id=guild_id,
                resolver=self.resolver,
            )
        return self._players[guild_id]

    def has_player(self, guild_id: int) -> bool:
        """Check if an active player exists for the specified guild."""
        return guild_id in self._players

    def get_queue(self, guild_id: int) -> List[Track]:
        """Get the current queue for a guild (player-backed if available)."""
        if guild_id in self._players:
            return self._players[guild_id].queue
        return self._queues.setdefault(guild_id, [])

    def get_current_track(self, guild_id: int) -> Optional[Track]:
        """Get the track currently playing in the guild."""
        if guild_id in self._players:
            return self._players[guild_id].current_track
        return self._current_track.get(guild_id)

    def set_current_track(self, guild_id: int, track: Optional[Track]) -> None:
        """Set the active track for a guild."""
        if guild_id in self._players:
            self._players[guild_id].current_track = track
        self._current_track[guild_id] = track

    def cleanup_guild(self, guild_id: int) -> None:
        """Purge all in-memory audio state when leaving a voice channel."""
        if guild_id in self._players:
            player = self._players.pop(guild_id)
            player.stop()

        self._queues.pop(guild_id, None)
        self._current_track.pop(guild_id, None)
        self._loop_modes.pop(guild_id, None)
        self._volumes.pop(guild_id, None)
        self._states.pop(guild_id, None)

    @staticmethod
    def is_voice_supported() -> bool:
        """Check if native PyNaCl encryption library is loaded."""
        try:
            import discord.voice_client
            return bool(discord.voice_client.has_nacl)
        except Exception:
            return False

    @staticmethod
    def is_ffmpeg_available() -> bool:
        """Check if FFmpeg executable exists on system PATH."""
        import shutil
        return shutil.which("ffmpeg") is not None

    @staticmethod
    def is_ytdlp_available() -> bool:
        """Check if yt-dlp audio extractor is installed and importable."""
        try:
            import yt_dlp
            return True
        except ImportError:
            return False

    def add_to_queue(self, guild_id: int, track: Track, max_size: int = 500) -> bool:
        """Add a track to the guild's playback queue."""
        if guild_id in self._players:
            return self._players[guild_id].enqueue(track, max_size=max_size)

        q = self.get_queue(guild_id)
        if len(q) >= max_size:
            return False
        q.append(track)
        return True

    def remove_from_queue(self, guild_id: int, index: int) -> Optional[Track]:
        """Remove a track at a specific index (1-based index from user command)."""
        if guild_id in self._players:
            return self._players[guild_id].remove_track(index)

        q = self.get_queue(guild_id)
        idx = index - 1
        if 0 <= idx < len(q):
            return q.pop(idx)
        return None

    def clear_queue(self, guild_id: int) -> int:
        """Clear all queued tracks for a guild and return number of tracks cleared."""
        if guild_id in self._players:
            return self._players[guild_id].clear_queue()

        q = self.get_queue(guild_id)
        count = len(q)
        q.clear()
        return count

    def set_loop_mode(self, guild_id: int, mode: LoopMode) -> LoopMode:
        """Update looping behavior."""
        if guild_id in self._players:
            self._players[guild_id].loop_mode = mode
        self._loop_modes[guild_id] = mode
        return mode

    def get_loop_mode(self, guild_id: int) -> LoopMode:
        """Get current looping behavior."""
        if guild_id in self._players:
            return self._players[guild_id].loop_mode
        return self._loop_modes.get(guild_id, LoopMode.OFF)

    def set_volume(self, guild_id: int, volume: int) -> int:
        """Set volume level clamped between 1 and 100."""
        clamped = max(1, min(100, volume))
        if guild_id in self._players:
            self._players[guild_id].set_volume(clamped)
        self._volumes[guild_id] = clamped
        return clamped

    def get_volume(self, guild_id: int) -> int:
        """Get current volume level."""
        if guild_id in self._players:
            return self._players[guild_id].volume
        return self._volumes.get(guild_id, 100)

    def set_state(self, guild_id: int, state: PlayerState) -> None:
        """Set player state."""
        if guild_id in self._players:
            self._players[guild_id].state = state
        self._states[guild_id] = state

    def get_state(self, guild_id: int) -> PlayerState:
        """Get current player state."""
        if guild_id in self._players:
            return self._players[guild_id].state
        return self._states.get(guild_id, PlayerState.IDLE)
