"""Custom permission checks and decorators for both Prefix and Slash commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, TypeVar

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

T = TypeVar("T")


class UserNotInVoiceError(commands.CheckFailure, app_commands.AppCommandError):
    """Raised when a command requires the user to be connected to a voice channel."""
    pass


class BotNotInVoiceError(commands.CheckFailure, app_commands.AppCommandError):
    """Raised when a command requires the bot to be connected to a voice channel."""
    pass


class UserDifferentVoiceChannelError(commands.CheckFailure, app_commands.AppCommandError):
    """Raised when the user is in a different voice channel than the bot."""
    pass


def is_bot_owner():
    """Check if the invoker is configured as a bot owner."""
    async def predicate(ctx: commands.Context) -> bool:
        bot: DeathBot = ctx.bot  # type: ignore
        if hasattr(bot, "config") and (ctx.author.id in bot.config.owner_ids or str(ctx.author.id) in [str(x) for x in bot.config.owner_ids]):
            return True
        if hasattr(bot, "is_bot_owner") and callable(bot.is_bot_owner):
            try:
                res = bot.is_bot_owner(ctx.author)
                if asyncio.iscoroutine(res):
                    return await res
                if isinstance(res, bool):
                    return res
            except Exception:
                pass
        return await bot.is_owner(ctx.author)

    return commands.check(predicate)


def is_app_bot_owner():
    """Slash command check for bot ownership."""
    async def predicate(interaction: discord.Interaction) -> bool:
        bot: DeathBot = interaction.client  # type: ignore
        if hasattr(bot, "config") and (interaction.user.id in bot.config.owner_ids or str(interaction.user.id) in [str(x) for x in bot.config.owner_ids]):
            return True
        if hasattr(bot, "is_bot_owner") and callable(bot.is_bot_owner):
            try:
                res = bot.is_bot_owner(interaction.user)
                if asyncio.iscoroutine(res):
                    return await res
                if isinstance(res, bool):
                    return res
            except Exception:
                pass
        return await bot.is_owner(interaction.user)

    return app_commands.check(predicate)


def require_voice_channel():
    """Ensure the user invoking the command is connected to a voice channel."""
    async def prefix_predicate(ctx: commands.Context) -> bool:
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice or not ctx.author.voice.channel:
            raise UserNotInVoiceError("You must be connected to a voice channel to use this command.")
        return True

    return commands.check(prefix_predicate)


def require_app_voice_channel():
    """Slash check ensuring user is connected to a voice channel."""
    async def app_predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or not interaction.user.voice.channel:
            raise UserNotInVoiceError("You must be connected to a voice channel to use this command.")
        return True

    return app_commands.check(app_predicate)

