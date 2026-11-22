"""Interactive Discord UI components, buttons, and views for the Death Bot music engine."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, List, Optional

import discord

from bot.services.music.source import AudioFilter, AudioSourceInfo, LoopMode, PlayerState, Track
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.services.music.player import GuildAudioPlayer

logger = get_logger("death_bot.music.views")


class MusicPlayerView(discord.ui.View):
    """Interactive control board attached to the active guild music player embed."""

    def __init__(self, player: GuildAudioPlayer, timeout: Optional[float] = None) -> None:
        super().__init__(timeout=timeout)
        self.player = player
        self._update_button_states()

    def _update_button_states(self) -> None:
        """Synchronize button labels and colors with current player state."""
        # 1. Play/Pause button
        is_paused = self.player.state == PlayerState.PAUSED
        self.btn_pause_resume.emoji = "▶️" if is_paused else "⏸️"
        self.btn_pause_resume.style = discord.ButtonStyle.green if is_paused else discord.ButtonStyle.secondary

        # 2. Loop button
        loop_mode = self.player.loop_mode
        if loop_mode == LoopMode.TRACK:
            self.btn_loop.label = "🔂 Track"
            self.btn_loop.style = discord.ButtonStyle.primary
        elif loop_mode == LoopMode.QUEUE:
            self.btn_loop.label = "🔁 Queue"
            self.btn_loop.style = discord.ButtonStyle.primary
        else:
            self.btn_loop.label = "🔁 Loop"
            self.btn_loop.style = discord.ButtonStyle.secondary

        # 3. Autoplay button
        self.btn_autoplay.style = discord.ButtonStyle.primary if self.player.autoplay else discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure invoker is in the same voice channel and has permission."""
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} Commands can only be used in servers.", ephemeral=True)
            return False

        user_voice = interaction.user.voice
        bot_voice = interaction.guild.voice_client if interaction.guild else None

        if not user_voice or not user_voice.channel:
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} You must be connected to a voice channel to use player controls.", ephemeral=True)
            return False

        if bot_voice and bot_voice.channel and user_voice.channel.id != bot_voice.channel.id:
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} You must be in the same voice channel as Death Bot.", ephemeral=True)
            return False

        # DJ check
        has_perm, reason = await self.player.can_control(interaction.user)
        if not has_perm:
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} {reason}", ephemeral=True)
            return False

        return True

    # --------------------------------------------------------------------------
    # Interactive Buttons (10 Controls)
    # --------------------------------------------------------------------------

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Previous Track"""
        success = await self.player.play_previous()
        if success:
            await interaction.response.send_message("⏮️ Returning to previous track...", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ No previous track history available.", ephemeral=True)

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Pause / Resume toggle"""
        if self.player.state == PlayerState.PAUSED:
            await self.player.resume()
            await interaction.response.send_message("▶️ Playback resumed.", ephemeral=True)
        else:
            await self.player.pause()
            await interaction.response.send_message("⏸️ Playback paused.", ephemeral=True)
        self._update_button_states()
        await self.player.update_player_message()

    @discord.ui.button(emoji=KrovexEmoji.PURPLE_ARROW.partial, style=discord.ButtonStyle.secondary, row=0)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Skip Track"""
        skipped = await self.player.skip()
        if skipped:
            await interaction.response.send_message(f"⏭️ Skipped **{skipped.title}**.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ No track currently playing to skip.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Stop Playback and Clear Queue"""
        await self.player.stop()
        await interaction.response.send_message("⏹️ Playback stopped and queue cleared.", ephemeral=True)

    @discord.ui.button(label="🔁 Loop", style=discord.ButtonStyle.secondary, row=0)
    async def btn_loop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Cycle Loop Mode (Off -> Track -> Queue -> Off)"""
        current = self.player.loop_mode
        if current == LoopMode.OFF:
            new_mode = self.player.set_loop_mode(LoopMode.TRACK)
        elif current == LoopMode.TRACK:
            new_mode = self.player.set_loop_mode(LoopMode.QUEUE)
        else:
            new_mode = self.player.set_loop_mode(LoopMode.OFF)

        self._update_button_states()
        await self.player.update_player_message()
        await interaction.response.send_message(f"🔁 Loop mode set to: **{new_mode.value.upper()}**", ephemeral=True)

    @discord.ui.button(emoji="🔀", label="Shuffle", style=discord.ButtonStyle.secondary, row=1)
    async def btn_shuffle(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Shuffle Queue"""
        count = self.player.shuffle()
        await interaction.response.send_message(f"🔀 Shuffled **{count}** tracks in the queue.", ephemeral=True)

    @discord.ui.button(emoji="🔉", label="-10%", style=discord.ButtonStyle.secondary, row=1)
    async def btn_vol_down(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Volume Down"""
        new_vol = self.player.set_volume(self.player.volume - 10)
        await self.player.update_player_message()
        await interaction.response.send_message(f"🔉 Volume reduced to **{new_vol}%**.", ephemeral=True)

    @discord.ui.button(emoji="🔊", label="+10%", style=discord.ButtonStyle.secondary, row=1)
    async def btn_vol_up(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Volume Up"""
        new_vol = self.player.set_volume(self.player.volume + 10)
        await self.player.update_player_message()
        await interaction.response.send_message(f"🔊 Volume increased to **{new_vol}%**.", ephemeral=True)

    @discord.ui.button(emoji="📜", label="Queue", style=discord.ButtonStyle.secondary, row=1)
    async def btn_queue(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Inspect Queue"""
        embed = self.player.build_queue_embed(page=1)
        view = PaginatedQueueView(self.player)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(emoji="♾️", label="Autoplay", style=discord.ButtonStyle.secondary, row=1)
    async def btn_autoplay(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Toggle Autoplay"""
        enabled = self.player.toggle_autoplay()
        self._update_button_states()
        await self.player.update_player_message()
        status = "ENABLED" if enabled else "DISABLED"
        await interaction.response.send_message(f"♾️ Autoplay recommendations **{status}**.", ephemeral=True)


class SongSelectView(discord.ui.View):
    """Interactive select menu presented when search candidates have close confidence scores."""

    def __init__(self, candidates: List[AudioSourceInfo], user_id: int, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.candidates = candidates[:10]  # Max 10 select options
        self.user_id = user_id
        self.selected_candidate: Optional[AudioSourceInfo] = None

        options = [
            discord.SelectOption(
                label=c.title[:100],
                description=f"{c.uploader} • {c.formatted_duration}"[:100],
                value=str(idx),
                emoji="🎵",
            )
            for idx, c in enumerate(self.candidates)
        ]

        self.select_menu = discord.ui.Select(
            placeholder="Select a track to play...",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.select_menu.callback = self._on_select
        self.add_item(self.select_menu)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Only the person who searched can choose a track.", ephemeral=True)
            return

        idx = int(self.select_menu.values[0])
        self.selected_candidate = self.candidates[idx]
        self.stop()
        await interaction.response.defer()

    async def on_timeout(self) -> None:
        self.stop()


class PaginatedQueueView(discord.ui.View):
    """Interactive pagination view for browsing large queues."""

    def __init__(self, player: GuildAudioPlayer, current_page: int = 1, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.player = player
        self.current_page = current_page
        self._update_buttons()

    def _total_pages(self) -> int:
        return max(1, math.ceil(len(self.player.queue) / 10))

    def _update_buttons(self) -> None:
        total = self._total_pages()
        self.btn_prev.disabled = self.current_page <= 1
        self.btn_next.disabled = self.current_page >= total

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.current_page = max(1, self.current_page - 1)
        self._update_buttons()
        embed = self.player.build_queue_embed(page=self.current_page)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.current_page = min(self._total_pages(), self.current_page + 1)
        self._update_buttons()
        embed = self.player.build_queue_embed(page=self.current_page)
        await interaction.response.edit_message(embed=embed, view=self)

