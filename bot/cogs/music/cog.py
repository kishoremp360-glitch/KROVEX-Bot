"""Premium music engine command cog for Death Bot.

Implements all playback, queue, autoplay, playlist, lyrics, audio filter, and DJ controls
with 100% shared business logic between Prefix (!) and Slash (/) command architectures.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.services.music.lyrics import LyricsService
from bot.services.music.player import GuildAudioPlayer
from bot.services.music.source import AudioFilter, LoopMode, Track
from bot.services.music.views import PaginatedQueueView, SongSelectView
from bot.utils.embeds import EmbedBuilder
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.music")


class Music(commands.Cog, name="Music System"):
    """Next-generation premium interactive music engine."""

    music = app_commands.Group(name="music", description="KROVEX Music System controls")
    filter = app_commands.Group(name="filter", description="Audio DSP equalizer filters", parent=music)
    playlist = app_commands.Group(name="playlist", description="KROVEX Playlist management")

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    def _get_player(self, guild_id: int) -> GuildAudioPlayer:
        """Helper to retrieve or initialize a guild audio player."""
        if not self.bot.music_service:
            raise RuntimeError("MusicService not initialized on bot.")
        return self.bot.music_service.get_player(guild_id)

    async def _ensure_voice(self, ctx: UnifiedContext) -> Optional[discord.VoiceClient]:
        """Verify the user is connected to voice and connect or move bot to user's channel."""
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await ctx.send_error("Server Only", "Music commands can only be used in a server.")
            return None

        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send_error(
                "Voice Required",
                "You must be connected to a voice channel to use music commands.",
            )
            return None

        user_channel = ctx.author.voice.channel
        voice_client: Optional[discord.VoiceClient] = ctx.guild.voice_client

        # Reclaim stale or disconnected voice client before attempting new operations
        if voice_client is not None and not voice_client.is_connected():
            logger.warning("Voice client in guild %s is disconnected or stale. Reconnecting...", ctx.guild.id)
            try:
                await voice_client.disconnect(force=True)
            except Exception as exc:
                logger.debug("Error forcing voice_client disconnect: %s", exc)
            voice_client = None

        if voice_client is None:
            # Check bot permissions in voice channel
            perms = user_channel.permissions_for(ctx.guild.me)
            if not perms.connect or not perms.speak:
                await ctx.send_error(
                    "Missing Permissions",
                    f"I need `Connect` and `Speak` permissions in {user_channel.mention}!",
                )
                return None
            try:
                voice_client = await user_channel.connect()
            except Exception as exc:
                logger.error("Failed to connect to voice channel: %s", exc)
                await ctx.send_error("Connection Error", f"Failed to connect to voice channel: `{exc}`")
                return None
        elif voice_client.channel != user_channel:
            # Bot is in another channel: if alone or caller has DJ/Admin, move; else require same channel
            if len([m for m in voice_client.channel.members if not m.bot]) == 0 or ctx.is_owner():
                await voice_client.move_to(user_channel)
            else:
                await ctx.send_error(
                    "Channel Mismatch",
                    f"I am already playing in {voice_client.channel.mention}. Please join that channel or wait until it's free.",
                )
                return None

        return voice_client

    # =========================================================================
    # 1. PLAYBACK CONTROLS
    # =========================================================================

    async def _execute_play(self, ctx: UnifiedContext, query: str) -> None:
        """Shared logic for playing an audio track or adding it to the queue."""
        await ctx.defer()

        if not query or not query.strip():
            await ctx.send_error("Missing Query", "Please provide a song name, keyword, or URL to play.")
            return

        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        player = self._get_player(ctx.guild.id)
        if ctx.channel and isinstance(ctx.channel, discord.TextChannel):
            player.text_channel = ctx.channel

        query = query.strip()

        # Check for Spotify playlist or album collections
        if "spotify.com" in query.lower() and ("album" in query.lower() or "playlist" in query.lower()):
            try:
                coll = await self.bot.music_service.resolver.resolve_spotify_collection(query)
                if coll and coll.get("tracks"):
                    tracks = coll["tracks"]
                    coll_type = coll.get("type", "playlist").capitalize()
                    coll_name = coll.get("name", "Spotify Collection")
                    guild_id = ctx.guild.id if ctx.guild else 0

                    # Enqueue first track immediately to start audio without waiting
                    first_track_info, _ = await self.bot.music_service.resolver.resolve(tracks[0]["query"])
                    first_track = Track(
                        source_info=first_track_info,
                        requester_id=ctx.author.id,
                        requester_name=ctx.author.display_name,
                    )
                    pos, started = await player.enqueue(first_track)

                    # Background task to enqueue remaining tracks with cancellation & rate-limit handling
                    async def enqueue_remaining():
                        for item in tracks[1:100]:  # Cap at 100 tracks
                            current_player = self._get_player(guild_id)
                            if not current_player or not current_player.is_connected:
                                break
                            try:
                                src, _ = await self.bot.music_service.resolver.resolve(item["query"])
                                trk = Track(
                                    source_info=src,
                                    requester_id=ctx.author.id,
                                    requester_name=ctx.author.display_name,
                                )
                                await current_player.enqueue(trk)
                                await asyncio.sleep(0.05)
                            except Exception as track_err:
                                logger.debug("Skipping unresolvable track '%s': %s", item.get("title"), track_err)
                                continue

                    asyncio.create_task(enqueue_remaining())

                    provider_label = first_track.source_info.source_provider.capitalize()
                    embed = EmbedBuilder.base(
                        title=f"🟢 Spotify {coll_type} Loaded",
                        description=f"Loaded **{len(tracks)}** tracks from **{coll_name}**.\n\n"
                                    f"▶ Now Playing: **[{first_track.title}]({first_track.uri})**\n"
                                    f"*(Audio matched & streamed via {provider_label})*",
                        color=0x1DB954,
                    )
                    if first_track.source_info.thumbnail_url:
                        embed.set_thumbnail(url=first_track.source_info.thumbnail_url)
                    await ctx.reply(embed=embed)
                    return
            except Exception as exc:
                logger.warning("Failed to batch load Spotify collection: %s; falling back to single track resolve", exc)

        try:
            primary, candidates = await self.bot.music_service.resolver.resolve(query)
        except Exception as exc:
            await ctx.send_error("Resolution Error", f"Could not find or resolve track: `{exc}`")
            return

        track = Track(
            source_info=primary,
            requester_id=ctx.author.id,
            requester_name=ctx.author.display_name,
        )

        pos, started = await player.enqueue(track)

        if started:
            source_suffix = f" *(via {track.source_info.source_provider.capitalize()})*" if track.source_info.original_source == "spotify" else ""
            await ctx.send_success("Now Playing", f"Playing **[{track.title}]({track.uri})**{source_suffix}.")
        else:
            embed = EmbedBuilder.base(
                title="🎵 Track Enqueued",
                description=f"Added **[{track.title}]({track.uri})** to the queue at position `#{pos}`.",
                color=0x9D4EDD,
            )
            embed.add_field(name="Duration", value=f"`{track.source_info.formatted_duration}`", inline=True)
            embed.add_field(name="Requested By", value=track.requester_name, inline=True)
            if track.source_info.original_source == "spotify":
                embed.add_field(name="Audio Source", value=f"Matched via `{track.source_info.source_provider.capitalize()}`", inline=True)
            if track.source_info.thumbnail_url:
                embed.set_thumbnail(url=track.source_info.thumbnail_url)
            await ctx.reply(embed=embed)

    @commands.command(name="play", aliases=["p"], help="Play a song by name, URL, or playlist.")
    async def play_prefix(self, ctx: commands.Context, *, query: str) -> None:
        await self._execute_play(UnifiedContext.from_prefix(ctx), query)

    @app_commands.command(name="play", description="Play a song or playlist in your voice channel.")
    @app_commands.describe(query="Song title, artist, or URL to play")
    async def play_slash(self, interaction: discord.Interaction, query: str) -> None:
        await self._execute_play(UnifiedContext.from_interaction(interaction), query)

    # -------------------------------------------------------------------------
    # SEARCH COMMAND
    # -------------------------------------------------------------------------

    async def _execute_search(self, ctx: UnifiedContext, query: str) -> None:
        """Search and display top matches with an interactive selector."""
        await ctx.defer()

        if not query or not query.strip():
            await ctx.send_error("Missing Query", "Please specify a search query.")
            return

        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        player = self._get_player(ctx.guild.id)
        if ctx.channel and isinstance(ctx.channel, discord.TextChannel):
            player.text_channel = ctx.channel

        try:
            _, candidates = await self.bot.music_service.resolver.resolve(query, min_confidence=0.0)
        except Exception as exc:
            await ctx.send_error("Search Error", f"Search failed: `{exc}`")
            return

        if not candidates:
            await ctx.send_error("No Results", f"No results found for `{query}`.")
            return

        view = SongSelectView(
            candidates=candidates,
            user_id=ctx.author.id,
            timeout=45.0,
        )
        embed = EmbedBuilder.base(
            title=f"🔍 Search Results for: {query[:50]}",
            description="Select a song from the dropdown menu below to begin playback:",
            color=0x9D4EDD,
        )
        for idx, item in enumerate(candidates[:5], 1):
            embed.add_field(
                name=f"{idx}. {item.title[:65]}",
                value=f"**Artist**: {item.uploader} • **Duration**: `{item.formatted_duration}`",
                inline=False,
            )
        msg = await ctx.reply(embed=embed, view=view)

        await view.wait()
        if view.selected_candidate:
            chosen_track = Track(
                source_info=view.selected_candidate,
                requester_id=ctx.author.id,
                requester_name=ctx.author.display_name,
            )
            pos, started = await player.enqueue(chosen_track)
            if started:
                await ctx.send_success("Now Playing", f"Playing **[{chosen_track.title}]({chosen_track.uri})**.")
            else:
                await ctx.send_success("Track Enqueued", f"Added **{chosen_track.title}** to queue (`#{pos}`).")

    @commands.command(name="search", aliases=["find"], help="Search for songs and choose interactively.")
    async def search_prefix(self, ctx: commands.Context, *, query: str) -> None:
        await self._execute_search(UnifiedContext.from_prefix(ctx), query)

    @music.command(name="search", description="Search for songs and pick interactively.")
    @app_commands.describe(query="Keywords to search for")
    async def search_slash(self, interaction: discord.Interaction, query: str) -> None:
        await self._execute_search(UnifiedContext.from_interaction(interaction), query)

    # -------------------------------------------------------------------------
    # PAUSE & RESUME
    # -------------------------------------------------------------------------

    async def _execute_pause(self, ctx: UnifiedContext) -> None:
        """Pause playback."""
        player = self._get_player(ctx.guild.id)
        if not player.current_track:
            await ctx.send_error("Not Playing", "There is no audio currently playing.")
            return

        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        if await player.pause():
            await ctx.send_success("Paused", "Audio playback has been paused.")
        else:
            await ctx.send_error("Error", "Playback is already paused or unavailable.")

    @commands.command(name="pause", help="Pause current audio playback.")
    async def pause_prefix(self, ctx: commands.Context) -> None:
        await self._execute_pause(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="pause", description="Pause current audio playback.")
    async def pause_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_pause(UnifiedContext.from_interaction(interaction))

    async def _execute_resume(self, ctx: UnifiedContext) -> None:
        """Resume paused playback."""
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        if await player.resume():
            await ctx.send_success("Resumed", "Audio playback has been resumed.")
        else:
            await ctx.send_error("Error", "Playback is not paused.")

    @commands.command(name="resume", aliases=["unpause"], help="Resume paused audio playback.")
    async def resume_prefix(self, ctx: commands.Context) -> None:
        await self._execute_resume(UnifiedContext.from_prefix(ctx))

    @music.command(name="resume", description="Resume paused audio playback.")
    async def resume_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_resume(UnifiedContext.from_interaction(interaction))

    # -------------------------------------------------------------------------
    # SKIP & PREVIOUS & STOP
    # -------------------------------------------------------------------------

    async def _execute_skip(self, ctx: UnifiedContext, force: bool = False) -> None:
        """Skip the current track, handling DJ check or vote skip."""
        player = self._get_player(ctx.guild.id)
        if not player.current_track:
            await ctx.send_error("Not Playing", "No audio is currently playing to skip.")
            return

        has_perm, _ = await player.can_control(ctx.author)
        if has_perm or force:
            await player.skip()
            await ctx.send_success("Skipped", "Skipped to the next track.")
            return

        passed, voted, required = player.vote_skip(ctx.author.id)
        if passed:
            await player.skip()
            await ctx.send_success("Vote Skip Passed", f"Skip threshold reached (`{voted}/{required}`). Skipping!")
        else:
            await ctx.reply(f"🗳️ Skip vote added! (`{voted}/{required}` votes needed)")

    @commands.command(name="skip", aliases=["s", "next"], help="Skip the current track (or vote skip).")
    async def skip_prefix(self, ctx: commands.Context) -> None:
        await self._execute_skip(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="skip", description="Skip the current track.")
    async def skip_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_skip(UnifiedContext.from_interaction(interaction))

    async def _execute_forceskip(self, ctx: UnifiedContext) -> None:
        """Force skip bypassing vote requirements."""
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return
        await self._execute_skip(ctx, force=True)

    @commands.command(name="forceskip", aliases=["fs"], help="Instantly skip current song (DJ/Admin).")
    async def forceskip_prefix(self, ctx: commands.Context) -> None:
        await self._execute_forceskip(UnifiedContext.from_prefix(ctx))

    @music.command(name="forceskip", description="Instantly skip without voting (DJ only).")
    async def forceskip_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_forceskip(UnifiedContext.from_interaction(interaction))

    async def _execute_previous(self, ctx: UnifiedContext) -> None:
        """Replay the previous track from history."""
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        success = await player.play_previous()
        if success:
            await ctx.send_success("Previous Track", "Playing previous track from history.")
        else:
            await ctx.send_error("No Previous Track", "There are no previous tracks in playback history.")

    @commands.command(name="previous", aliases=["prev", "back"], help="Play the previous song from history.")
    async def previous_prefix(self, ctx: commands.Context) -> None:
        await self._execute_previous(UnifiedContext.from_prefix(ctx))

    @music.command(name="previous", description="Play the previous song from history.")
    async def previous_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_previous(UnifiedContext.from_interaction(interaction))

    async def _execute_stop(self, ctx: UnifiedContext) -> None:
        """Stop playback and clear queue."""
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        await player.stop(clear_queue=True)
        await ctx.send_success("Playback Stopped", "Audio playback stopped and queue has been cleared.")

    @commands.command(name="stop", help="Stop playback and clear queue.")
    async def stop_prefix(self, ctx: commands.Context) -> None:
        await self._execute_stop(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="stop", description="Stop playback and clear the queue.")
    async def stop_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_stop(UnifiedContext.from_interaction(interaction))

    async def _execute_disconnect(self, ctx: UnifiedContext) -> None:
        """Disconnect bot from voice and clean up state."""
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        await player.disconnect()
        self.bot.music_service.cleanup_guild(ctx.guild.id)
        await ctx.send_success("Disconnected", "Left the voice channel and cleaned up audio player.")

    @commands.command(name="disconnect", aliases=["leave", "dc"], help="Disconnect the bot from voice.")
    async def disconnect_prefix(self, ctx: commands.Context) -> None:
        await self._execute_disconnect(UnifiedContext.from_prefix(ctx))

    @music.command(name="disconnect", description="Disconnect bot from the voice channel.")
    async def disconnect_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_disconnect(UnifiedContext.from_interaction(interaction))

    async def _execute_join(self, ctx: UnifiedContext) -> None:
        """Explicitly connect the bot to the author's voice channel."""
        await ctx.defer()
        vc = await self._ensure_voice(ctx)
        if vc:
            await ctx.send_success("Connected", f"Connected to {vc.channel.mention}.")

    @commands.command(name="join", aliases=["connect"], help="Connect bot to your voice channel.")
    async def join_prefix(self, ctx: commands.Context) -> None:
        await self._execute_join(UnifiedContext.from_prefix(ctx))

    @music.command(name="join", description="Connect bot to your voice channel.")
    async def join_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_join(UnifiedContext.from_interaction(interaction))

    # -------------------------------------------------------------------------
    # NOW PLAYING & VOLUME
    # -------------------------------------------------------------------------

    async def _execute_nowplaying(self, ctx: UnifiedContext) -> None:
        """Display detailed now playing embed with live progress and neon design."""
        player = self._get_player(ctx.guild.id)
        player.sync_state()
        if not player.current_track:
            await ctx.send_error("Nothing Playing", "No audio is currently playing in this server.")
            return

        embed = player.build_player_embed()
        await ctx.reply(embed=embed)

    @commands.command(name="nowplaying", aliases=["np", "current"], help="Show currently playing track.")
    async def nowplaying_prefix(self, ctx: commands.Context) -> None:
        await self._execute_nowplaying(UnifiedContext.from_prefix(ctx))

    @music.command(name="nowplaying", description="Show the currently playing track.")
    async def nowplaying_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_nowplaying(UnifiedContext.from_interaction(interaction))

    async def _execute_volume(self, ctx: UnifiedContext, volume: Optional[int] = None) -> None:
        """Inspect or adjust playback volume (1-150%)."""
        player = self._get_player(ctx.guild.id)
        if volume is None:
            await ctx.reply(f"🔊 Current playback volume: `{player.volume}%`")
            return

        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        new_vol = player.set_volume(volume)
        await ctx.send_success("Volume Updated", f"Playback volume set to `{new_vol}%`.")

    @commands.command(name="volume", aliases=["vol", "v"], help="View or adjust volume (1-150%).")
    async def volume_prefix(self, ctx: commands.Context, volume: Optional[int] = None) -> None:
        await self._execute_volume(UnifiedContext.from_prefix(ctx), volume)

    @music.command(name="volume", description="View or adjust playback volume.")
    @app_commands.describe(volume="Volume level between 1 and 150")
    async def volume_slash(self, interaction: discord.Interaction, volume: Optional[app_commands.Range[int, 1, 150]] = None) -> None:
        await self._execute_volume(UnifiedContext.from_interaction(interaction), volume)

    # =========================================================================
    # 2. QUEUE MANAGEMENT
    # =========================================================================

    async def _execute_queue(self, ctx: UnifiedContext) -> None:
        """Display paginated interactive queue view."""
        player = self._get_player(ctx.guild.id)
        if not player.current_track and len(player.queue) == 0:
            await ctx.send_error("Empty Queue", "The queue is completely empty. Use `/play` to add songs!")
            return

        embed = player.build_queue_embed(page=1)
        view = PaginatedQueueView(player=player, current_page=1, timeout=60.0)
        await ctx.reply(embed=embed, view=view if len(player.queue) > 10 else None)

    @commands.command(name="queue", aliases=["q"], help="View the current playback queue.")
    async def queue_prefix(self, ctx: commands.Context) -> None:
        await self._execute_queue(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="queue", description="View current music playback queue.")
    async def queue_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_queue(UnifiedContext.from_interaction(interaction))

    async def _execute_clear(self, ctx: UnifiedContext) -> None:
        """Clear the queue."""
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        count = len(player.queue)
        player.queue.clear()
        await ctx.send_success("Queue Cleared", f"Removed `{count}` tracks from the queue.")

    @commands.command(name="clear", aliases=["clearqueue", "cq"], help="Clear all queued songs.")
    async def clear_prefix(self, ctx: commands.Context) -> None:
        await self._execute_clear(UnifiedContext.from_prefix(ctx))

    @music.command(name="clear", description="Clear all songs from the queue.")
    async def clear_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_clear(UnifiedContext.from_interaction(interaction))

    async def _execute_remove(self, ctx: UnifiedContext, position: int) -> None:
        """Remove a track by its 1-based position."""
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        idx = position - 1
        if 0 <= idx < len(player.queue):
            removed = player.queue.pop(idx)
            await ctx.send_success("Track Removed", f"Removed **{removed.title}** from position `#{position}`.")
        else:
            await ctx.send_error("Invalid Position", f"Position `#{position}` is out of range. Current queue size: `{len(player.queue)}`.")

    @commands.command(name="remove", aliases=["rm"], help="Remove a song from queue by position.")
    async def remove_prefix(self, ctx: commands.Context, position: int) -> None:
        await self._execute_remove(UnifiedContext.from_prefix(ctx), position)

    @music.command(name="remove", description="Remove a track from the queue by position.")
    @app_commands.describe(position="Queue position number (1-based)")
    async def remove_slash(self, interaction: discord.Interaction, position: int) -> None:
        await self._execute_remove(UnifiedContext.from_interaction(interaction), position)

    async def _execute_shuffle(self, ctx: UnifiedContext) -> None:
        """Randomize queue tracks."""
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        if len(player.queue) < 2:
            await ctx.send_error("Queue Too Small", "Need at least 2 tracks in the queue to shuffle.")
            return

        player.shuffle()
        await ctx.send_success("Queue Shuffled", f"🔀 Shuffled `{len(player.queue)}` tracks.")

    @commands.command(name="shuffle", aliases=["sh"], help="Randomly shuffle the playback queue.")
    async def shuffle_prefix(self, ctx: commands.Context) -> None:
        await self._execute_shuffle(UnifiedContext.from_prefix(ctx))

    @music.command(name="shuffle", description="Randomly shuffle songs in the queue.")
    async def shuffle_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_shuffle(UnifiedContext.from_interaction(interaction))

    async def _execute_loop(self, ctx: UnifiedContext, mode: Optional[str] = None) -> None:
        """Set or cycle loop mode (off, track, queue)."""
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        if mode is None:
            # Cycle through off -> track -> queue -> off
            transitions = {
                LoopMode.OFF: LoopMode.TRACK,
                LoopMode.TRACK: LoopMode.QUEUE,
                LoopMode.QUEUE: LoopMode.OFF,
            }
            player.set_loop_mode(transitions.get(player.loop_mode, LoopMode.OFF))
        else:
            mode_lower = mode.lower().strip()
            if mode_lower in ("off", "none", "disable"):
                player.set_loop_mode(LoopMode.OFF)
            elif mode_lower in ("track", "song", "current", "1"):
                player.set_loop_mode(LoopMode.TRACK)
            elif mode_lower in ("queue", "all"):
                player.set_loop_mode(LoopMode.QUEUE)
            else:
                await ctx.send_error("Invalid Mode", "Valid loop modes are: `off`, `track`, `queue`.")
                return

        await ctx.send_success("Loop Mode Updated", f"Loop mode set to: **`{player.loop_mode.value.upper()}`**")

    @commands.command(name="loop", aliases=["repeat"], help="Toggle loop mode (off, track, queue).")
    async def loop_prefix(self, ctx: commands.Context, mode: Optional[str] = None) -> None:
        await self._execute_loop(UnifiedContext.from_prefix(ctx), mode)

    @music.command(name="loop", description="Change playback looping mode.")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Off", value="off"),
        app_commands.Choice(name="Current Track", value="track"),
        app_commands.Choice(name="Entire Queue", value="queue"),
    ])
    async def loop_slash(self, interaction: discord.Interaction, mode: Optional[str] = None) -> None:
        await self._execute_loop(UnifiedContext.from_interaction(interaction), mode)

    async def _execute_skipto(self, ctx: UnifiedContext, position: int) -> None:
        """Skip directly to a specific position in the queue."""
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        if position < 1 or position > len(player.queue):
            await ctx.send_error("Out of Range", f"Position `#{position}` is out of range (`1 - {len(player.queue)}`).")
            return

        # Pop all tracks prior to target position
        del player.queue[:position - 1]
        await player.skip()
        await ctx.send_success("Skipped To", f"Skipped directly to track `#{position}`.")

    @commands.command(name="skipto", aliases=["jump"], help="Skip directly to a track in queue.")
    async def skipto_prefix(self, ctx: commands.Context, position: int) -> None:
        await self._execute_skipto(UnifiedContext.from_prefix(ctx), position)

    @music.command(name="skipto", description="Skip directly to a song in the queue.")
    @app_commands.describe(position="Position number to jump to")
    async def skipto_slash(self, interaction: discord.Interaction, position: int) -> None:
        await self._execute_skipto(UnifiedContext.from_interaction(interaction), position)

    # =========================================================================
    # 3. AUTOPLAY & 24/7 MODE
    # =========================================================================

    async def _execute_autoplay(self, ctx: UnifiedContext) -> None:
        """Toggle smart autoplay recommendation engine."""
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        enabled = player.toggle_autoplay()
        state = "Enabled 🟢" if enabled else "Disabled 🔴"
        await ctx.send_success("Autoplay", f"Smart autoplay recommendations: **{state}**.")

    @commands.command(name="autoplay", aliases=["ap"], help="Toggle smart autoplay recommendation engine.")
    async def autoplay_prefix(self, ctx: commands.Context) -> None:
        await self._execute_autoplay(UnifiedContext.from_prefix(ctx))

    @music.command(name="autoplay", description="Toggle smart music autoplay recommendations.")
    async def autoplay_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_autoplay(UnifiedContext.from_interaction(interaction))

    async def _execute_247(self, ctx: UnifiedContext) -> None:
        """Toggle 24/7 voice stay-connected mode."""
        await ctx.defer()
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        player.twenty_four_seven = not player.twenty_four_seven
        # Persist to database if repository available
        if self.bot.music_repo:
            await self.bot.music_repo.update_settings(ctx.guild.id, twenty_four_seven=player.twenty_four_seven)

        status = "Active 🟢 (Bot will stay connected permanently)" if player.twenty_four_seven else "Disabled 🔴 (Bot will disconnect when empty)"
        await ctx.send_success("24/7 Mode", f"24/7 Voice Mode: **{status}**")

    @commands.command(name="247", aliases=["stay", "alwayson"], help="Toggle 24/7 persistent voice connection.")
    async def twenty_four_seven_prefix(self, ctx: commands.Context) -> None:
        await self._execute_247(UnifiedContext.from_prefix(ctx))

    @music.command(name="247", description="Toggle 24/7 voice connection mode.")
    async def twenty_four_seven_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_247(UnifiedContext.from_interaction(interaction))

    # =========================================================================
    # 4. AUDIO FILTERS (DSP)
    # =========================================================================

    async def _execute_filter(self, ctx: UnifiedContext, audio_filter: AudioFilter) -> None:
        """Apply a live FFmpeg DSP filter."""
        player = self._get_player(ctx.guild.id)
        has_perm, reason = await player.can_control(ctx.author)
        if not has_perm:
            await ctx.send_error("Permission Denied", reason)
            return

        await ctx.defer()
        await player.set_filter(audio_filter)
        name = audio_filter.value.upper()
        if audio_filter == AudioFilter.OFF:
            await ctx.send_success("Filter Reset", "All audio filters have been removed. Normal playback resumed.")
        else:
            await ctx.send_success("Filter Applied", f"Active audio DSP filter set to: **`{name}`**.")

    @commands.command(name="bassboost", aliases=["bb"], help="Apply bassboost DSP filter.")
    async def bassboost_prefix(self, ctx: commands.Context) -> None:
        await self._execute_filter(UnifiedContext.from_prefix(ctx), AudioFilter.BASSBOOST)

    @filter.command(name="bass", description="Apply heavy bass boost filter.")
    async def bass_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_filter(UnifiedContext.from_interaction(interaction), AudioFilter.BASSBOOST)

    @commands.command(name="nightcore", aliases=["nc"], help="Apply nightcore (speed + pitch up) filter.")
    async def nightcore_prefix(self, ctx: commands.Context) -> None:
        await self._execute_filter(UnifiedContext.from_prefix(ctx), AudioFilter.NIGHTCORE)

    @filter.command(name="nightcore", description="Apply nightcore (pitch and tempo increase) filter.")
    async def nightcore_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_filter(UnifiedContext.from_interaction(interaction), AudioFilter.NIGHTCORE)

    @commands.command(name="vaporwave", aliases=["vw"], help="Apply vaporwave (slow + pitch down) filter.")
    async def vaporwave_prefix(self, ctx: commands.Context) -> None:
        await self._execute_filter(UnifiedContext.from_prefix(ctx), AudioFilter.VAPORWAVE)

    @filter.command(name="vaporwave", description="Apply slowed vaporwave audio filter.")
    async def vaporwave_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_filter(UnifiedContext.from_interaction(interaction), AudioFilter.VAPORWAVE)

    @commands.command(name="8d", aliases=["surround"], help="Apply 8D spatial audio rotation filter.")
    async def eight_d_prefix(self, ctx: commands.Context) -> None:
        await self._execute_filter(UnifiedContext.from_prefix(ctx), AudioFilter.EIGHT_D)

    @filter.command(name="8d", description="Apply 8D panning spatial audio filter.")
    async def eight_d_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_filter(UnifiedContext.from_interaction(interaction), AudioFilter.EIGHT_D)

    @commands.command(name="resetfilters", aliases=["clearfilters", "nofilter"], help="Reset all audio filters.")
    async def resetfilters_prefix(self, ctx: commands.Context) -> None:
        await self._execute_filter(UnifiedContext.from_prefix(ctx), AudioFilter.OFF)

    @filter.command(name="clear", description="Remove all audio filters and reset to normal.")
    async def resetfilters_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_filter(UnifiedContext.from_interaction(interaction), AudioFilter.OFF)

    # =========================================================================
    # 5. LYRICS ENGINE
    # =========================================================================

    async def _execute_lyrics(self, ctx: UnifiedContext, query: Optional[str] = None) -> None:
        """Fetch real lyrics from LRCLIB API without fabrication."""
        player = self._get_player(ctx.guild.id)
        target_title = ""
        target_artist = None

        if query and query.strip():
            target_title = query.strip()
        elif player.current_track:
            target_title = player.current_track.title
            target_artist = player.current_track.source_info.uploader
        else:
            await ctx.send_error("Missing Query", "Specify a song title to search or start playing a song first.")
            return

        await ctx.defer()
        result = await self.bot.music_service.lyrics_service.get_lyrics(
            track_name=target_title,
            artist_name=target_artist,
        )

        if not result:
            await ctx.send_error("Lyrics Not Found", f"No verified lyrics found for `{target_title}`.")
            return

        resolved_title, resolved_artist, lyrics_text = result

        # Paginate or truncate lyrics if they exceed Discord embed character limits (4096)
        display_text = lyrics_text[:3900] + ("\n\n... (truncated)" if len(lyrics_text) > 3900 else "")
        embed = EmbedBuilder.base(
            title=f"📜 Lyrics • {resolved_title[:50]}",
            description=display_text,
            color=0x9D4EDD,
        )
        if resolved_artist:
            embed.set_footer(text=f"Artist: {resolved_artist} • Source: lrclib.net")
        await ctx.reply(embed=embed)

    @commands.command(name="lyrics", aliases=["ly"], help="Search lyrics for current or specified song.")
    async def lyrics_prefix(self, ctx: commands.Context, *, query: Optional[str] = None) -> None:
        await self._execute_lyrics(UnifiedContext.from_prefix(ctx), query)

    @music.command(name="lyrics", description="Fetch real lyrics for a song.")
    @app_commands.describe(query="Song title or artist (defaults to current playing track)")
    async def lyrics_slash(self, interaction: discord.Interaction, query: Optional[str] = None) -> None:
        await self._execute_lyrics(UnifiedContext.from_interaction(interaction), query)

    # =========================================================================
    # 6. PLAYLIST REPOSITORY INTEGRATION
    # =========================================================================

    async def _execute_playlist_create(self, ctx: UnifiedContext, name: str) -> None:
        """Create a new custom playlist for this server."""
        if not self.bot.playlist_repo:
            await ctx.send_error("Database Unavailable", "Playlist storage is currently unavailable.")
            return

        clean_name = name.strip()
        success = await self.bot.playlist_repo.create_playlist(
            guild_id=ctx.guild.id,
            user_id=ctx.author.id,
            name=clean_name,
        )
        if success:
            await ctx.send_success("Playlist Created", f"Successfully created playlist **`{clean_name}`**.")
        else:
            await ctx.send_error("Already Exists", f"A playlist named **`{clean_name}`** already exists in this server.")

    @commands.command(name="playlistcreate", aliases=["plc"], help="Create a saved custom playlist.")
    async def playlistcreate_prefix(self, ctx: commands.Context, *, name: str) -> None:
        await self._execute_playlist_create(UnifiedContext.from_prefix(ctx), name)

    @playlist.command(name="create", description="Create a new saved playlist.")
    @app_commands.describe(name="Playlist name")
    async def playlistcreate_slash(self, interaction: discord.Interaction, name: str) -> None:
        await self._execute_playlist_create(UnifiedContext.from_interaction(interaction), name)

    async def _execute_playlist_add(self, ctx: UnifiedContext, playlist_name: str, query: Optional[str] = None) -> None:
        """Add current song or query to a saved playlist."""
        if not self.bot.playlist_repo:
            await ctx.send_error("Database Unavailable", "Playlist storage is unavailable.")
            return

        player = self._get_player(ctx.guild.id)
        track_to_add: Optional[Track] = None

        if query and query.strip():
            await ctx.defer()
            try:
                primary, _ = await self.bot.music_service.resolver.resolve(query.strip())
                track_to_add = Track(
                    source_info=primary,
                    requester_id=ctx.author.id,
                    requester_name=ctx.author.display_name,
                )
            except Exception as exc:
                await ctx.send_error("Resolution Error", f"Could not find song: `{exc}`")
                return
        elif player.current_track:
            track_to_add = player.current_track

        if not track_to_add:
            await ctx.send_error("Missing Track", "Play a song or supply a search query to add.")
            return

        track_dict = {
            "title": track_to_add.title,
            "url": track_to_add.uri,
            "duration": track_to_add.duration,
            "uploader": track_to_add.source_info.uploader,
            "thumbnail_url": track_to_add.source_info.thumbnail_url,
        }

        success = await self.bot.playlist_repo.add_track(
            guild_id=ctx.guild.id,
            user_id=ctx.author.id,
            name=playlist_name.strip(),
            track_data=track_dict,
        )
        if success:
            await ctx.send_success("Track Added", f"Added **{track_to_add.title}** to playlist **`{playlist_name}`**.")
        else:
            await ctx.send_error("Not Found", f"Playlist **`{playlist_name}`** not found.")

    @commands.command(name="playlistadd", aliases=["pla"], help="Add current or specified song to playlist.")
    async def playlistadd_prefix(self, ctx: commands.Context, playlist_name: str, *, query: Optional[str] = None) -> None:
        await self._execute_playlist_add(UnifiedContext.from_prefix(ctx), playlist_name, query)

    @playlist.command(name="add", description="Add a song to a saved playlist.")
    @app_commands.describe(playlist_name="Target playlist name", query="Song to add (defaults to current track)")
    async def playlistadd_slash(self, interaction: discord.Interaction, playlist_name: str, query: Optional[str] = None) -> None:
        await self._execute_playlist_add(UnifiedContext.from_interaction(interaction), playlist_name, query)

    async def _execute_playlist_play(self, ctx: UnifiedContext, playlist_name: str) -> None:
        """Load and enqueue an entire saved playlist."""
        await ctx.defer()

        if not self.bot.playlist_repo:
            await ctx.send_error("Database Unavailable", "Playlist storage is unavailable.")
            return

        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        playlist = await self.bot.playlist_repo.get_playlist(
            guild_id=ctx.guild.id,
            user_id=ctx.author.id,
            name=playlist_name.strip(),
        )
        if not playlist or not playlist.get("tracks"):
            await ctx.send_error("Empty or Missing", f"Playlist **`{playlist_name}`** was not found or is empty.")
            return

        player = self._get_player(ctx.guild.id)
        if ctx.channel and isinstance(ctx.channel, discord.TextChannel):
            player.text_channel = ctx.channel

        tracks_data = playlist["tracks"]
        enqueued_count = 0

        for td in tracks_data:
            try:
                primary, _ = await self.bot.music_service.resolver.resolve(td["url"])
                t = Track(
                    source_info=primary,
                    requester_id=ctx.author.id,
                    requester_name=ctx.author.display_name,
                )
                await player.enqueue(t)
                enqueued_count += 1
            except Exception:
                continue

        await ctx.send_success(
            "Playlist Enqueued",
            f"Loaded and enqueued **{enqueued_count}** tracks from playlist **`{playlist_name}`**.",
        )

    @commands.command(name="playlistplay", aliases=["plp"], help="Load and play a saved playlist.")
    async def playlistplay_prefix(self, ctx: commands.Context, *, playlist_name: str) -> None:
        await self._execute_playlist_play(UnifiedContext.from_prefix(ctx), playlist_name)

    @playlist.command(name="play", description="Load and play a saved playlist.")
    @app_commands.describe(playlist_name="Playlist name to play")
    async def playlistplay_slash(self, interaction: discord.Interaction, playlist_name: str) -> None:
        await self._execute_playlist_play(UnifiedContext.from_interaction(interaction), playlist_name)

    async def _execute_playlist_list(self, ctx: UnifiedContext) -> None:
        """List all playlists owned by the user in this guild."""
        if not self.bot.playlist_repo:
            await ctx.send_error("Database Unavailable", "Playlist storage is unavailable.")
            return

        playlists = await self.bot.playlist_repo.list_playlists(guild_id=ctx.guild.id, user_id=ctx.author.id)
        if not playlists:
            await ctx.reply("📂 You do not have any saved playlists in this server yet.")
            return

        embed = EmbedBuilder.base(
            title=f"📂 Saved Playlists • {ctx.author.display_name}",
            description="Your custom saved playlists in this server:",
            color=0x9D4EDD,
        )
        for pl in playlists:
            track_count = len(pl.get("tracks", []))
            created_str = pl['created_at'].strftime('%Y-%m-%d') if hasattr(pl.get('created_at'), 'strftime') else "Recent"
            embed.add_field(
                name=f"🎵 {pl['name']}",
                value=f"Tracks: `{track_count}` • Created: `{created_str}`",
                inline=False,
            )
        await ctx.reply(embed=embed)

    @commands.command(name="playlistlist", aliases=["playlists", "plls"], help="List your saved playlists.")
    async def playlistlist_prefix(self, ctx: commands.Context) -> None:
        await self._execute_playlist_list(UnifiedContext.from_prefix(ctx))

    @playlist.command(name="list", description="List your saved playlists in this server.")
    async def playlists_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_playlist_list(UnifiedContext.from_interaction(interaction))

    async def _execute_playlist_delete(self, ctx: UnifiedContext, playlist_name: str) -> None:
        """Delete a saved playlist."""
        if not self.bot.playlist_repo:
            await ctx.send_error("Database Unavailable", "Playlist storage is unavailable.")
            return

        success = await self.bot.playlist_repo.delete_playlist(
            guild_id=ctx.guild.id,
            user_id=ctx.author.id,
            name=playlist_name.strip(),
        )
        if success:
            await ctx.send_success("Playlist Deleted", f"Deleted playlist **`{playlist_name}`**.")
        else:
            await ctx.send_error("Not Found", f"Playlist **`{playlist_name}`** does not exist.")

    @commands.command(name="playlistdelete", aliases=["pldel"], help="Delete a saved playlist.")
    async def playlistdelete_prefix(self, ctx: commands.Context, *, playlist_name: str) -> None:
        await self._execute_playlist_delete(UnifiedContext.from_prefix(ctx), playlist_name)

    @playlist.command(name="delete", description="Delete a saved playlist.")
    @app_commands.describe(playlist_name="Playlist name to delete")
    async def playlistdelete_slash(self, interaction: discord.Interaction, playlist_name: str) -> None:
        await self._execute_playlist_delete(UnifiedContext.from_interaction(interaction), playlist_name)

    # =========================================================================
    # 7. DJ ROLE & SETTINGS
    # =========================================================================

    async def _execute_djrole(self, ctx: UnifiedContext, role: Optional[discord.Role] = None) -> None:
        """Configure or inspect the guild DJ role."""
        if not ctx.author.guild_permissions.manage_guild and not ctx.is_owner():
            await ctx.send_error("Forbidden", "You need `Manage Server` permission to configure the DJ role.")
            return

        if not self.bot.music_repo:
            await ctx.send_error("Database Unavailable", "Settings storage is unavailable.")
            return

        if role is None:
            settings = await self.bot.music_repo.get_or_create(ctx.guild.id)
            if settings and settings.dj_role_id:
                dj_r = ctx.guild.get_role(settings.dj_role_id)
                name = dj_r.mention if dj_r else f"`Role ID: {settings.dj_role_id}`"
                await ctx.reply(f"🎧 Current DJ Role: {name}")
            else:
                await ctx.reply("🎧 No DJ role is currently configured (DJ commands open to everyone in voice).")
            return

        await self.bot.music_repo.update_settings(ctx.guild.id, dj_role_id=role.id)
        player = self._get_player(ctx.guild.id)
        player.dj_role_id = role.id
        player.dj_only = True
        await ctx.send_success("DJ Role Updated", f"DJ role has been set to {role.mention}.")

    @commands.command(name="djrole", aliases=["setdj"], help="View or set the server DJ role.")
    async def djrole_prefix(self, ctx: commands.Context, role: Optional[discord.Role] = None) -> None:
        await self._execute_djrole(UnifiedContext.from_prefix(ctx), role)

    @music.command(name="djrole", description="View or set the server DJ role.")
    @app_commands.describe(role="Role to designate as DJ (omit to inspect)")
    async def djrole_slash(self, interaction: discord.Interaction, role: Optional[discord.Role] = None) -> None:
        await self._execute_djrole(UnifiedContext.from_interaction(interaction), role)

    async def _execute_voteskip_settings(self, ctx: UnifiedContext, ratio: Optional[float] = None) -> None:
        """View or configure vote skip ratio (0.1 to 1.0)."""
        if ratio is not None and not ctx.author.guild_permissions.manage_guild and not ctx.is_owner():
            await ctx.send_error("Forbidden", "You need `Manage Server` permission to configure vote skip.")
            return

        player = self._get_player(ctx.guild.id)
        if ratio is None:
            pct = int(player.vote_skip_ratio * 100)
            await ctx.reply(f"🗳️ Current vote skip threshold: `{pct}%` of listeners.")
            return

        clamped = max(0.1, min(1.0, ratio))
        player.vote_skip_ratio = clamped
        if self.bot.music_repo:
            await self.bot.music_repo.update_settings(ctx.guild.id, vote_skip_ratio=clamped)

        await ctx.send_success("Vote Skip Updated", f"Vote skip threshold set to `{int(clamped * 100)}%`.")

    @commands.command(name="voteskipsettings", aliases=["voteratio"], help="View or configure vote skip ratio (0.1 - 1.0).")
    async def voteskipsettings_prefix(self, ctx: commands.Context, ratio: Optional[float] = None) -> None:
        await self._execute_voteskip_settings(UnifiedContext.from_prefix(ctx), ratio)

    @music.command(name="voteskipsettings", description="View or set vote skip threshold ratio.")
    @app_commands.describe(ratio="Fraction between 0.1 and 1.0 (e.g. 0.5 for 50%)")
    async def voteskipsettings_slash(self, interaction: discord.Interaction, ratio: Optional[app_commands.Range[float, 0.1, 1.0]] = None) -> None:
        await self._execute_voteskip_settings(UnifiedContext.from_interaction(interaction), ratio)

    # =========================================================================
    # 8. DIAGNOSTICS & SYSTEM STATUS
    # =========================================================================

    async def _execute_musicstatus(self, ctx: UnifiedContext) -> None:
        """Shared logic for music engine diagnostics."""
        has_nacl = discord.voice_client.has_nacl
        has_ffmpeg = self.bot.music_service.is_ffmpeg_available()
        has_ytdlp = self.bot.music_service.is_ytdlp_available()

        embed = EmbedBuilder.base(
            title="🎵 Music Engine Architecture & Status",
            description="Diagnostic overview of Death Bot's premium audio subsystem capabilities.",
            color=0x9D4EDD,
        )
        embed.add_field(
            name="Voice Native Libraries (PyNaCl)",
            value="🟢 Available" if has_nacl else "🔴 Missing PyNaCl",
            inline=True,
        )
        embed.add_field(
            name="Audio Processor (FFmpeg)",
            value="🟢 Installed" if has_ffmpeg else "🔴 Missing FFmpeg executable",
            inline=True,
        )
        embed.add_field(
            name="Stream Extractor (yt-dlp)",
            value="🟢 Installed" if has_ytdlp else "🔴 Missing yt-dlp",
            inline=True,
        )
        embed.add_field(
            name="Max Queue Limit",
            value=f"`{self.bot.config.max_queue_size}` tracks",
            inline=True,
        )
        embed.add_field(
            name="Default Volume",
            value=f"`{self.bot.config.default_volume}%`",
            inline=True,
        )
        embed.add_field(
            name="Active Guild Players",
            value=f"`{len(self.bot.music_service._players)}` active",
            inline=True,
        )
        embed.add_field(
            name="Audio Pipeline Status",
            value="🟢 Fully operational (Phase 2 Premium Audio Active)",
            inline=False,
        )

        await ctx.reply(embed=embed)

    @commands.command(name="musicstatus", aliases=["musicinfo", "ms"], help="Check music engine status and audio subsystem.")
    async def musicstatus_prefix(self, ctx: commands.Context) -> None:
        await self._execute_musicstatus(UnifiedContext.from_prefix(ctx))

    @music.command(name="status", description="Display music engine status and audio subsystem diagnostics.")
    async def musicstatus_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_musicstatus(UnifiedContext.from_interaction(interaction))

    async def _execute_musicsettings(self, ctx: UnifiedContext) -> None:
        """Shared logic for viewing music settings."""
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        settings = None
        if self.bot.music_repo:
            settings = await self.bot.music_repo.get_or_create(ctx.guild.id)

        default_vol = settings.default_volume if settings else self.bot.config.default_volume
        max_q = settings.max_queue_size if settings else self.bot.config.max_queue_size
        loop = settings.loop_mode if settings else "off"
        twenty_four_seven = "Enabled" if (settings and settings.twenty_four_seven) else "Disabled"
        dj_info = f"<@&{settings.dj_role_id}>" if (settings and settings.dj_role_id) else "None"

        embed = EmbedBuilder.base(
            title=f"🎶 Music Settings • {ctx.guild.name}",
            description="Persistent audio preferences configured for this guild.",
            color=0x9D4EDD,
        )
        embed.add_field(name="Default Volume", value=f"`{default_vol}%`", inline=True)
        embed.add_field(name="Queue Capacity", value=f"`{max_q}`", inline=True)
        embed.add_field(name="Default Loop Mode", value=f"`{loop}`", inline=True)
        embed.add_field(name="24/7 Mode", value=f"`{twenty_four_seven}`", inline=True)
        embed.add_field(name="DJ Role", value=dj_info, inline=True)

        await ctx.reply(embed=embed)

    @commands.command(name="musicsettings", help="View current server music settings.")
    async def musicsettings_prefix(self, ctx: commands.Context) -> None:
        await self._execute_musicsettings(UnifiedContext.from_prefix(ctx))

    @music.command(name="settings", description="View server music configuration settings.")
    async def musicsettings_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_musicsettings(UnifiedContext.from_interaction(interaction))


async def setup(bot: DeathBot) -> None:
    """Setup hook to register cog."""
    await bot.add_cog(Music(bot))
