"""Per-guild music playback engine, voice channel controller, and queue orchestrator."""

from __future__ import annotations

import asyncio
import math
import random
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

import discord

from bot.services.music.resolver import AudioResolver
from bot.services.music.source import (
    AudioFilter,
    AudioSourceInfo,
    DeathAudioSource,
    LoopMode,
    PlayerState,
    Track,
)
from bot.services.music.views import MusicPlayerView
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.music.player")


class GuildAudioPlayer:
    """Isolated stateful audio playback engine for an individual Discord guild."""

    def __init__(
        self,
        bot: DeathBot,
        guild_id: int,
        resolver: Optional[AudioResolver] = None,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.resolver = resolver or AudioResolver()

        # Playback queue and history
        self.queue: List[Track] = []
        self.history: List[Track] = []
        self.current_track: Optional[Track] = None
        self.current_source: Optional[DeathAudioSource] = None

        # Playback configuration and states
        self.state: PlayerState = PlayerState.IDLE
        self.loop_mode: LoopMode = LoopMode.OFF
        self.volume: int = 100
        self.active_filter: AudioFilter = AudioFilter.OFF
        self.autoplay: bool = False
        self.twenty_four_seven: bool = False

        # DJ and Voting
        self.dj_role_id: Optional[int] = None
        self.dj_only: bool = False
        self.vote_skip_ratio: float = 0.5
        self.skip_votes: Set[int] = set()

        # Channel & Interactive UI references
        self.text_channel: Optional[discord.TextChannel] = None
        self.player_message: Optional[discord.Message] = None
        self.player_view: Optional[MusicPlayerView] = None

        # Concurrency safety & background tasks
        self.lock = asyncio.Lock()
        self._play_lock = asyncio.Lock()
        self._is_advancing: bool = False
        self._inactivity_task: Optional[asyncio.Task] = None
        self._progress_update_task: Optional[asyncio.Task] = None

    @property
    def guild(self) -> Optional[discord.Guild]:
        return self.bot.get_guild(self.guild_id)

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        g = self.guild
        return g.voice_client if g else None

    @property
    def is_connected(self) -> bool:
        vc = self.voice_client
        return vc is not None and vc.is_connected()

    def sync_state(self) -> PlayerState:
        """Reconcile internal player state with actual Discord VoiceClient and current_track."""
        vc = self.voice_client
        if not vc or not vc.is_connected():
            if self.state in (PlayerState.PLAYING, PlayerState.PAUSED):
                logger.info(
                    "VoiceClient not connected in guild %s; syncing state from %s to IDLE",
                    self.guild_id,
                    self.state,
                )
                self.state = PlayerState.IDLE
                self.current_track = None
                self.current_source = None
            return self.state

        if self.current_track is None:
            if self.state in (PlayerState.PLAYING, PlayerState.PAUSED):
                logger.info(
                    "No current track in guild %s; syncing state from %s to IDLE",
                    self.guild_id,
                    self.state,
                )
                self.state = PlayerState.IDLE
                self.current_source = None
            return self.state

        # We have a current track and connected voice client
        if vc.is_playing():
            self.state = PlayerState.PLAYING
        elif vc.is_paused():
            self.state = PlayerState.PAUSED
        elif self.state == PlayerState.PLAYING:
            logger.info(
                "VoiceClient is idle but state was PLAYING in guild %s; syncing to IDLE",
                self.guild_id,
            )
            self.state = PlayerState.IDLE
            self.current_track = None
            self.current_source = None

        return self.state

    @property
    def is_playing(self) -> bool:
        """True only if the player is actively streaming audio to a connected voice channel."""
        self.sync_state()
        vc = self.voice_client
        return (
            self.state == PlayerState.PLAYING
            and self.current_track is not None
            and vc is not None
            and vc.is_connected()
            and vc.is_playing()
        )

    @property
    def is_paused(self) -> bool:
        """True if playback is currently paused on a connected voice channel."""
        self.sync_state()
        vc = self.voice_client
        return (
            self.state == PlayerState.PAUSED
            and self.current_track is not None
            and vc is not None
            and vc.is_connected()
            and vc.is_paused()
        )

    @property
    def elapsed_seconds(self) -> float:
        if self.current_source:
            return self.current_source.elapsed_seconds
        return 0.0

    async def connect(self, channel: discord.VoiceChannel, timeout: float = 15.0) -> discord.VoiceClient:
        """Connect or move to the specified voice channel."""
        vc = self.voice_client
        if vc and vc.is_connected():
            if vc.channel.id != channel.id:
                await vc.move_to(channel)
            return vc
        else:
            if vc:
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass
            new_vc = await channel.connect(timeout=timeout, reconnect=True)
            return new_vc

    async def disconnect(self) -> None:
        """Disconnect voice client, cancel timers, and purge in-memory playback."""
        self._cancel_inactivity_task()
        self._cancel_progress_task()

        vc = self.voice_client
        if vc and vc.is_connected():
            try:
                await vc.disconnect(force=True)
            except Exception as err:
                logger.warning("Error disconnecting voice client in %s: %s", self.guild_id, err)

        await self.stop(clear_queue=True)

    def _cancel_inactivity_task(self) -> None:
        if self._inactivity_task and not self._inactivity_task.done():
            self._inactivity_task.cancel()
            self._inactivity_task = None

    def _cancel_progress_task(self) -> None:
        if self._progress_update_task and not self._progress_update_task.done():
            self._progress_update_task.cancel()
            self._progress_update_task = None

    def _schedule_inactivity_timeout(self, delay: float = 300.0) -> None:
        """Schedule automatic voice disconnection after 5 minutes of inactivity if 24/7 is disabled."""
        self._cancel_inactivity_task()
        if self.twenty_four_seven:
            return

        async def _inactivity_countdown():
            try:
                await asyncio.sleep(delay)
                if not self.twenty_four_seven and (self.state == PlayerState.IDLE or not self.queue):
                    logger.info("Inactivity timeout triggered for guild %s. Disconnecting.", self.guild_id)
                    if self.text_channel:
                        embed = EmbedBuilder.info(
                            title="Disconnected Due to Inactivity",
                            description="Left voice channel after 5 minutes of idle time. Enable **24/7 Mode** to keep me connected.",
                        )
                        await self.text_channel.send(embed=embed)
                    await self.disconnect()
            except asyncio.CancelledError:
                pass

        self._inactivity_task = asyncio.create_task(_inactivity_countdown())

    # --------------------------------------------------------------------------
    # Playback Control
    # --------------------------------------------------------------------------

    async def enqueue(self, track: Track, play_now: bool = True) -> Tuple[int, bool]:
        """Enqueue a track and begin playback if the player is currently idle.

        Returns:
            Tuple[int, bool]: (queue_position, started_playing_now)
            - If playback started immediately: returns (0, True) and track is current_track.
            - If track was placed in queue: returns (pos >= 1, False).
        """
        self._cancel_inactivity_task()
        self.sync_state()

        is_active = (self.current_track is not None and self.state in (PlayerState.PLAYING, PlayerState.PAUSED))

        if not is_active and play_now:
            async with self.lock:
                self.queue.insert(0, track)
            await self.play_next()
            if self.current_track == track and self.state == PlayerState.PLAYING:
                return 0, True
            return 0, False

            async with self.lock:
                pos = self.queue.index(track) + 1 if track in self.queue else len(self.queue)
            return max(1, pos), False
        else:
            async with self.lock:
                self.queue.append(track)
                pos = len(self.queue)
            return pos, False

    async def add_track(self, track: Track, play_now: bool = True) -> int:
        """Add a track to the queue and begin playback if idle (backward-compatible)."""
        pos, started = await self.enqueue(track, play_now=play_now)
        return pos if not started else 1

    async def play_next(self, force: bool = False) -> None:
        """Advance queue, create FFmpeg audio stream, and begin playback with concurrency protection."""
        if self._is_advancing or self._play_lock.locked():
            logger.debug("play_next already in progress for guild %s; skipping duplicate call.", self.guild_id)
            return

        async with self._play_lock:
            self._is_advancing = True
            try:
                # If already playing and not forced (e.g. by skip), do not advance
                vc = self.voice_client
                if not force and vc and vc.is_connected() and vc.is_playing():
                    logger.debug("Playback is already actively underway in %s; skipping play_next.", self.guild_id)
                    return
                await self._execute_play_next()
            finally:
                self._is_advancing = False

    async def _execute_play_next(self) -> None:
        vc = self.voice_client
        if not vc or not vc.is_connected():
            # Bounded check if voice client is currently reconnecting
            if vc and getattr(vc, "_connecting", False):
                logger.info("VoiceClient in guild %s is reconnecting; waiting briefly...", self.guild_id)
                for _ in range(10):
                    await asyncio.sleep(0.2)
                    if vc.is_connected():
                        break

            if not vc or not vc.is_connected():
                logger.warning(
                    "Cannot start playback in guild %s: VoiceClient is not connected.",
                    self.guild_id,
                )
                self.state = PlayerState.IDLE
                self._schedule_inactivity_timeout()
                return

        next_track: Optional[Track] = None

        async with self.lock:
            # 1. Loop track
            if self.loop_mode == LoopMode.TRACK and self.current_track:
                next_track = self.current_track
            # 2. Pop from queue
            elif self.queue:
                if self.current_track:
                    self.history.append(self.current_track)
                    if len(self.history) > 50:
                        self.history.pop(0)

                if self.loop_mode == LoopMode.QUEUE and self.current_track:
                    self.queue.append(self.current_track)

                next_track = self.queue.pop(0)
            # 3. Autoplay if queue is exhausted
            elif self.autoplay and self.current_track:
                logger.info("Autoplay active in guild %s. Resolving recommended track...", self.guild_id)
                next_track = await self._resolve_autoplay_track()
                if self.current_track:
                    self.history.append(self.current_track)
            else:
                # Queue is fully finished
                if self.current_track:
                    self.history.append(self.current_track)
                self.current_track = None
                self.current_source = None
                self.state = PlayerState.IDLE
                self._schedule_inactivity_timeout()
                await self.update_player_message()
                return

        if not next_track:
            self.current_track = None
            self.current_source = None
            self.state = PlayerState.IDLE
            self._schedule_inactivity_timeout()
            return

        self.current_track = next_track
        self.skip_votes.clear()

        # Create FFmpeg audio source
        try:
            source = DeathAudioSource.create_stream(
                stream_url=next_track.source_info.url,
                volume=self.volume / 100.0,
                audio_filter=self.active_filter,
                start_offset=next_track.start_offset,
            )
            self.current_source = source
        except Exception as err:
            logger.error("Failed to construct FFmpeg audio stream for '%s': %s", next_track.title, err)
            if self.text_channel:
                embed = EmbedBuilder.error(
                    title="Playback Stream Error",
                    description=f"Could not initialize audio stream for **{next_track.title}**:\n`{err}`",
                )
                await self.text_channel.send(embed=embed)
            # Record failed track into history so it is not silently lost
            self.history.append(next_track)
            self.current_track = None
            self.current_source = None
            # Schedule next track safely
            asyncio.create_task(self.play_next())
            return

        # Start playback via Discord VoiceClient
        self.state = PlayerState.PLAYING

        def _after(error: Optional[Exception]) -> None:
            if error:
                logger.error("Voice client playback exception in guild %s: %s", self.guild_id, error)
            elif source.frames_read == 0:
                logger.warning("Stream ended immediately with 0 audio frames for '%s'", next_track.title)
            fut = asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)
            try:
                fut.result(timeout=1.0)
            except Exception:
                pass

        try:
            if vc.is_playing() or vc.is_paused():
                vc.stop()
            # Explicitly speak to initiate Discord voice router speaking state
            try:
                if hasattr(vc, "ws") and vc.ws:
                    asyncio.create_task(vc.ws.speak(discord.SpeakingState.voice))
            except Exception:
                pass
            vc.play(source, after=_after)
            await self.update_player_message()
        except Exception as err:
            logger.error("VoiceClient.play failed in guild %s: %s", self.guild_id, err)
            self.state = PlayerState.IDLE
            self.current_track = None
            self.current_source = None
            if self.text_channel:
                embed = EmbedBuilder.error(
                    title="Playback Error",
                    description=f"Failed to play **{next_track.title}** on voice client:\n`{err}`",
                )
                await self.text_channel.send(embed=embed)

    async def _resolve_autoplay_track(self) -> Optional[Track]:
        """Fetch an automatic song recommendation based on the current track."""
        if not self.current_track:
            return None
        query = f"{self.current_track.title} {self.current_track.uploader}"
        try:
            _, candidates = await self.resolver.resolve(query, timeout=10.0)
            # Find candidate not recently played
            played_uris = {t.uri for t in self.history[-10:]}
            if self.current_track:
                played_uris.add(self.current_track.uri)

            for c in candidates:
                if c.webpage_url not in played_uris:
                    return Track(
                        source_info=c,
                        requester_id=self.bot.user.id if self.bot.user else 0,
                        requester_name="Autoplay Engine",
                    )
        except Exception as err:
            logger.warning("Autoplay recommendation failed for '%s': %s", query, err)
        return None

    async def pause(self) -> bool:
        """Pause current playback."""
        vc = self.voice_client
        if vc and vc.is_playing():
            vc.pause()
            self.state = PlayerState.PAUSED
            return True
        return False

    async def resume(self) -> bool:
        """Resume paused playback."""
        vc = self.voice_client
        if vc and vc.is_paused():
            vc.resume()
            self.state = PlayerState.PLAYING
            return True
        return False

    async def skip(self) -> Optional[Track]:
        """Skip current track."""
        vc = self.voice_client
        skipped = self.current_track
        # If in track loop mode, temporarily advance past track
        if self.loop_mode == LoopMode.TRACK:
            self.loop_mode = LoopMode.OFF

        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()  # Triggers _after which invokes play_next()
        else:
            await self.play_next(force=True)
        return skipped

    async def play_previous(self) -> bool:
        """Return to the previously played track."""
        if not self.history:
            return False

        async with self.lock:
            prev_track = self.history.pop()
            if self.current_track:
                self.queue.insert(0, self.current_track)
            self.queue.insert(0, prev_track)

        vc = self.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        else:
            await self.play_next(force=True)
        return True

    async def stop(self, clear_queue: bool = True) -> None:
        """Halt playback and reset state."""
        vc = self.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()

        if clear_queue:
            async with self.lock:
                self.queue.clear()

        self.current_track = None
        self.current_source = None
        self.state = PlayerState.STOPPED
        self._schedule_inactivity_timeout()
        await self.update_player_message()

    def set_volume(self, volume: int) -> int:
        """Set volume clamped between 1 and 150."""
        clamped = max(1, min(150, volume))
        self.volume = clamped
        if self.current_source:
            self.current_source.volume = clamped / 100.0
        return clamped

    def set_loop_mode(self, mode: LoopMode) -> LoopMode:
        """Update looping behavior."""
        self.loop_mode = mode
        return mode

    def toggle_autoplay(self) -> bool:
        """Toggle autoplay recommendation engine."""
        self.autoplay = not self.autoplay
        return self.autoplay

    def shuffle(self) -> int:
        """Shuffle existing queued tracks."""
        random.shuffle(self.queue)
        return len(self.queue)

    async def set_filter(self, audio_filter: AudioFilter) -> None:
        """Apply an FFmpeg audio filter on-the-fly without losing playback position."""
        self.active_filter = audio_filter
        if self.current_track and self.current_source and self.voice_client:
            # Save current playback position
            offset = self.elapsed_seconds
            self.current_track.start_offset = offset
            vc = self.voice_client
            # Recreate audio stream with new filter arguments
            source = DeathAudioSource.create_stream(
                stream_url=self.current_track.source_info.url,
                volume=self.volume / 100.0,
                audio_filter=self.active_filter,
                start_offset=offset,
            )
            self.current_source = source
            # Hot-swap source inside Discord VoiceClient
            if vc.is_playing() or vc.is_paused():
                vc._player = None  # Detach old audio player safely
                vc.play(source)

    # --------------------------------------------------------------------------
    # DJ & Permission Management
    # --------------------------------------------------------------------------

    async def can_control(self, member: discord.Member) -> Tuple[bool, str]:
        """Check if a member is authorized to control playback."""
        # 1. Administrator or Manage Guild override
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True, "Authorized (Administrator Override)"

        # 2. Track Requester override
        if self.current_track and member.id == self.current_track.requester_id:
            return True, "Authorized (Track Requester)"

        # 3. If DJ Mode is disabled, allow all connected listeners
        if not self.dj_only:
            return True, "Authorized"

        # 4. Check DJ Role
        if self.dj_role_id:
            if any(role.id == self.dj_role_id for role in member.roles):
                return True, "Authorized (DJ Role)"
            return False, f"DJ Mode is enabled. You need the <@&{self.dj_role_id}> role."

        return True, "Authorized"

    def vote_skip(self, user_id: int) -> Tuple[bool, int, int]:
        """Register a skip vote. Returns (has_passed, current_votes, required_votes)."""
        vc = self.voice_client
        if not vc or not vc.channel:
            return False, 0, 1

        listeners = [m for m in vc.channel.members if not m.bot]
        required = max(1, math.ceil(len(listeners) * self.vote_skip_ratio))

        self.skip_votes.add(user_id)
        current = len(self.skip_votes)

        passed = current >= required
        return passed, current, required

    # --------------------------------------------------------------------------
    # Embed & Interactive UI Builders
    # --------------------------------------------------------------------------

    def build_player_embed(self) -> discord.Embed:
        """Construct the signature Obsidian & Neon Purple now-playing embed."""
        if not self.current_track:
            return EmbedBuilder.base(
                title=f"{KrovexEmoji.MUSIC} KROVEX • Music Engine Idle",
                description="No track currently playing. Add songs using `/play` or `!play <song>`.",
                color=0x7B2CBF,
                footer_text="KROVEX High-Fidelity Audio • Standby",
            )

        track = self.current_track
        info = track.source_info
        elapsed = self.elapsed_seconds

        state_badge = f"{KrovexEmoji.BLUE} Playing" if self.state == PlayerState.PLAYING else "⏸️ Paused"
        if self.state == PlayerState.STOPPED:
            state_badge = "⏹️ Stopped"

        embed = EmbedBuilder.base(
            title=f"{state_badge} • {track.title}",
            color=0x9D4EDD,
            thumbnail=track.thumbnail,
            footer_text=f"Requested by {track.requester_name} • KROVEX Engine",
        )

        # Progress bar
        embed.add_field(
            name="Progress",
            value=info.progress_bar(elapsed),
            inline=False,
        )

        # Technical Metadata
        filter_badge = f"`{self.active_filter.value.upper()}`" if self.active_filter != AudioFilter.OFF else "`OFF`"
        loop_badge = f"`{self.loop_mode.value.upper()}`"
        autoplay_badge = "`ON`" if self.autoplay else "`OFF`"

        embed.add_field(name="Uploader", value=f"`{track.uploader}`", inline=True)
        embed.add_field(name="Volume", value=f"`{self.volume}%`", inline=True)
        embed.add_field(name="Loop", value=loop_badge, inline=True)
        embed.add_field(name="Filter", value=filter_badge, inline=True)
        embed.add_field(name="Autoplay", value=autoplay_badge, inline=True)
        embed.add_field(name="In Queue", value=f"`{len(self.queue)}` tracks", inline=True)

        return embed

    def build_queue_embed(self, page: int = 1, per_page: int = 10) -> discord.Embed:
        """Construct a paginated queue list embed."""
        total_tracks = len(self.queue)
        total_pages = max(1, math.ceil(total_tracks / per_page))
        current_page = max(1, min(page, total_pages))

        start_idx = (current_page - 1) * per_page
        end_idx = start_idx + per_page
        page_tracks = self.queue[start_idx:end_idx]

        embed = EmbedBuilder.base(
            title=f"📜 Playback Queue • {total_tracks} Tracks",
            description=f"Currently Playing: **{self.current_track.title if self.current_track else 'None'}**",
            color=0x9D4EDD,
            footer_text=f"Page {current_page} of {total_pages} • KROVEX Music",
        )

        if page_tracks:
            lines = []
            for i, t in enumerate(page_tracks, start=start_idx + 1):
                lines.append(f"`{i:02d}.` **[{t.title}]({t.uri})** `[{t.source_info.formatted_duration}]` • <@{t.requester_id}>")
            embed.add_field(name="Upcoming Tracks", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="Upcoming Tracks", value="*The queue is currently empty.*", inline=False)

        return embed

    async def update_player_message(self) -> None:
        """Update or create the persistent player control board."""
        if not self.text_channel:
            return

        embed = self.build_player_embed()
        if not self.player_view:
            self.player_view = MusicPlayerView(self)
        else:
            self.player_view._update_button_states()

        if self.player_message:
            try:
                await self.player_message.edit(embed=embed, view=self.player_view)
                return
            except (discord.NotFound, discord.HTTPException):
                # Message was deleted by user or purged
                self.player_message = None

        try:
            self.player_message = await self.text_channel.send(embed=embed, view=self.player_view)
        except Exception as err:
            logger.warning("Could not send player message in %s: %s", self.text_channel.name, err)

