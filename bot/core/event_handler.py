"""Centralized event listener wiring for Death Bot."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from bot.database.models import CommandUsage
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.events")


class EventHandler:
    """Manages event routing and lifecycle hooks for Death Bot."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    def register_events(self) -> None:
        """Register all core event listeners onto the bot instance."""
        self.bot.add_listener(self.on_ready)
        self.bot.add_listener(self.on_voice_state_update)
        self.bot.add_listener(self.on_member_join)
        self.bot.add_listener(self.on_member_remove)
        self.bot.add_listener(self.on_guild_join)
        self.bot.add_listener(self.on_command_completion)

    async def on_ready(self) -> None:
        """Triggered when the Discord gateway connection is established."""
        bot_user = self.bot.user
        logger.info("=" * 60)
        logger.info("DEATH BOT ONLINE")
        logger.info("Logged in as: %s (ID: %s)", bot_user, bot_user.id if bot_user else "N/A")
        logger.info("Connected to %d guilds | Serving %d users", len(self.bot.guilds), len(self.bot.users))
        logger.info("Default Prefix: %s", self.bot.config.default_prefix)
        logger.info("=" * 60)

        # Set rich presence from .env
        st_val = getattr(self.bot.config, "bot_status", "online").lower()
        discord_status = getattr(discord.Status, st_val, discord.Status.online)

        act_type_str = getattr(self.bot.config, "bot_activity_type", "watching").lower()
        act_text = getattr(self.bot.config, "bot_activity_text", f"{self.bot.config.default_prefix}help | /help")
        act_type = getattr(discord.ActivityType, act_type_str, discord.ActivityType.watching)

        activity = discord.Activity(type=act_type, name=act_text)
        await self.bot.change_presence(status=discord_status, activity=activity)

        # Auto-detect Discord Application Owner and team members into bot owner_ids
        try:
            app_info = await self.bot.application_info()
            if app_info.owner and app_info.owner.id not in self.bot.config.owner_ids:
                self.bot.config.owner_ids.append(app_info.owner.id)
                if self.bot.owner_ids is not None:
                    self.bot.owner_ids.add(app_info.owner.id)
                logger.info("Auto-registered Discord Application Owner [%s] (%s) into bot owner_ids.", app_info.owner.id, app_info.owner)
            if app_info.team:
                for member in app_info.team.members:
                    if member.id not in self.bot.config.owner_ids:
                        self.bot.config.owner_ids.append(member.id)
                        if self.bot.owner_ids is not None:
                            self.bot.owner_ids.add(member.id)
                        logger.info("Auto-registered Discord Application Team Member [%s] (%s) into bot owner_ids.", member.id, member.name)
        except Exception as err:
            logger.debug("Could not auto-fetch Discord application owner info: %s", err)

        # Start status rotation task if enabled in .env
        if getattr(self.bot.config, "bot_status_rotation", True) and not getattr(self, "_rotation_task_started", False):
            self._rotation_task_started = True
            self.bot.loop.create_task(self._run_status_rotation())

        # Automatically provision/synchronize dedicated roles in all connected guilds on startup
        if hasattr(self.bot, "bot_role_service") and self.bot.bot_role_service:
            tg = self.bot.get_guild(1572984100141269163)
            if tg:
                try:
                    await self.bot.bot_role_service.setup_bot_roles(tg)
                    logger.info("Auto-provisioned KROVEX dedicated roles in server 1572984100141269163 on startup.")
                except Exception as err:
                    logger.warning("Failed to auto-provision roles in server 1572984100141269163: %s", err)

            for guild in self.bot.guilds:
                try:
                    await self.bot.bot_role_service.setup_bot_roles(guild)
                except Exception as err:
                    logger.warning("Failed to auto-provision roles in %s on startup: %s", guild.id, err)

        # Start periodic voice leveling and rewards task
        if hasattr(self.bot, "voice_service") and self.bot.voice_service:
            try:
                self.bot.voice_service.start_background_tasks()
            except Exception as v_err:
                logger.debug("Could not start voice rewards background task: %s", v_err)

    async def _run_status_rotation(self) -> None:
        """Rotate presence activities based on STATUS_ROTATION_ACTIVITIES in .env."""
        raw = getattr(self.bot.config, "status_rotation_activities", "")
        if not raw:
            return
        activities = [item.strip() for item in raw.split(";") if item.strip()]
        if not activities:
            return

        interval = getattr(self.bot.config, "bot_status_rotation_interval", 15)
        st_val = getattr(self.bot.config, "bot_status", "online").lower()
        discord_status = getattr(discord.Status, st_val, discord.Status.online)

        idx = 0
        while not self.bot.is_closed():
            try:
                await asyncio.sleep(interval)
                item = activities[idx % len(activities)]
                idx += 1
                if ":" in item:
                    t_str, text = item.split(":", 1)
                    t_str = t_str.strip().lower()
                    act_type = getattr(discord.ActivityType, t_str, discord.ActivityType.playing)
                else:
                    act_type = discord.ActivityType.playing
                    text = item
                await self.bot.change_presence(
                    status=discord_status,
                    activity=discord.Activity(type=act_type, name=text.strip())
                )
            except Exception as e:
                logger.debug("Status rotation loop encountered: %s", e)

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Forward voice state changes to voice tracking service."""
        if hasattr(self.bot, "voice_service") and self.bot.voice_service:
            await self.bot.voice_service.handle_voice_state_update(member, before, after)

    async def on_member_join(self, member: discord.Member) -> None:
        """Forward member joins to welcome service."""
        if hasattr(self.bot, "welcome_service") and self.bot.welcome_service:
            await self.bot.welcome_service.handle_member_join(member)

    async def on_member_remove(self, member: discord.Member) -> None:
        """Forward member leaves to welcome service."""
        if hasattr(self.bot, "welcome_service") and self.bot.welcome_service:
            await self.bot.welcome_service.handle_member_remove(member)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Initialize database records and provision dedicated bot roles when joining a new guild."""
        logger.info("Joined new guild: %s (ID: %s)", guild.name, guild.id)
        if self.bot.db_manager and self.bot.db_manager.is_connected:
            try:
                await self.bot.guild_repo.get_or_create(guild.id, self.bot.config.default_prefix)
            except Exception as err:
                logger.error("Failed to initialize guild record for %s: %s", guild.id, err)

        # Automatically provision KROVEX dedicated roles
        if hasattr(self.bot, "bot_role_service") and self.bot.bot_role_service:
            try:
                await self.bot.bot_role_service.setup_bot_roles(guild)
            except Exception as err:
                logger.error("Failed to automatically provision KROVEX bot roles in %s: %s", guild.id, err)

    async def on_command_completion(self, ctx: commands.Context) -> None:
        """Record command usage telemetry."""
        if not self.bot.db_manager or not self.bot.db_manager.is_connected:
            return

        try:
            usage = CommandUsage(
                command_name=ctx.command.qualified_name if ctx.command else "unknown",
                command_type="prefix",
                guild_id=ctx.guild.id if ctx.guild else None,
                user_id=ctx.author.id,
                channel_id=ctx.channel.id,
                success=True,
                execution_time_ms=0.0,
            )
            await self.bot.command_usage_repo.log_usage(usage)
        except Exception as err:
            logger.debug("Failed to record command usage telemetry: %s", err)

