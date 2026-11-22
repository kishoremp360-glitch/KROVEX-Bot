"""Global error handling for both Prefix and Slash commands."""

from __future__ import annotations

import sys
import traceback
import uuid
from typing import TYPE_CHECKING, Optional, Union

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.checks import (
    BotNotInVoiceError,
    UserDifferentVoiceChannelError,
    UserNotInVoiceError,
)
from bot.utils.embeds import EmbedBuilder
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.core.errors")


class GlobalErrorHandler:
    """Centralized handler for all command-related errors in Death Bot."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    async def handle_prefix_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Handle errors raised during Prefix command execution."""
        # Unwrap CommandInvokeError
        if isinstance(error, commands.CommandInvokeError):
            error = error.original  # type: ignore

        # 1. Silently ignore command not found to avoid chat clutter
        if isinstance(error, commands.CommandNotFound):
            return

        # 2. Cooldown
        if isinstance(error, commands.CommandOnCooldown):
            embed = EmbedBuilder.warning(
                title="Command on Cooldown",
                description=f"Please wait **{error.retry_after:.1f}** seconds before using this command again.",
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        # 3. Missing user permissions
        if isinstance(error, commands.MissingPermissions):
            missing = ", ".join(f"`{p.replace('_', ' ').title()}`" for p in error.missing_permissions)
            embed = EmbedBuilder.error(
                title="Permission Denied",
                description=f"You need the following permission(s) to execute this command:\n{missing}",
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        # 4. Missing bot permissions
        if isinstance(error, commands.BotMissingPermissions):
            missing = ", ".join(f"`{p.replace('_', ' ').title()}`" for p in error.missing_permissions)
            embed = EmbedBuilder.error(
                title="Bot Permission Missing",
                description=f"I require the following permission(s) to execute this command:\n{missing}",
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        # 5. Missing required argument
        if isinstance(error, commands.MissingRequiredArgument):
            embed = EmbedBuilder.warning(
                title="Missing Argument",
                description=f"Parameter `{error.param.name}` is required.\nUsage: `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`",
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        # 6. Bad argument
        if isinstance(error, (commands.BadArgument, commands.BadUnionArgument)):
            embed = EmbedBuilder.error(
                title="Invalid Input",
                description=str(error),
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        # 7. Voice state errors
        if isinstance(error, (UserNotInVoiceError, BotNotInVoiceError, UserDifferentVoiceChannelError)):
            embed = EmbedBuilder.warning(
                title="Voice Error",
                description=str(error),
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        # 8. Not owner
        if isinstance(error, commands.NotOwner):
            embed = EmbedBuilder.error(
                title="Restricted",
                description="This command is restricted to the bot developers.",
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        # 9. Generic unhandled error
        error_id = str(uuid.uuid4())[:8].upper()
        logger.error(
            "Unhandled prefix error [Ref: %s] in command '%s': %s",
            error_id,
            ctx.command.qualified_name if ctx.command else "Unknown",
            error,
            exc_info=error,
        )

        embed = EmbedBuilder.error(
            title="System Error",
            description="An unexpected error occurred while processing your command.",
            error_code=error_id,
        )
        try:
            await ctx.reply(embed=embed, mention_author=False)
        except Exception:
            pass

    async def handle_slash_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Handle errors raised during Slash command execution."""
        # Unwrap CommandInvokeError
        if isinstance(error, app_commands.CommandInvokeError):
            error = error.original  # type: ignore

        # 1. Cooldown
        if isinstance(error, app_commands.CommandOnCooldown):
            embed = EmbedBuilder.warning(
                title="Command on Cooldown",
                description=f"Please wait **{error.retry_after:.1f}** seconds before using this command again.",
            )
            await self._respond_slash(interaction, embed=embed, ephemeral=True)
            return

        # 2. Missing user permissions
        if isinstance(error, app_commands.MissingPermissions):
            missing = ", ".join(f"`{p.replace('_', ' ').title()}`" for p in error.missing_permissions)
            embed = EmbedBuilder.error(
                title="Permission Denied",
                description=f"You need the following permission(s) to execute this command:\n{missing}",
            )
            await self._respond_slash(interaction, embed=embed, ephemeral=True)
            return

        # 3. Missing bot permissions
        if isinstance(error, app_commands.BotMissingPermissions):
            missing = ", ".join(f"`{p.replace('_', ' ').title()}`" for p in error.missing_permissions)
            embed = EmbedBuilder.error(
                title="Bot Permission Missing",
                description=f"I require the following permission(s) to execute this command:\n{missing}",
            )
            await self._respond_slash(interaction, embed=embed, ephemeral=True)
            return

        # 4. Voice state errors
        if isinstance(error, (UserNotInVoiceError, BotNotInVoiceError, UserDifferentVoiceChannelError)):
            embed = EmbedBuilder.warning(
                title="Voice Error",
                description=str(error),
            )
            await self._respond_slash(interaction, embed=embed, ephemeral=True)
            return

        # 5. Check failures
        if isinstance(error, app_commands.CheckFailure):
            embed = EmbedBuilder.error(
                title="Check Failed",
                description="You do not satisfy the requirements to run this command.",
            )
            await self._respond_slash(interaction, embed=embed, ephemeral=True)
            return

        # 6. Transformer / Bad argument conversion
        if isinstance(error, app_commands.TransformerError):
            val_str = f"`{error.value}`" if getattr(error, "value", None) else "the provided argument"
            embed = EmbedBuilder.error(
                title="Invalid Channel or Argument",
                description=f"Could not convert {val_str} to a valid channel. Please select or mention a valid text channel.",
            )
            await self._respond_slash(interaction, embed=embed, ephemeral=True)
            return

        # 6. Unhandled error
        error_id = str(uuid.uuid4())[:8].upper()
        logger.error(
            "Unhandled slash error [Ref: %s] in command '%s': %s",
            error_id,
            interaction.command.name if interaction.command else "Unknown",
            error,
            exc_info=error,
        )

        embed = EmbedBuilder.error(
            title="System Error",
            description="An unexpected error occurred while processing your slash command.",
            error_code=error_id,
        )
        await self._respond_slash(interaction, embed=embed, ephemeral=True)

    async def _respond_slash(self, interaction: discord.Interaction, embed: discord.Embed, ephemeral: bool = True) -> None:
        """Safely respond to interaction considering whether already responded or deferred."""
        try:
            if not interaction.response.is_done():
                try:
                    await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
                    return
                except (discord.HTTPException, discord.InteractionResponded) as exc:
                    err_code = getattr(exc, "code", None)
                    err_msg = str(exc).lower()
                    if err_code == 40060 or "already been acknowledged" in err_msg or isinstance(exc, discord.InteractionResponded):
                        await interaction.followup.send(embed=embed, ephemeral=ephemeral)
                        return
                    raise
            else:
                await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        except Exception as err:
            logger.error("Failed to send error response to interaction: %s", err)

