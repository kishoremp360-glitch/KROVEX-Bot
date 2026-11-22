"""KROVEX Temporary Voice Actions & Scheduled Reversion Engine.

Supports timed server mutes, timed server deafens, and timed channel locks
(1m, 5m, 10m, 30m, or custom duration) with automatic background reversion
and persistence across bot restarts.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import discord

from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.ownervc.temp_actions")


class TemporaryActionsEngine:
    """Manages scheduled expirations for temporary voice and channel restrictions."""

    def __init__(self, bot: "DeathBot") -> None:
        self.bot = bot
        self._loop_task: Optional[asyncio.Task] = None
        self._is_running: bool = False

    def start(self) -> None:
        """Start the background audit loop."""
        if not self._is_running:
            self._is_running = True
            self._loop_task = asyncio.create_task(self._reversion_worker())
            logger.info("TemporaryActionsEngine background worker initialized.")

    def stop(self) -> None:
        """Halt the background audit loop."""
        self._is_running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            self._loop_task = None

    async def schedule_temp_mute(
        self,
        guild_id: int,
        member: discord.Member,
        duration_seconds: int,
        executor_id: int,
    ) -> int:
        """Apply server mute and record temporary expiration."""
        expires_at = time.time() + duration_seconds
        await member.edit(mute=True, reason=f"KROVEX Temp Mute ({duration_seconds}s)")
        revert_data = json.dumps({"action": "unmute", "channel_id": getattr(member.voice, "channel", None) and member.voice.channel.id})
        
        if self.bot.vc_repo:
            return await self.bot.vc_repo.save_temp_action(
                guild_id=guild_id,
                action_type="temp_mute",
                target_id=member.id,
                revert_data=revert_data,
                expires_at=expires_at,
                created_by=executor_id,
            )
        return 0

    async def schedule_temp_deafen(
        self,
        guild_id: int,
        member: discord.Member,
        duration_seconds: int,
        executor_id: int,
    ) -> int:
        """Apply server deafen and record temporary expiration."""
        expires_at = time.time() + duration_seconds
        await member.edit(deafen=True, reason=f"KROVEX Temp Deafen ({duration_seconds}s)")
        revert_data = json.dumps({"action": "undeafen", "channel_id": getattr(member.voice, "channel", None) and member.voice.channel.id})

        if self.bot.vc_repo:
            return await self.bot.vc_repo.save_temp_action(
                guild_id=guild_id,
                action_type="temp_deafen",
                target_id=member.id,
                revert_data=revert_data,
                expires_at=expires_at,
                created_by=executor_id,
            )
        return 0

    async def schedule_temp_lock(
        self,
        guild_id: int,
        channel: discord.VoiceChannel,
        duration_seconds: int,
        executor_id: int,
    ) -> int:
        """Apply connect=False overwrite and record temporary expiration."""
        expires_at = time.time() + duration_seconds
        
        # Save previous overwrite state for @everyone before modifying
        default_role = channel.guild.default_role
        prev_overwrite = channel.overwrites_for(default_role)
        prev_connect = prev_overwrite.connect

        await channel.set_permissions(default_role, connect=False, reason=f"KROVEX Temp Lock ({duration_seconds}s)")
        revert_data = json.dumps({"action": "restore_lock", "prev_connect": prev_connect})

        if self.bot.vc_repo:
            return await self.bot.vc_repo.save_temp_action(
                guild_id=guild_id,
                action_type="temp_lock",
                target_id=channel.id,
                revert_data=revert_data,
                expires_at=expires_at,
                created_by=executor_id,
            )
        return 0

    async def _reversion_worker(self) -> None:
        """Periodically scans active temporary records and reverts expired items."""
        while self._is_running:
            try:
                await asyncio.sleep(5)  # Scan every 5 seconds
                if not hasattr(self.bot, "vc_repo") or not self.bot.vc_repo:
                    continue

                active_actions = await self.bot.vc_repo.get_active_temp_actions()
                now = time.time()

                for record in active_actions:
                    expires_at = record.get("expires_at", 0)
                    if now < expires_at:
                        continue  # Not expired yet

                    action_id = record["id"]
                    guild_id = record["guild_id"]
                    action_type = record["action_type"]
                    target_id = record["target_id"]
                    revert_raw = record.get("revert_data", "{}")

                    try:
                        revert_data = json.loads(revert_raw)
                    except Exception:
                        revert_data = {}

                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        # Deactivate invalid guild record
                        await self.bot.vc_repo.deactivate_temp_action(action_id)
                        continue

                    # Execute reversion
                    try:
                        if action_type == "temp_mute":
                            member = guild.get_member(target_id)
                            if member and member.voice and member.voice.mute:
                                await member.edit(mute=False, reason="KROVEX Temp Mute Expired")
                                logger.info("Auto-unmuted member %s in guild %s", target_id, guild_id)

                        elif action_type == "temp_deafen":
                            member = guild.get_member(target_id)
                            if member and member.voice and member.voice.deaf:
                                await member.edit(deafen=False, reason="KROVEX Temp Deafen Expired")
                                logger.info("Auto-undeafened member %s in guild %s", target_id, guild_id)

                        elif action_type == "temp_lock":
                            channel = guild.get_channel(target_id)
                            if isinstance(channel, discord.VoiceChannel):
                                prev_connect = revert_data.get("prev_connect", None)
                                await channel.set_permissions(
                                    guild.default_role,
                                    connect=prev_connect,
                                    reason="KROVEX Temp Lock Expired",
                                )
                                logger.info("Auto-unlocked voice channel %s in guild %s", target_id, guild_id)

                    except discord.Forbidden:
                        logger.warning("Forbidden while auto-reverting action %s in guild %s", action_id, guild_id)
                    except Exception as rev_err:
                        logger.warning("Error auto-reverting action %s: %s", action_id, rev_err)

                    # Mark record inactive
                    await self.bot.vc_repo.deactivate_temp_action(action_id)

            except asyncio.CancelledError:
                break
            except Exception as loop_err:
                logger.error("Error in TemporaryActionsEngine worker loop: %s", loop_err)
                await asyncio.sleep(5)


async def setup(bot: "DeathBot") -> None:
    """Extension discovery hook."""
    pass

