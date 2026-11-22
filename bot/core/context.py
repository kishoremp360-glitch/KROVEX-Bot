"""Unified command context bridging Prefix commands and Slash command interactions.

Allows writing 100% shared business logic with zero duplication between
Prefix and Slash commands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Union

import discord
from discord.ext import commands

from bot.utils.embeds import EmbedBuilder

if TYPE_CHECKING:
    from bot.core.bot import DeathBot


class UnifiedContext:
    """Unified context adapter normalizing discord.Interaction and commands.Context."""

    def __init__(
        self,
        bot: DeathBot,
        interaction: Optional[discord.Interaction] = None,
        prefix_ctx: Optional[commands.Context] = None,
    ) -> None:
        self.bot = bot
        self.interaction = interaction
        self.prefix_ctx = prefix_ctx
        self._deferred: bool = False
        self._ephemeral: bool = False

    @classmethod
    def from_interaction(cls, interaction: discord.Interaction) -> UnifiedContext:
        """Create a unified context from a slash command interaction."""
        return cls(bot=interaction.client, interaction=interaction)  # type: ignore

    @classmethod
    def from_prefix(cls, ctx: commands.Context) -> UnifiedContext:
        """Create a unified context from a prefix command context."""
        return cls(bot=ctx.bot, prefix_ctx=ctx)  # type: ignore

    @property
    def is_interaction(self) -> bool:
        """True if the command was invoked via a slash command."""
        return self.interaction is not None

    @property
    def is_prefix(self) -> bool:
        """True if the command was invoked via a prefix message."""
        return self.prefix_ctx is not None

    @property
    def guild(self) -> Optional[discord.Guild]:
        if self.interaction:
            return self.interaction.guild
        return self.prefix_ctx.guild if self.prefix_ctx else None

    @property
    def channel(self) -> Union[discord.TextChannel, discord.VoiceChannel, discord.Thread, discord.abc.GuildChannel, discord.abc.PrivateChannel]:
        if self.interaction:
            return self.interaction.channel  # type: ignore
        return self.prefix_ctx.channel  # type: ignore

    @property
    def author(self) -> Union[discord.User, discord.Member]:
        if self.interaction:
            return self.interaction.user
        return self.prefix_ctx.author  # type: ignore

    @property
    def user(self) -> Union[discord.User, discord.Member]:
        return self.author

    @property
    def me(self) -> Optional[discord.Member]:
        if self.guild:
            return self.guild.me
        return None

    async def defer(self, ephemeral: bool = False) -> None:
        """Defer the response (only affects slash command interactions)."""
        if self.interaction:
            if not self.interaction.response.is_done():
                try:
                    await self.interaction.response.defer(ephemeral=ephemeral)
                except (discord.HTTPException, discord.InteractionResponded):
                    pass
            self._deferred = True
            self._ephemeral = ephemeral

    async def reply(
        self,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        embeds: Optional[List[discord.Embed]] = None,
        view: Optional[discord.ui.View] = None,
        ephemeral: bool = False,
    ) -> Union[discord.Message, discord.WebhookMessage]:
        """Send a response whether invoked via slash or prefix command."""
        if embeds is None and embed is not None:
            embeds = [embed]

        eff_ephemeral = ephemeral or self._ephemeral

        if self.interaction:
            if not self.interaction.response.is_done() and not self._deferred:
                try:
                    await self.interaction.response.send_message(
                        content=content,
                        embeds=embeds or [],
                        view=view or discord.utils.MISSING,
                        ephemeral=eff_ephemeral,
                    )
                    return await self.interaction.original_response()
                except (discord.HTTPException, discord.InteractionResponded) as exc:
                    # Fallback to followup if Discord or local state already registered acknowledgement
                    err_code = getattr(exc, "code", None)
                    err_msg = str(exc).lower()
                    if err_code == 40060 or "already been acknowledged" in err_msg or isinstance(exc, discord.InteractionResponded):
                        return await self.interaction.followup.send(
                            content=content,
                            embeds=embeds or [],
                            view=view or discord.utils.MISSING,
                            ephemeral=eff_ephemeral,
                            wait=True,
                        )
                    raise
            else:
                return await self.interaction.followup.send(
                    content=content,
                    embeds=embeds or [],
                    view=view or discord.utils.MISSING,
                    ephemeral=eff_ephemeral,
                    wait=True,
                )
        elif self.prefix_ctx:
            return await self.prefix_ctx.reply(
                content=content,
                embeds=embeds or [],
                view=view or discord.utils.MISSING,
                mention_author=False,
            )
        else:
            raise RuntimeError("UnifiedContext has neither interaction nor prefix_ctx.")

    async def edit(
        self,
        message: Optional[Union[discord.Message, discord.WebhookMessage]] = None,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        embeds: Optional[List[discord.Embed]] = None,
        view: Optional[discord.ui.View] = None,
    ) -> Union[discord.Message, discord.WebhookMessage]:
        """Edit a previously sent message or interaction response."""
        if embeds is None and embed is not None:
            embeds = [embed]

        if message is not None:
            await message.edit(
                content=content,
                embeds=embeds if embeds is not None else discord.utils.MISSING,
                view=view or discord.utils.MISSING,
            )
            return message

        if self.interaction:
            return await self.interaction.edit_original_response(
                content=content,
                embeds=embeds if embeds is not None else discord.utils.MISSING,
                view=view or discord.utils.MISSING,
            )
        raise RuntimeError("Cannot edit without an existing message or interaction.")

    async def send_success(self, title: str, description: Optional[str] = None, ephemeral: bool = False) -> Any:
        """Send a standardized neon green success embed."""
        embed = EmbedBuilder.success(title=title, description=description)
        return await self.reply(embed=embed, ephemeral=ephemeral)

    async def send_error(
        self,
        title: str,
        description: Optional[str] = None,
        error_code: Optional[str] = None,
        ephemeral: bool = True,
    ) -> Any:
        """Send a standardized neon red error embed."""
        embed = EmbedBuilder.error(title=title, description=description, error_code=error_code)
        return await self.reply(embed=embed, ephemeral=ephemeral)

    async def send_info(self, title: str, description: Optional[str] = None, ephemeral: bool = False) -> Any:
        """Send a standardized neon purple informational embed."""
        embed = EmbedBuilder.info(title=title, description=description)
        return await self.reply(embed=embed, ephemeral=ephemeral)

