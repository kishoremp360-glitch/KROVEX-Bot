"""Death Bot Entry Point.

Initializes logging, loads validated configuration, boots the Discord bot
engine, and registers OS signal handlers for graceful shutdown.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

import discord

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig, ConfigurationError
from bot.core.bot import DeathBot
from bot.utils.logger import get_logger, setup_logging

logger = get_logger("death_bot.main")


async def start_cloud_health_server(port: int = 7860):
    """Start lightweight HTTP health server for cloud platforms (e.g. Hugging Face Spaces / Render)."""
    try:
        from aiohttp import web

        async def handle_ping(request: web.Request) -> web.Response:
            return web.Response(text="KROVEX ONLINE 24/7\n", status=200)

        app = web.Application()
        app.router.add_get("/", handle_ping)
        app.router.add_get("/health", handle_ping)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info("Cloud health-check server active on port %d.", port)
        return runner
    except Exception as exc:
        logger.warning("Could not start cloud health server on port %d: %s", port, exc)
        return None


async def main() -> int:
    """Async main routine."""
    # Step 1: Pre-load config to determine log level
    try:
        config = BotConfig.from_env(validate=True)
    except ConfigurationError as err:
        # Fallback minimal logging to print readable notice
        setup_logging("INFO")
        logger.error("Configuration validation error:\n%s", err)
        return 1
    except Exception as err:
        setup_logging("INFO")
        logger.error("Unexpected error loading configuration: %s", err, exc_info=True)
        return 1

    # Step 2: Initialize system-wide logging with configured level
    setup_logging(level=config.log_level)
    logger.info("Configuration validated successfully.")
    logger.debug("Runtime configuration: %s", config)

    # Step 2b: Cloud health server (activates if SPACE_ID or PORT is present)
    health_port = int(os.environ.get("PORT", os.environ.get("SPACE_PORT", "7860")))
    health_runner = None
    if os.environ.get("SPACE_ID") or os.environ.get("PORT"):
        health_runner = await start_cloud_health_server(port=health_port)

    # Step 3: Instantiate bot
    bot = DeathBot(config=config)

    # Step 4: Handle process signals for graceful shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Shutdown signal received. Initiating graceful shutdown...")
        stop_event.set()
        asyncio.create_task(bot.close())

    # Register OS signals if supported (Windows supports SIGINT)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except (NotImplementedError, AttributeError):
            # Windows may not support add_signal_handler for all signals
            pass

    # Step 5: Start the bot
    try:
        async with bot:
            await bot.start(config.token)
    except discord.errors.PrivilegedIntentsRequired:
        logger.warning(
            "Privileged intents (Server Members or Message Content) are not enabled in the Discord Developer Portal.\n"
            "To enable prefix commands (!) and member caching, enable 'Server Members Intent' and 'Message Content Intent' at:\n"
            "https://discord.com/developers/applications/\n"
            "Starting Death Bot with standard intents now so Slash Commands, Voice, and Buttons are fully active..."
        )
        fallback_intents = discord.Intents.default()
        fallback_intents.voice_states = True
        fallback_intents.guilds = True
        fallback_bot = DeathBot(config=config, intents=fallback_intents)
        try:
            async with fallback_bot:
                await fallback_bot.start(config.token)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received.")
        except Exception as err:
            logger.critical("Fatal error encountered during bot execution: %s", err, exc_info=True)
            return 1
        finally:
            if not fallback_bot.is_closed():
                await fallback_bot.close()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    except Exception as err:
        logger.critical("Fatal error encountered during bot execution: %s", err, exc_info=True)
        return 1
    finally:
        if health_runner:
            try:
                await health_runner.cleanup()
            except Exception:
                pass
        if not bot.is_closed():
            await bot.close()

    return 0


def run() -> None:
    """Sync entry point wrapper."""
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()

