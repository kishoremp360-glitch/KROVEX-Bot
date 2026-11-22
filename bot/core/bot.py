"""Core bot class for Death Bot, subclassing AutoShardedBot with modular architecture."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.config import BotConfig
from bot.core.error_handler import GlobalErrorHandler
from bot.core.event_handler import EventHandler
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories import (
    CustomCommandRepository,
    SoulRepository,
    AutomodRepository,
    CommandUsageRepository,
    GuildRepository,
    InviteRepository,
    LevelRepository,
    ModerationRepository,
    MusicRepository,
    PlaylistRepository,
    SecurityRepository,
    TicketRepository,
    UserRepository,
    VCRepository,
    VoiceRepository,
    WelcomeRepository,
    ReactionRoleRepository,
    ServerAdminRepository,
    LoggingRepository,
    EconomyRepository,
    ShopRepository,
    MinigameRepository,
    MimicRepository,
    MentionSettingsRepository,
)
from bot.services.ai import GeminiProvider, SoulService
from bot.services.custom_command_service import CustomCommandService
from bot.services.music_service import MusicService
from bot.services.voice_service import VoiceService
from bot.services.welcome_service import WelcomeService
from bot.utils.logger import get_logger

logger = get_logger("death_bot.core")


async def get_prefix(bot: DeathBot, message: discord.Message) -> List[str]:
    """Dynamically determine prefix per-guild or fallback to default."""
    prefixes = [bot.config.default_prefix] if bot.config.default_prefix else []
    for p in [".", "!"]:
        if p not in prefixes:
            prefixes.append(p)

    if message.guild and bot.db_manager and bot.db_manager.is_connected and bot.guild_repo:
        try:
            guild_p = await bot.guild_repo.get_prefix(message.guild.id, None)
            if guild_p and guild_p not in prefixes:
                prefixes.insert(0, guild_p)
        except Exception:
            pass

    if bot.user:
        return commands.when_mentioned_or(*prefixes)(bot, message)
    return prefixes


_bypass_applied = False


def _apply_bot_owner_universal_bypass() -> None:
    """Ensure configured Bot Owners bypass all command checks and permission requirements."""
    global _bypass_applied
    if _bypass_applied:
        return
    _bypass_applied = True

    _orig_cmd_can_run = commands.Command.can_run
    _orig_app_cmd_can_run = app_commands.Command._check_can_run
    _orig_context_menu_can_run = getattr(app_commands.ContextMenu, "_check_can_run", None)

    async def _cmd_can_run_bypass(self: commands.Command, ctx: commands.Context, /) -> bool:
        bot: Any = ctx.bot
        if bot:
            if hasattr(bot, "config") and (ctx.author.id in bot.config.owner_ids or str(ctx.author.id) in [str(x) for x in bot.config.owner_ids]):
                return True
            if hasattr(bot, "is_bot_owner") and callable(bot.is_bot_owner):
                try:
                    res = bot.is_bot_owner(ctx.author)
                    if asyncio.iscoroutine(res):
                        if await res:
                            return True
                    elif bool(res):
                        return True
                except Exception:
                    pass
        return await _orig_cmd_can_run(self, ctx)

    async def _app_cmd_can_run_bypass(self: app_commands.Command, interaction: discord.Interaction) -> bool:
        bot: Any = interaction.client
        if bot:
            if hasattr(bot, "config") and (interaction.user.id in bot.config.owner_ids or str(interaction.user.id) in [str(x) for x in bot.config.owner_ids]):
                return True
            if hasattr(bot, "is_bot_owner") and callable(bot.is_bot_owner):
                try:
                    res = bot.is_bot_owner(interaction.user)
                    if asyncio.iscoroutine(res):
                        if await res:
                            return True
                    elif bool(res):
                        return True
                except Exception:
                    pass
        return await _orig_app_cmd_can_run(self, interaction)

    commands.Command.can_run = _cmd_can_run_bypass
    app_commands.Command._check_can_run = _app_cmd_can_run_bypass

    if _orig_context_menu_can_run:
        async def _cm_can_run_bypass(self: app_commands.ContextMenu, interaction: discord.Interaction) -> bool:
            bot: Any = interaction.client
            if bot:
                if hasattr(bot, "config") and (interaction.user.id in bot.config.owner_ids or str(interaction.user.id) in [str(x) for x in bot.config.owner_ids]):
                    return True
                if hasattr(bot, "is_bot_owner") and callable(bot.is_bot_owner):
                    try:
                        res = bot.is_bot_owner(interaction.user)
                        if asyncio.iscoroutine(res):
                            if await res:
                                return True
                        elif bool(res):
                            return True
                    except Exception:
                        pass
            return await _orig_context_menu_can_run(self, interaction)

        app_commands.ContextMenu._check_can_run = _cm_can_run_bypass


class DeathBot(commands.AutoShardedBot):
    """Next-generation modular Discord bot engine."""

    def __init__(self, config: BotConfig, intents: Optional[discord.Intents] = None) -> None:
        self.config = config
        self.start_time: datetime = datetime.now(timezone.utc)
        self.session: Optional[aiohttp.ClientSession] = None

        # Database manager and repository containers
        self.db_manager: Optional[SQLiteDatabaseManager] = None
        self.guild_repo: Optional[GuildRepository] = None
        self.user_repo: Optional[UserRepository] = None
        self.voice_repo: Optional[VoiceRepository] = None
        self.welcome_repo: Optional[WelcomeRepository] = None
        self.music_repo: Optional[MusicRepository] = None
        self.command_usage_repo: Optional[CommandUsageRepository] = None
        self.moderation_repo: Optional[ModerationRepository] = None
        self.playlist_repo: Optional[PlaylistRepository] = None
        self.security_repo: Optional[SecurityRepository] = None
        self.automod_repo: Optional[AutomodRepository] = None
        self.invite_repo: Optional[InviteRepository] = None
        self.level_repo: Optional[LevelRepository] = None
        self.ticket_repo: Optional[TicketRepository] = None
        self.vc_repo: Optional[VCRepository] = None
        self.rr_repo: Optional[ReactionRoleRepository] = None
        self.admin_repo: Optional[ServerAdminRepository] = None
        self.logging_repo: Optional[LoggingRepository] = None
        self.economy_repo: Optional[EconomyRepository] = None
        self.shop_repo: Optional[ShopRepository] = None
        self.minigame_repo: Optional[MinigameRepository] = None
        self.mimic_repo: Optional[MimicRepository] = None
        self.mention_repo: Optional[MentionSettingsRepository] = None
        self.custom_command_repo: Optional[CustomCommandRepository] = None
        self.soul_repo: Optional[SoulRepository] = None

        # Core services
        self.custom_command_service: Optional[CustomCommandService] = None
        self.soul_provider: Optional[GeminiProvider] = None
        self.soul_service: Optional[SoulService] = None
        self.music_service: Optional[MusicService] = None
        self.voice_service: Optional[VoiceService] = None
        self.welcome_service: Optional[WelcomeService] = None
        self.dm_queue_service: Optional[Any] = None
        self.bot_role_service: Optional[Any] = None
        self.dashboard_server: Optional[Any] = None

        # Error and event handlers
        self.error_handler = GlobalErrorHandler(self)
        self.event_handler = EventHandler(self)

        # Discord Gateway Intents
        if intents is None:
            intents = discord.Intents.default()
            intents.members = True
            intents.message_content = True
            intents.voice_states = True
            intents.guilds = True

        super().__init__(
            command_prefix=get_prefix,
            intents=intents,
            help_command=None,  # Custom help command implemented in utility cog
            case_insensitive=True,
            owner_ids=set(config.owner_ids),
        )
        _apply_bot_owner_universal_bypass()

    @property
    def db(self) -> Optional[SQLiteDatabaseManager]:
        """Convenience alias for the central SQLiteDatabaseManager."""
        return self.db_manager

    @property
    def uptime_seconds(self) -> float:
        """Seconds elapsed since the bot started."""
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()

    async def setup_hook(self) -> None:
        """Asynchronous setup executed before gateway connection."""
        logger.info("Initializing Death Bot runtime services...")

        # 1. Initialize HTTP session
        self.session = aiohttp.ClientSession()

        # Explicitly ensure Opus codec is loaded for voice streaming
        if not discord.opus.is_loaded():
            try:
                discord.opus._load_default()
            except Exception as opus_err:
                logger.debug("Default opus loader skipped: %s", opus_err)
            if not discord.opus.is_loaded():
                for opus_lib in [
                    "libopus.so.0",
                    "libopus.so",
                    "opus",
                    "/usr/lib/x86_64-linux-gnu/libopus.so.0",
                    "/usr/lib/aarch64-linux-gnu/libopus.so.0",
                    "/usr/lib/libopus.so.0",
                ]:
                    try:
                        discord.opus.load_opus(opus_lib)
                        if discord.opus.is_loaded():
                            logger.info("Successfully loaded libopus via '%s'", opus_lib)
                            break
                    except Exception:
                        pass

        # 2. Initialize Database and Repositories
        await self._init_database()

        # 3. Initialize Services
        self.music_service = MusicService(bot=self)
        if self.voice_repo:
            self.voice_service = VoiceService(self, self.voice_repo)
        if self.welcome_repo:
            self.welcome_service = WelcomeService(self, self.welcome_repo)
        if hasattr(self, "custom_command_repo") and self.custom_command_repo:
            self.custom_command_service = CustomCommandService(self.custom_command_repo, bot=self)
        if hasattr(self, "soul_repo") and self.soul_repo:
            self.soul_provider = GeminiProvider(
                api_key=self.config.gemini_api_key,
                model=self.config.soul_model,
                session=self.session,
            )
            self.soul_service = SoulService(
                db=self.db_manager,
                repo=self.soul_repo,
                provider=self.soul_provider,
                timeout=self.config.soul_timeout,
                default_cooldown=self.config.soul_cooldown_seconds,
                bot=self,
            )
        try:
            await self.load_extension("bot.services.security_service")
            logger.info("Loaded SecurityService extension.")
        except Exception as e:
            logger.warning("Could not load SecurityService: %s", e)
        try:
            await self.load_extension("bot.services.automod_service")
            logger.info("Loaded AutoModService extension.")
        except Exception as e:
            logger.warning("Could not load AutoModService: %s", e)
        try:
            await self.load_extension("bot.services.dm_queue_service")
            logger.info("Loaded DMQueueService extension.")
        except Exception as e:
            logger.warning("Could not load DMQueueService: %s", e)
        try:
            await self.load_extension("bot.services.logging_service")
            logger.info("Loaded LoggingService extension.")
        except Exception as e:
            logger.warning("Could not load LoggingService: %s", e)
        try:
            await self.load_extension("bot.services.mention_service")
            logger.info("Loaded MentionService extension.")
        except Exception as e:
            logger.warning("Could not load MentionService: %s", e)
        try:
            await self.load_extension("bot.services.bot_role_service")
            logger.info("Loaded BotRoleService extension.")
        except Exception as e:
            logger.warning("Could not load BotRoleService: %s", e)

        # 4. Wire Global Error Handlers
        self.on_command_error = self.error_handler.handle_prefix_error
        self.tree.on_error = self.error_handler.handle_slash_error

        # 5. Register Event Listeners
        self.event_handler.register_events()

        # 6. Load Cogs dynamically
        await self.load_cogs()

        # 7. Sync Slash Commands
        if getattr(self.config, "sync_commands_on_startup", True):
            await self.sync_app_commands()
        else:
            logger.info("Startup slash command sync skipped per SYNC_COMMANDS_ON_STARTUP=false.")

        # 8. Initialize Dashboard Web Server (if enabled)
        if hasattr(self.config, "dashboard_enabled") and self.config.dashboard_enabled:
            await self._init_dashboard_server()

    async def _init_dashboard_server(self) -> None:
        """Initialize and launch the asynchronous dashboard web server."""
        try:
            from bot.dashboard.server import DashboardServer

            self.dashboard_server = DashboardServer(
                bot=self,
                host=self.config.dashboard_host,
                port=self.config.dashboard_port,
            )
            success = await self.dashboard_server.start()
            if not success:
                logger.warning(
                    "Dashboard web server failed to bind to %s:%s. Continuing without web server.",
                    self.config.dashboard_host,
                    self.config.dashboard_port,
                )
        except Exception as err:
            logger.error("Failed to initialize dashboard web server: %s", err, exc_info=True)
            self.dashboard_server = None

    async def _init_database(self) -> None:
        """Initialize central SQLite manager and repositories."""
        try:
            self.db_manager = SQLiteDatabaseManager()
            await self.db_manager.connect()

            # Initialize repositories with central SQLite database manager
            self.guild_repo = GuildRepository(self.db_manager)
            self.user_repo = UserRepository(self.db_manager)
            self.voice_repo = VoiceRepository(self.db_manager)
            self.welcome_repo = WelcomeRepository(self.db_manager)
            self.music_repo = MusicRepository(self.db_manager)
            self.playlist_repo = PlaylistRepository(self.db_manager)
            self.command_usage_repo = CommandUsageRepository(self.db_manager)
            self.moderation_repo = ModerationRepository(self.db_manager)
            self.security_repo = SecurityRepository(self.db_manager)
            self.automod_repo = AutomodRepository(self.db_manager)
            self.invite_repo = InviteRepository(self.db_manager)
            self.level_repo = LevelRepository(self.db_manager)
            self.ticket_repo = TicketRepository(self.db_manager)
            self.vc_repo = VCRepository(self.db_manager)
            self.rr_repo = ReactionRoleRepository(self.db_manager)
            self.admin_repo = ServerAdminRepository(self.db_manager)
            self.logging_repo = LoggingRepository(self.db_manager)
            self.economy_repo = EconomyRepository(self.db_manager)
            self.shop_repo = ShopRepository(self.db_manager)
            self.minigame_repo = MinigameRepository(self.db_manager)
            self.mimic_repo = MimicRepository(self.db_manager)
            self.mention_repo = MentionSettingsRepository(self.db_manager)
            self.custom_command_repo = CustomCommandRepository(self.db_manager)
            self.soul_repo = SoulRepository(self.db_manager)
            logger.info("Central SQLite database and all repositories initialized successfully.")
        except Exception as err:
            logger.error("Failed to initialize SQLite database: %s", err, exc_info=True)

    async def load_cogs(self) -> None:
        """Dynamically load all extension cogs found within bot/cogs/."""
        cogs_dir = Path(__file__).resolve().parent.parent / "cogs"
        logger.info("Discovering extensions in %s...", cogs_dir)

        loaded_count = 0
        for py_file in cogs_dir.rglob("*.py"):
            if py_file.name.startswith("_"):
                continue

            # Compute module dot path relative to project root
            relative_parts = py_file.relative_to(cogs_dir.parent).with_suffix("").parts
            module_name = f"bot.{'.'.join(relative_parts)}"

            try:
                await self.load_extension(module_name)
                logger.info("Loaded extension: %s", module_name)
                loaded_count += 1
            except Exception as err:
                logger.error("Failed to load extension %s: %s", module_name, err, exc_info=True)

        logger.info("Extension discovery complete: %d extension(s) loaded.", loaded_count)

    async def sync_app_commands(self) -> None:
        """Sync slash command tree globally and ensure dev guild has no duplicate overrides."""
        try:
            if self.config.dev_guild_id:
                dev_guild = discord.Object(id=self.config.dev_guild_id)
                self.tree.clear_commands(guild=dev_guild)
                await self.tree.sync(guild=dev_guild)
                logger.info("Cleared guild-scoped command overrides for dev guild [%s]", self.config.dev_guild_id)

            synced = await self.tree.sync()
            logger.info("Synced %d global slash commands.", len(synced))
        except Exception as err:
            logger.error("Failed to sync slash commands: %s", err)

    async def is_bot_owner(self, user: Union[discord.User, discord.Member, int]) -> bool:
        """Verify whether a user or member is a recognized Bot Owner across all resolution paths."""
        uid = user if isinstance(user, int) else user.id
        if hasattr(self, "config") and self.config:
            if uid in self.config.owner_ids or str(uid) in [str(x) for x in self.config.owner_ids]:
                return True
        if self.owner_ids and (uid in self.owner_ids or str(uid) in [str(x) for x in self.owner_ids]):
            return True
        if self.owner_id and (uid == self.owner_id or str(uid) == str(self.owner_id)):
            return True
        if self.application:
            if self.application.owner and self.application.owner.id == uid:
                return True
            if self.application.team and any(m.id == uid for m in self.application.team.members):
                return True
        try:
            user_obj = user if isinstance(user, (discord.User, discord.Member)) else discord.Object(id=uid)
            return await super().is_owner(user_obj)
        except Exception:
            return False

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Handle interactions, intercepting alias/legacy slash commands to guarantee zero unanswered timeouts."""
        if interaction.type == discord.InteractionType.application_command and interaction.data:
            cmd_name = interaction.data.get("name")
            if cmd_name == "vcpanel":
                cog = self.get_cog("OwnerVC")
                if cog and hasattr(cog, "_execute_owner_vcpanel"):
                    await cog._execute_owner_vcpanel(interaction)
                    return
            elif cmd_name in ("ownerdashboard", "ownerpanel"):
                cog = self.get_cog("Owner Dashboard")
                if cog and hasattr(cog, "_execute_ownerpanel"):
                    await cog._execute_ownerpanel(interaction)
                    return

    async def on_message(self, message: discord.Message) -> None:
        """Process prefix commands for non-bot messages."""
        if message.author.bot:
            return
        await self.process_commands(message)

    async def close(self) -> None:
        """Gracefully release network, database, and process resources upon shutdown."""
        logger.info("Shutting down Death Bot...")

        if hasattr(self, "dm_queue_service") and self.dm_queue_service:
            try:
                await self.dm_queue_service.stop()
            except Exception as err:
                logger.warning("Error stopping DMQueueService during shutdown: %s", err)

        if hasattr(self, "dashboard_server") and self.dashboard_server:
            try:
                await self.dashboard_server.stop()
            except Exception as err:
                logger.warning("Error stopping DashboardServer during shutdown: %s", err)

        if hasattr(self, "soul_provider") and self.soul_provider:
            try:
                await self.soul_provider.close()
            except Exception as err:
                logger.warning("Error closing soul_provider during shutdown: %s", err)

        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("HTTP session closed.")

        if self.db_manager:
            await self.db_manager.close()

        try:
            await super().close()
        except AttributeError:
            # Handles offline / dry-run test instances that never initialized the gateway queue
            pass
        logger.info("Death Bot shutdown complete.")

