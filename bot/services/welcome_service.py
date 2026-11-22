"""Welcome and goodbye processing service for Death Bot."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import discord

from bot.database.repositories import WelcomeRepository
from bot.utils.embeds import EmbedBuilder
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.services.welcome")


class WelcomeService:
    """Orchestrates new member greetings, automatic role assignments, and departure logs."""

    def __init__(self, bot: DeathBot, welcome_repo: WelcomeRepository) -> None:
        self.bot = bot
        self.repo = welcome_repo

    def format_template(self, template: str, member: discord.Member) -> str:
        """Replace standard and alias placeholders in string template."""
        return (
            template.replace("{user}", member.mention)
            .replace("{mention}", member.mention)
            .replace("{user_name}", member.name)
            .replace("{username}", member.name)
            .replace("{user_display}", member.display_name)
            .replace("{display_name}", member.display_name)
            .replace("{server}", member.guild.name)
            .replace("{server_name}", member.guild.name)
            .replace("{member_count}", str(member.guild.member_count))
            .replace("{count}", str(member.guild.member_count))
        )

    async def handle_member_join(self, member: discord.Member) -> None:
        """Process member join: welcome channel message, auto roles, and welcome DM."""
        guild = member.guild
        try:
            settings = await self.repo.get_or_create(guild.id)
            if not settings.enabled:
                return

            # 1. Automatic Roles with hierarchy and permission validation
            if settings.auto_role_ids:
                roles_to_add = [
                    guild.get_role(rid)
                    for rid in settings.auto_role_ids
                    if guild.get_role(rid) is not None
                ]
                me = guild.me
                if roles_to_add and me and me.guild_permissions.manage_roles:
                    try:
                        # Ensure bot's top role is strictly higher than target roles
                        valid_roles = [r for r in roles_to_add if r < me.top_role]
                        if valid_roles:
                            await member.add_roles(*valid_roles, reason="Death Bot Auto-role on join")
                    except discord.Forbidden:
                        logger.warning("Missing permissions to assign auto-roles in %s", guild.name)
                    except Exception as err:
                        logger.error("Error adding auto-roles to %s: %s", member, err)
                elif roles_to_add and (not me or not me.guild_permissions.manage_roles):
                    logger.warning("Cannot assign auto-roles in %s: bot lacks Manage Roles permission", guild.name)

            # 2. Public Welcome Message / Embed in configured channel
            if settings.channel_id:
                channel = guild.get_channel(settings.channel_id)
                if isinstance(channel, discord.TextChannel):
                    me = guild.me
                    perms = channel.permissions_for(me) if me else None
                    if perms and perms.send_messages:
                        formatted_msg = self.format_template(settings.message_template, member)
                        if settings.embed_enabled and perms.embed_links:
                            embed = EmbedBuilder.base(
                                title=f"👋 Welcome to {guild.name}!",
                                description=formatted_msg,
                                color=0x9D4EDD,
                                thumbnail=member.display_avatar.url,
                                footer_text=f"Member #{guild.member_count}",
                            )
                            await channel.send(embed=embed)
                        else:
                            await channel.send(formatted_msg)
                    else:
                        logger.warning("Cannot send welcome message in %s: lacking Send Messages permission", channel.name)

            # 3. Direct Message greeting
            if settings.dm_enabled:
                try:
                    dm_text = self.format_template(settings.dm_template, member)
                    dm_embed = EmbedBuilder.base(
                        title=f"Welcome to {guild.name}!",
                        description=dm_text,
                        color=0x9D4EDD,
                        thumbnail=guild.icon.url if guild.icon else None,
                    )
                    queue_service = getattr(self.bot, "dm_queue_service", None)
                    if queue_service:
                        await queue_service.enqueue(
                            recipient_id=member.id,
                            guild_id=guild.id,
                            message_type="welcome",
                            embed=dm_embed,
                            idempotency_key=f"welcome:{guild.id}:{member.id}",
                        )
                        logger.info("Enqueued welcome DM for %s in %s", member, guild.name)
                    else:
                        await member.send(embed=dm_embed)
                except (discord.Forbidden, discord.HTTPException):
                    # User likely has DMs closed or blocked bot; safely ignore
                    logger.debug("Could not deliver welcome DM to %s (DMs closed)", member)

        except Exception as err:
            logger.error("Error processing member join for %s in %s: %s", member, guild.name, err)

    async def handle_member_remove(self, member: discord.Member) -> None:
        """Process member departure / goodbye message."""
        guild = member.guild
        try:
            settings = await self.repo.get_or_create(guild.id)
            if not settings.send_goodbye or not settings.goodbye_channel_id:
                return

            channel = guild.get_channel(settings.goodbye_channel_id)
            if isinstance(channel, discord.TextChannel):
                me = guild.me
                perms = channel.permissions_for(me) if me else None
                if perms and perms.send_messages:
                    goodbye_msg = self.format_template(settings.goodbye_template, member)
                    if perms.embed_links:
                        embed = EmbedBuilder.base(
                            title="👋 Member Left",
                            description=goodbye_msg,
                            color=0xFF3366,
                            thumbnail=member.display_avatar.url,
                            footer_text=f"Remaining Members: {guild.member_count}",
                        )
                        await channel.send(embed=embed)
                    else:
                        await channel.send(goodbye_msg)
        except Exception as err:
            logger.error("Error processing member departure for %s: %s", member, err)

