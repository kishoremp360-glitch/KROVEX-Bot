"""Voice activity tracking and live channel status service for Death Bot.

Handles voice state events, session persistence, live channel statistics, and
throttled updates to avoid Discord API rate-limiting.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

import discord

from bot.database.repositories import VoiceRepository
from bot.utils.embeds import EmbedBuilder
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.services.voice")


class VoiceService:
    """Service tracking real-time voice channel activity and managing throttled status embeds."""

    def __init__(self, bot: DeathBot, voice_repo: VoiceRepository) -> None:
        self.bot = bot
        self.repo = voice_repo
        # Active in-memory sessions: (guild_id, user_id) -> joined_at
        self._active_sessions: Dict[Tuple[int, int], datetime] = {}
        # Rate-limiting tracker: guild_id -> last_status_update_timestamp
        self._last_status_updates: Dict[int, float] = {}
        # Dynamic Join-to-Create lock tracker
        self._hub_locks: Dict[Tuple[int, int], asyncio.Lock] = {}
        # Anti-Soundboard spam tracker: (guild_id, user_id) -> list of timestamp floats
        self._soundboard_tracker: Dict[Tuple[int, int], List[float]] = {}
        # Mute/deafen evasion tracker: (guild_id, user_id) -> state dict
        self._evasion_watch: Dict[Tuple[int, int], Dict[str, Any]] = {}
        # Periodic background leveling task handle
        self._rewards_task: Optional[asyncio.Task] = None

    def get_active_voice_count(self, guild: discord.Guild) -> int:
        """Count total non-bot members connected to voice channels in a guild."""
        total = 0
        for vc in guild.voice_channels:
            total += sum(1 for m in vc.members if not m.bot)
        return total

    def get_voice_channels_summary(self, guild: discord.Guild) -> List[Dict[str, Any]]:
        """Generate structured breakdown of voice channels and their occupants."""
        summary = []
        for vc in guild.voice_channels:
            members = [m for m in vc.members if not m.bot]
            if members:
                summary.append({
                    "channel_id": vc.id,
                    "channel_name": vc.name,
                    "member_count": len(members),
                    "members": [m.display_name for m in members],
                })
        return summary

    async def handle_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Process Discord on_voice_state_update events efficiently."""
        if member.bot:
            return

        guild = member.guild
        afk_channel = guild.afk_channel
        key = (guild.id, member.id)
        now = datetime.now(timezone.utc)

        is_before_active = before.channel is not None and before.channel != afk_channel
        is_after_active = after.channel is not None and after.channel != afk_channel

        # 1. Member joined an active voice channel (was not in active voice before)
        if not is_before_active and is_after_active and after.channel is not None:
            self._active_sessions[key] = now
            try:
                await self.repo.start_session(guild.id, member.id, after.channel.id)
                logger.debug("Voice session started: %s in %s (%s)", member, after.channel.name, guild.name)
            except Exception as err:
                logger.error("Failed to record voice session start: %s", err)

            # AutoMod Voice Mute/Deafen Evasion Guard
            evasion_rec = self._evasion_watch.pop(key, None)
            if evasion_rec and (now.timestamp() - evasion_rec.get("timestamp", 0) < 30.0):
                try:
                    if guild.me and guild.me.guild_permissions.mute_members:
                        await member.edit(
                            mute=evasion_rec.get("was_muted", False),
                            deafen=evasion_rec.get("was_deafened", False),
                            reason="KROVEX Voice AutoMod: Mute/Deafen Evasion Prevention",
                        )
                        logger.info("Enforced voice evasion protection on %s in %s", member, guild.name)
                except Exception as ev_err:
                    logger.debug("Could not re-apply voice evasion mute/deafen: %s", ev_err)

            # Join-to-Create Dynamic Room Generation
            if isinstance(after.channel, discord.VoiceChannel):
                await self._handle_join_to_create(member, after.channel)

        # 2. Member left active voice (disconnected or moved to AFK)
        elif is_before_active and not is_after_active:
            self._active_sessions.pop(key, None)
            try:
                session = await self.repo.end_session(guild.id, member.id)
                if session and before.channel:
                    logger.debug(
                        "Voice session ended: %s from %s (Duration: %ss)",
                        member,
                        before.channel.name,
                        session.duration_seconds,
                    )
            except Exception as err:
                logger.error("Failed to record voice session end: %s", err)

            # Record state if member left while server-muted or server-deafened (evasion watch)
            if getattr(before, "mute", False) or getattr(before, "deaf", False):
                self._evasion_watch[key] = {
                    "was_muted": bool(before.mute),
                    "was_deafened": bool(before.deaf),
                    "timestamp": now.timestamp(),
                }

            if isinstance(before.channel, discord.VoiceChannel):
                await self._check_and_cleanup_temp_channel(before.channel)

        # 3. Member switched between two active channels
        elif is_before_active and is_after_active and before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            try:
                await self.repo.end_session(guild.id, member.id)
                await self.repo.start_session(guild.id, member.id, after.channel.id)
                self._active_sessions[key] = now
                logger.debug("Voice session switched: %s from %s to %s", member, before.channel.name, after.channel.name)
            except Exception as err:
                logger.error("Failed to record voice channel switch: %s", err)

            if isinstance(before.channel, discord.VoiceChannel):
                await self._check_and_cleanup_temp_channel(before.channel)

            # Check Join-to-Create on the new destination channel
            if isinstance(after.channel, discord.VoiceChannel):
                await self._handle_join_to_create(member, after.channel)

        # Trigger throttled status embed refresh
        await self.schedule_status_refresh(guild)

    def _is_hub_channel(self, channel: discord.VoiceChannel) -> bool:
        """Determine if a channel is a designated Join-to-Create hub channel."""
        name = getattr(channel, "name", "").lower()
        return "➕" in name or "join to create" in name or "[+]" in name or "join-to-create" in name

    async def _handle_join_to_create(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
    ) -> Optional[discord.VoiceChannel]:
        """Automatically create a dynamic temporary voice room and move the user into it."""
        if not self._is_hub_channel(channel):
            return None

        guild = member.guild
        me = getattr(guild, "me", None)
        if not me:
            return None

        # Lock per member to avoid race conditions on rapid re-joins
        key = (guild.id, member.id)
        if key not in self._hub_locks:
            self._hub_locks[key] = asyncio.Lock()

        async with self._hub_locks[key]:
            # Verify member is still inside the hub voice channel
            if not getattr(member, "voice", None) or member.voice.channel != channel:
                return None

            room_name = f"🔊・{member.display_name}'s Room"
            category = getattr(channel, "category", None)
            bitrate = min(getattr(channel, "bitrate", 64000), 96000)

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(connect=True, speak=True),
                member: discord.PermissionOverwrite(
                    manage_channels=True,
                    move_members=True,
                    mute_members=True,
                    deafen_members=True,
                    connect=True,
                    speak=True,
                    stream=True,
                ),
            }

            try:
                new_vc = await guild.create_voice_channel(
                    name=room_name,
                    category=category,
                    bitrate=bitrate,
                    overwrites=overwrites,
                    reason=f"KROVEX Auto-VC: Dynamic room created for {member} ({member.id})",
                )
                await member.move_to(new_vc, reason="KROVEX Auto-VC: Move to dynamic room")

                vc_repo = getattr(self.bot, "vc_repo", None)
                if vc_repo:
                    await vc_repo.register_temp_channel(guild.id, new_vc.id, member.id)

                # Send interactive OwnerVC dashboard directly into the new VC's text channel
                try:
                    from bot.cogs.ownervc.dashboard import OwnerVCControlView, build_owner_vc_embed
                    view = OwnerVCControlView(self.bot, new_vc)
                    embed = build_owner_vc_embed(new_vc)
                    await new_vc.send(embed=embed, view=view)
                except Exception as dash_err:
                    logger.debug("Could not send dashboard to VC text channel: %s", dash_err)

                logger.info("Created Auto-VC room #%s for %s in %s", new_vc.name, member, guild.name)
                return new_vc
            except Exception as err:
                logger.error("Failed to create Auto-VC room for %s: %s", member, err, exc_info=True)
                return None

    async def record_soundboard_event(self, member: discord.Member, channel: discord.VoiceChannel) -> bool:
        """Track soundboard triggers and apply automated sanctions if spammed (>3 in 5s)."""
        key = (member.guild.id, member.id)
        now_ts = asyncio.get_event_loop().time()
        stamps = self._soundboard_tracker.setdefault(key, [])
        stamps.append(now_ts)
        self._soundboard_tracker[key] = [t for t in stamps if now_ts - t <= 5.0]

        if len(self._soundboard_tracker[key]) >= 3:
            try:
                if member.guild.me and member.guild.me.guild_permissions.mute_members:
                    await member.edit(mute=True, reason="KROVEX Voice AutoMod: Anti-Soundboard Spam Throttling")
                    logger.info("Muted %s for soundboard spam in %s", member, member.guild.name)

                vc_repo = getattr(self.bot, "vc_repo", None)
                if vc_repo:
                    await vc_repo.log_action(
                        guild_id=member.guild.id,
                        executor_id=getattr(self.bot.user, "id", 0) if self.bot.user else 0,
                        action_type="soundboard_spam_mute",
                        scope="single_member",
                        source_channel_id=channel.id,
                        destination_channel_id=None,
                        target_count=1,
                        success_count=1,
                        fail_count=0,
                        details=f"Muted {member.display_name} for soundboard spam",
                    )
                return True
            except Exception as err:
                logger.warning("Could not apply soundboard spam sanction to %s: %s", member, err)
        return False

    def start_background_tasks(self) -> None:
        """Start the periodic voice leveling and rewards task."""
        if self._rewards_task is None or self._rewards_task.done():
            loop = getattr(self.bot, "loop", None) or asyncio.get_event_loop()
            self._rewards_task = loop.create_task(self._run_voice_rewards_loop())

    async def _run_voice_rewards_loop(self) -> None:
        """Periodic background worker awarding XP and coins for active un-deafened voice time."""
        while not self.bot.is_closed():
            try:
                await asyncio.sleep(60)
                economy_repo = getattr(self.bot, "economy_repo", None)
                if not economy_repo:
                    continue

                for guild in getattr(self.bot, "guilds", []):
                    afk_ch = getattr(guild, "afk_channel", None)
                    for vc in getattr(guild, "voice_channels", []):
                        if afk_ch and vc.id == afk_ch.id:
                            continue

                        # Anti-farming: Must have at least 2 non-bot members
                        non_bots = [m for m in getattr(vc, "members", []) if not getattr(m, "bot", False)]
                        if len(non_bots) < 2:
                            continue

                        for m in non_bots:
                            # Anti-farming: Must not be muted or deafened
                            vs = getattr(m, "voice", None)
                            if not vs:
                                continue
                            if getattr(vs, "mute", False) or getattr(vs, "self_mute", False) or getattr(vs, "deaf", False) or getattr(vs, "self_deaf", False):
                                continue

                            try:
                                await economy_repo.add_balance(guild.id, m.id, wallet=5, bank=0)
                                await economy_repo.add_xp(guild.id, m.id, xp=15)
                            except Exception as r_err:
                                logger.debug("Failed awarding voice reward to %s: %s", m.id, r_err)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Error in voice rewards loop: %s", e)

    async def _check_and_cleanup_temp_channel(self, channel: Optional[discord.VoiceChannel]) -> None:
        """Automatically delete an empty temporary voice channel."""
        if not channel or not isinstance(channel, discord.VoiceChannel):
            return
        if any(not m.bot for m in channel.members):
            return
        vc_repo = getattr(self.bot, "vc_repo", None)
        if not vc_repo:
            return
        try:
            if await vc_repo.is_temp_channel(channel.guild.id, channel.id):
                await vc_repo.remove_temp_channel(channel.guild.id, channel.id)
                await channel.delete(reason="Automatic cleanup of empty temporary voice channel")
                logger.info("Cleaned up empty temporary voice channel #%s (%s) in %s", channel.name, channel.id, channel.guild.name)
        except Exception as err:
            logger.warning("Could not auto-cleanup temporary voice channel #%s: %s", getattr(channel, "name", channel.id), err)

    async def schedule_status_refresh(self, guild: discord.Guild) -> None:
        """Refresh live status embed if enabled and interval has elapsed."""
        try:
            settings = await self.repo.get_or_create_settings(guild.id)
            if not settings.enabled or not settings.status_channel_id or not settings.status_message_id:
                return

            now_ts = asyncio.get_event_loop().time()
            last_ts = self._last_status_updates.get(guild.id, 0.0)

            # Throttle updates according to configured interval
            if now_ts - last_ts < settings.update_interval:
                return

            self._last_status_updates[guild.id] = now_ts
            channel = guild.get_channel(settings.status_channel_id)
            if not isinstance(channel, discord.TextChannel):
                return

            try:
                message = await channel.fetch_message(settings.status_message_id)
            except (discord.NotFound, discord.Forbidden):
                return

            embed = self.build_status_embed(guild)
            await message.edit(embed=embed)
        except Exception as err:
            logger.error("Error refreshing voice status embed for guild %s: %s", guild.id, err)

    def build_status_embed(self, guild: discord.Guild) -> discord.Embed:
        """Construct the live neon-themed voice status embed."""
        total_voice_members = self.get_active_voice_count(guild)
        summary = self.get_voice_channels_summary(guild)

        embed = EmbedBuilder.base(
            title=f"🎙️ Live Voice Status • {guild.name}",
            description=f"Currently **{total_voice_members}** member(s) connected to voice channels.",
            color=0x9D4EDD,
            footer_text="Death Bot Voice Tracker • Auto-refreshed",
        )

        if summary:
            for item in summary[:10]:  # Limit to 10 channels to avoid embed size limit
                names = ", ".join(item["members"])
                embed.add_field(
                    name=f"🔊 {item['channel_name']} ({item['member_count']})",
                    value=names[:1024] if names else "Empty",
                    inline=False,
                )
        else:
            embed.add_field(
                name="Channels Status",
                value="*No active voice activity detected at the moment.*",
                inline=False,
            )

        return embed

