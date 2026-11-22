"""Audio source abstractions, metadata models, and FFmpeg PCM audio streaming."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

import discord

from bot.utils.logger import get_logger

logger = get_logger("death_bot.music.source")


class LoopMode(str, Enum):
    """Looping states for audio playback."""
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


class PlayerState(str, Enum):
    """Lifecycle states of the guild music player."""
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class AudioFilter(str, Enum):
    """Supported real-time FFmpeg audio DSP filters."""
    OFF = "off"
    BASSBOOST = "bassboost"
    NIGHTCORE = "nightcore"
    VAPORWAVE = "vaporwave"
    EIGHT_D = "8d"


FILTER_MAP: Dict[AudioFilter, str] = {
    AudioFilter.BASSBOOST: "bass=g=10,dynaudnorm=f=200",
    AudioFilter.NIGHTCORE: "asetrate=48000*1.25,aresample=48000,atempo=1.06",
    AudioFilter.VAPORWAVE: "asetrate=48000*0.8,aresample=48000,atempo=1.0",
    AudioFilter.EIGHT_D: "apulsator=hz=0.125",
}


@dataclass
class AudioSourceInfo:
    """Metadata representing an extracted audio stream or video."""
    title: str
    url: str
    webpage_url: str
    duration_seconds: int
    uploader: str
    thumbnail_url: Optional[str] = None
    is_live: bool = False
    views: Optional[int] = None
    confidence_score: float = 1.0
    source_provider: str = "youtube"
    original_source: Optional[str] = None
    album_name: Optional[str] = None

    @property
    def formatted_duration(self) -> str:
        """Return human-readable duration format MM:SS or HH:MM:SS."""
        if self.is_live:
            return "LIVE"
        mins, secs = divmod(max(0, self.duration_seconds), 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def progress_bar(self, elapsed: float, length: int = 16) -> str:
        """Render a neon progress bar e.g. 🔘────────────── [01:23 / 03:45]."""
        if self.is_live or self.duration_seconds <= 0:
            return "🔴 LIVE STREAM"

        ratio = min(1.0, max(0.0, elapsed / self.duration_seconds))
        fill_index = int(ratio * length)

        bar = ""
        for i in range(length):
            if i == fill_index:
                bar += "🟣"  # Neon purple cursor
            elif i < fill_index:
                bar += "━"
            else:
                bar += "─"

        elapsed_mins, elapsed_secs = divmod(int(elapsed), 60)
        elapsed_hours, elapsed_mins = divmod(elapsed_mins, 60)
        if elapsed_hours > 0:
            elapsed_str = f"{elapsed_hours:02d}:{elapsed_mins:02d}:{elapsed_secs:02d}"
        else:
            elapsed_str = f"{elapsed_mins:02d}:{elapsed_secs:02d}"

        return f"`{elapsed_str}` {bar} `{self.formatted_duration}`"


@dataclass
class Track:
    """Represents an active track queued for playback."""
    source_info: AudioSourceInfo
    requester_id: int
    requester_name: str
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    active_filter: AudioFilter = AudioFilter.OFF
    start_offset: float = 0.0

    @property
    def title(self) -> str:
        return self.source_info.title

    @property
    def uri(self) -> str:
        return self.source_info.webpage_url

    @property
    def duration(self) -> int:
        return self.source_info.duration_seconds

    @property
    def uploader(self) -> str:
        return self.source_info.uploader

    @property
    def thumbnail(self) -> Optional[str]:
        return self.source_info.thumbnail_url


class DeathAudioSource(discord.PCMVolumeTransformer):
    """FFmpeg PCM audio source with volume control and live playback tracking."""

    def __init__(
        self,
        source: discord.FFmpegPCMAudio,
        volume: float = 1.0,
        start_offset: float = 0.0,
    ) -> None:
        super().__init__(source, volume=volume)
        self.start_offset = start_offset
        self.frames_read: int = 0

    @property
    def _current_error(self) -> Optional[Exception]:
        """Expose inner FFmpeg process error so Discord.py AudioPlayer can report failures."""
        return getattr(self.original, "_current_error", None)

    @property
    def elapsed_seconds(self) -> float:
        """Calculate elapsed playback time based on 20ms PCM audio frames."""
        return self.start_offset + (self.frames_read * 0.02)

    def read(self) -> bytes:
        data = super().read()
        if data:
            self.frames_read += 1
        return data

    @classmethod
    def create_stream(
        cls,
        stream_url: str,
        volume: float = 1.0,
        audio_filter: AudioFilter = AudioFilter.OFF,
        start_offset: float = 0.0,
    ) -> DeathAudioSource:
        """Instantiate an FFmpeg audio source with reconnection parameters and DSP filters."""
        # Find ffmpeg executable
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"

        # Standard browser User-Agent so streaming CDNs (SoundCloud, YouTube, Audius) do not block FFmpeg
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        before_opts = [
            "-user_agent", ua,
            "-reconnect", "1",
            "-reconnect_delay_max", "5",
        ]
        # Only add reconnect_streamed if not an HLS playlist (m3u8), where it can cause socket errors
        if ".m3u8" not in stream_url.lower():
            before_opts.extend(["-reconnect_streamed", "1"])

        if start_offset > 0:
            before_opts.extend(["-ss", f"{start_offset:.2f}"])

        options = ["-vn"]
        if audio_filter in FILTER_MAP:
            options.extend(["-af", FILTER_MAP[audio_filter]])

        ffmpeg_source = discord.FFmpegPCMAudio(
            stream_url,
            executable=ffmpeg_bin,
            before_options=" ".join(before_opts),
            options=" ".join(options),
        )
        return cls(ffmpeg_source, volume=volume, start_offset=start_offset)

