"""Advanced Support Ticket System Cog with full Prefix and Slash command parity."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.tickets.transcript import generate_transcript
from bot.cogs.tickets.views import (
    TicketActionView,
    TicketCloseConfirmView,
    TicketPanelView,
    handle_create_ticket,
)
from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.tickets")
BRAND_COLOR = 0x9D4EDD


class TicketsCog(commands.GroupCog, group_name="ticket"):
    """Comprehensive support ticket system with interactive panels, categories, and transcripts."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot
        super().__init__()

    async def cog_load(self) -> None:
        """Register persistent views on bot load."""
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketActionView())

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Handle persistent ticket interactions even across bot restarts."""
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = interaction.data.get("custom_id", "") if hasattr(interaction, "data") and isinstance(interaction.data, dict) else ""
        if custom_id in ("ticket:create_default", "ticket_create_general", "ticket:create") or custom_id.startswith("ticket:create") or custom_id.startswith("ticket_create"):
            try:
                await handle_create_ticket(interaction)
            except Exception as err:
                logger.warning("Error processing ticket creation interaction: %s", err)
            return
        if custom_id and custom_id.startswith("ticket_rate:"):
            from bot.cogs.tickets.views import handle_ticket_rating_interaction
            try:
                await handle_ticket_rating_interaction(interaction, bot=self.bot)
            except Exception as err:
                logger.warning("Error processing ticket rating interaction: %s", err)

    # =========================================================
    # CORE SHARED BUSINESS LOGIC
    # =========================================================

    async def _execute_setup(self, ctx: UnifiedContext, category: Optional[discord.CategoryChannel] = None, staff_role: Optional[discord.Role] = None, transcript_channel: Optional[discord.TextChannel] = None) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        if not ctx.author.guild_permissions.administrator and not ctx.author.guild_permissions.manage_guild:
            await ctx.send_error("Permission Denied", "You need Administrator or Manage Server permissions.")
            return

        cat_id = category.id if category else None
        role_id = staff_role.id if staff_role else None
        tr_id = transcript_channel.id if transcript_channel else None

        await self.bot.ticket_repo.update_settings(
            ctx.guild.id,
            category_id=cat_id,
            staff_role_id=role_id,
            transcript_channel_id=tr_id,
        )

        embed = EmbedBuilder.success(
            title=f"{KrovexEmoji.TICKET} Ticket System Configured",
            description=(
                f"**Parent Category:** {category.mention if category else '`None (Root)`'}\n"
                f"**Support Staff Role:** {staff_role.mention if staff_role else '`None`'}\n"
                f"**Transcript Channel:** {transcript_channel.mention if transcript_channel else '`None`'}\n\n"
                "Use `ticketpanel` to deploy an interactive panel for your members."
            ),
        )
        await ctx.reply(embed=embed)

    async def _execute_panel(self, ctx: UnifiedContext, channel: Optional[discord.TextChannel] = None, title: str = "Support Tickets", description: str = "Click below to open a private ticket with our team.") -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        if not ctx.author.guild_permissions.administrator and not ctx.author.guild_permissions.manage_guild:
            await ctx.send_error("Permission Denied", "You need Administrator or Manage Server permissions.")
            return

        target_ch = channel or ctx.channel
        if not isinstance(target_ch, discord.TextChannel):
            await ctx.send_error("Invalid Channel", "Must be deployed in a text channel.")
            return

        categories = await self.bot.ticket_repo.get_categories(ctx.guild.id)
        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.TICKET} {title}",
            description=description,
            color=BRAND_COLOR,
        )
        embed.set_footer(text=f"{ctx.guild.name} • Support Desk", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)

        view = TicketPanelView(categories=categories)
        await target_ch.send(embed=embed, view=view)
        await ctx.send_success("Panel Deployed", f"Ticket creation panel deployed in {target_ch.mention}!")

    async def _execute_create(self, ctx: UnifiedContext, category_name: Optional[str] = None) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return

        cat_id = None
        if category_name:
            cats = await self.bot.ticket_repo.get_categories(ctx.guild.id)
            for c in cats:
                if c["name"].lower() == category_name.lower():
                    cat_id = c["id"]
                    break

        # Simulate interaction or use helper
        if ctx.is_slash and ctx.interaction:
            await handle_create_ticket(ctx.interaction, cat_id)
        else:
            # Prefix execution
            settings = await self.bot.ticket_repo.get_settings(ctx.guild.id)
            if await self.bot.ticket_repo.is_blacklisted(ctx.guild.id, ctx.author.id):
                await ctx.send_error("Blacklisted", "You are blacklisted from opening tickets.")
                return

            open_tickets = await self.bot.ticket_repo.get_user_open_tickets(ctx.guild.id, ctx.author.id)
            max_t = settings.get("max_tickets_per_user") or 1
            if len(open_tickets) >= max_t:
                await ctx.send_error("Limit Reached", f"You already have {len(open_tickets)} open ticket(s).")
                return

            # Create channel
            guild = ctx.guild
            user = ctx.author
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, embed_links=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, manage_messages=True),
            }
            s_role_id = settings.get("staff_role_id")
            if s_role_id:
                s_role = guild.get_role(s_role_id)
                if s_role:
                    overwrites[s_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            ticket_counter = (settings.get("ticket_counter") or 0) + 1
            ch = await guild.create_text_channel(
                name=f"ticket-{ticket_counter:04d}",
                overwrites=overwrites,
                topic=f"Support ticket for {user.name} ({user.id})",
            )
            await self.bot.ticket_repo.create_ticket(guild.id, ch.id, user.id, cat_id)

            embed = EmbedBuilder.base(
                title=f"{KrovexEmoji.TICKET} Support Ticket #{ticket_counter:04d}",
                description=f"Welcome {user.mention}! Support staff has been notified.\nDescribe your question below.",
                color=BRAND_COLOR,
            )
            await ch.send(content=user.mention, embed=embed, view=TicketActionView())
            await ctx.reply(f"✅ Your ticket has been created: {ch.mention}")

    async def _execute_close(self, ctx: UnifiedContext, reason: Optional[str] = None) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not an active support ticket.")
            return

        view = TicketCloseConfirmView(creator_id=ticket.get("creator_id"))
        embed = EmbedBuilder.warning(
            title="Close Ticket",
            description=f"Reason: **{reason or 'No reason provided'}**\nConfirm closing this ticket channel?",
        )
        await ctx.reply(embed=embed, view=view)

    async def _execute_reopen(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not a ticket.")
            return

        await self.bot.ticket_repo.reopen_ticket(ctx.channel.id)
        await ctx.send_success("Ticket Reopened", "This ticket is now active again.")

    async def _execute_claim(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not an active support ticket.")
            return
        if ticket.get("claimed_by"):
            await ctx.send_error("Already Claimed", f"This ticket is already claimed by <@{ticket['claimed_by']}>.")
            return

        await self.bot.ticket_repo.claim_ticket(ctx.channel.id, ctx.author.id)
        await ctx.send_success("Ticket Claimed", f"Ticket is now claimed by {ctx.author.mention}.")

    async def _execute_unclaim(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not an active support ticket.")
            return

        await self.bot.ticket_repo.unclaim_ticket(ctx.channel.id)
        await ctx.send_success("Claim Released", "This ticket is now open for any support agent.")

    async def _execute_add(self, ctx: UnifiedContext, member: discord.Member) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not an active support ticket.")
            return

        if isinstance(ctx.channel, discord.TextChannel):
            await ctx.channel.set_permissions(member, read_messages=True, send_messages=True, attach_files=True, embed_links=True)
            await self.bot.ticket_repo.add_participant(ticket["ticket_id"], member.id, ctx.author.id)
            await ctx.send_success("Member Added", f"Added {member.mention} to this ticket.")

    async def _execute_remove(self, ctx: UnifiedContext, member: discord.Member) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not an active support ticket.")
            return

        if isinstance(ctx.channel, discord.TextChannel):
            await ctx.channel.set_permissions(member, overwrite=None)
            await self.bot.ticket_repo.remove_participant(ticket["ticket_id"], member.id)
            await ctx.send_success("Member Removed", f"Removed {member.mention} from this ticket.")

    async def _execute_lock(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not an active support ticket.")
            return

        creator = ctx.guild.get_member(ticket["creator_id"])
        if creator and isinstance(ctx.channel, discord.TextChannel):
            await ctx.channel.set_permissions(creator, read_messages=True, send_messages=False)
        await self.bot.ticket_repo.lock_ticket(ctx.channel.id)
        await ctx.send_success("Ticket Locked", "The ticket creator can no longer send messages.")

    async def _execute_unlock(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not an active support ticket.")
            return

        creator = ctx.guild.get_member(ticket["creator_id"])
        if creator and isinstance(ctx.channel, discord.TextChannel):
            await ctx.channel.set_permissions(creator, read_messages=True, send_messages=True)
        await self.bot.ticket_repo.unlock_ticket(ctx.channel.id)
        await ctx.send_success("Ticket Unlocked", "The ticket creator can now send messages.")

    async def _execute_transcript(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not isinstance(ctx.channel, discord.TextChannel):
            return
        file = await generate_transcript(ctx.channel)
        await ctx.reply("📜 Exported ticket transcript:", file=file)

    async def _execute_reason(self, ctx: UnifiedContext, reason: str) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not an active support ticket.")
            return

        await self.bot.ticket_repo.set_reason(ctx.channel.id, reason)
        await ctx.send_success("Reason Updated", f"Ticket note updated: **{reason}**")

    async def _execute_category(self, ctx: UnifiedContext, action: str, name: str, emoji: str = "🎫", description: str = "") -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        if action.lower() == "add":
            cat_id = await self.bot.ticket_repo.create_category(ctx.guild.id, name, emoji, description)
            await ctx.send_success("Category Added", f"Created ticket category `{name}` (ID: {cat_id}).")
        elif action.lower() in ("delete", "remove"):
            ok = await self.bot.ticket_repo.delete_category(ctx.guild.id, name)
            if ok:
                await ctx.send_success("Category Removed", f"Deleted category `{name}`.")
            else:
                await ctx.send_error("Not Found", f"No category found matching `{name}`.")
        else:
            cats = await self.bot.ticket_repo.get_categories(ctx.guild.id)
            desc = "\n".join(f"• {c['emoji']} **{c['name']}** (ID: `{c['id']}`) - {c.get('description', '')}" for c in cats) or "No custom categories configured."
            embed = EmbedBuilder.base(title=f"{KrovexEmoji.TICKET} Ticket Categories", description=desc, color=BRAND_COLOR)
            await ctx.reply(embed=embed)

    async def _execute_role(self, ctx: UnifiedContext, role: discord.Role) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        await self.bot.ticket_repo.update_settings(ctx.guild.id, staff_role_id=role.id)
        await ctx.send_success("Staff Role Set", f"Support staff role updated to {role.mention}.")

    async def _execute_limit(self, ctx: UnifiedContext, limit: int) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if limit < 1 or limit > 10:
            await ctx.send_error("Invalid Range", "Ticket limit must be between 1 and 10.")
            return

        await self.bot.ticket_repo.update_settings(ctx.guild.id, max_tickets_per_user=limit)
        await ctx.send_success("Limit Configured", f"Max open tickets per user set to `{limit}`.")

    async def _execute_cooldown(self, ctx: UnifiedContext, seconds: int) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return
        if seconds < 0 or seconds > 86400:
            await ctx.send_error("Invalid Seconds", "Cooldown must be between 0 and 86400 seconds.")
            return

        await self.bot.ticket_repo.update_settings(ctx.guild.id, cooldown_seconds=seconds)
        await ctx.send_success("Cooldown Updated", f"Ticket creation cooldown set to `{seconds}`s.")

    async def _execute_stats(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        stats = await self.bot.ticket_repo.get_ticket_stats(ctx.guild.id)
        embed = EmbedBuilder.base(
            title=f"📊 Ticket Statistics • {ctx.guild.name}",
            color=BRAND_COLOR,
        )
        embed.add_field(name="Total Tickets", value=f"`{stats['total']}`", inline=True)
        embed.add_field(name="Open Tickets", value=f"🟢 `{stats['open']}`", inline=True)
        embed.add_field(name="Claimed Tickets", value=f"🟡 `{stats['claimed']}`", inline=True)
        embed.add_field(name="Closed Tickets", value=f"🔴 `{stats['closed']}`", inline=True)
        embed.add_field(name="Average Rating", value=f"⭐ `{stats['avg_rating']} / 5.0`", inline=True)
        await ctx.reply(embed=embed)

    async def _execute_rating(self, ctx: UnifiedContext, stars: int, feedback: Optional[str] = None) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not a ticket.")
            return
        if stars < 1 or stars > 5:
            await ctx.send_error("Invalid Rating", "Rating must be between 1 and 5 stars.")
            return

        await self.bot.ticket_repo.set_rating(ctx.channel.id, stars, feedback)
        await ctx.send_success("Rating Submitted", f"Recorded `{stars}/5` stars rating. Thank you!")

    async def _execute_logs(self, ctx: UnifiedContext, channel: discord.TextChannel) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Administrator required.")
            return

        await self.bot.ticket_repo.update_settings(ctx.guild.id, logs_channel_id=channel.id)
        await ctx.send_success("Logs Configured", f"Ticket audit logs will be routed to {channel.mention}.")

    async def _execute_delete(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not an active support ticket.")
            return
        if not ctx.author.guild_permissions.manage_channels and not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Manage Channels required.")
            return

        await ctx.reply("🗑️ Deleting ticket channel immediately...")
        await asyncio.sleep(2)
        if isinstance(ctx.channel, discord.TextChannel):
            await ctx.channel.delete(reason=f"Ticket deleted by {ctx.author}")

    async def _execute_rename(self, ctx: UnifiedContext, new_name: str) -> None:
        if not ctx.guild or not isinstance(ctx.channel, discord.TextChannel):
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not an active ticket.")
            return

        clean_name = new_name.lower().replace(" ", "-")[:100]
        await ctx.channel.edit(name=clean_name)
        await ctx.send_success("Ticket Renamed", f"Channel renamed to `#{clean_name}`.")

    async def _execute_blacklist(self, ctx: UnifiedContext, user: discord.User, reason: str = "Abuse of ticket system") -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        if not ctx.author.guild_permissions.manage_guild and not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Manage Server required.")
            return

        await self.bot.ticket_repo.blacklist_user(ctx.guild.id, user.id, reason, ctx.author.id)
        await ctx.send_success("User Blacklisted", f"Blocked {user.mention} from creating support tickets. Reason: **{reason}**.")

    async def _execute_unblacklist(self, ctx: UnifiedContext, user: discord.User) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        if not ctx.author.guild_permissions.manage_guild and not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "Manage Server required.")
            return

        ok = await self.bot.ticket_repo.unblacklist_user(ctx.guild.id, user.id)
        if ok:
            await ctx.send_success("Blacklist Removed", f"Unblocked {user.mention} from the ticket system.")
        else:
            await ctx.send_error("Not Blacklisted", f"{user.mention} was not blacklisted.")

    async def _execute_export(self, ctx: UnifiedContext) -> None:
        if not ctx.guild or not self.bot.ticket_repo:
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            await ctx.send_error("Not a Ticket", "This channel is not an active ticket.")
            return

        participants = await self.bot.ticket_repo.get_participants(ticket["ticket_id"])
        claimed_str = f"<@{ticket['claimed_by']}>" if ticket.get("claimed_by") else "`Unclaimed`"
        rating_str = f"{ticket['rating']} ⭐" if ticket.get("rating") else "Unrated"
        reason_str = ticket.get("close_reason") or "None"
        embed = EmbedBuilder.base(
            title=f"📋 Ticket Metadata Export • #{ticket['ticket_number']}",
            description=(
                f"**Ticket ID:** `{ticket['ticket_id']}`\n"
                f"**Creator:** <@{ticket['creator_id']}>\n"
                f"**Claimed By:** {claimed_str}\n"
                f"**Status:** `{ticket['status']}`\n"
                f"**Created At:** `{ticket['created_at']}`\n"
                f"**Participants:** {', '.join(f'<@{p}>' for p in participants) if participants else 'None'}\n"
                f"**Close Reason:** {reason_str}\n"
                f"**Rating:** {rating_str}"
            ),
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    # =========================================================
    # SLASH COMMAND GROUP: /ticket <subcommand> (25 subcommands)
    # =========================================================

    @app_commands.command(name="setup", description="Configure server ticket category, staff role, and transcript channel.")
    @app_commands.describe(category="Category for new tickets", staff_role="Support team role", transcript_channel="Channel for closed transcripts")
    async def slash_setup(self, interaction: discord.Interaction, category: Optional[discord.CategoryChannel] = None, staff_role: Optional[discord.Role] = None, transcript_channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_setup(UnifiedContext.from_interaction(interaction), category, staff_role, transcript_channel)

    @app_commands.command(name="panel", description="Deploy an interactive ticket creation embed panel.")
    @app_commands.describe(channel="Target channel for panel", title="Embed title", description="Embed description")
    async def slash_panel(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None, title: str = "Support Tickets", description: str = "Click below to open a ticket.") -> None:
        await self._execute_panel(UnifiedContext.from_interaction(interaction), channel, title, description)

    @app_commands.command(name="create", description="Manually open a new support ticket.")
    @app_commands.describe(category_name="Optional category name")
    async def slash_create(self, interaction: discord.Interaction, category_name: Optional[str] = None) -> None:
        await self._execute_create(UnifiedContext.from_interaction(interaction), category_name)

    @app_commands.command(name="close", description="Close the current support ticket.")
    @app_commands.describe(reason="Reason for closing the ticket")
    async def slash_close(self, interaction: discord.Interaction, reason: Optional[str] = None) -> None:
        await self._execute_close(UnifiedContext.from_interaction(interaction), reason)

    @app_commands.command(name="reopen", description="Reopen a closed support ticket.")
    async def slash_reopen(self, interaction: discord.Interaction) -> None:
        await self._execute_reopen(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="claim", description="Claim responsibility for handling this ticket.")
    async def slash_claim(self, interaction: discord.Interaction) -> None:
        await self._execute_claim(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="unclaim", description="Release your claim on this ticket.")
    async def slash_unclaim(self, interaction: discord.Interaction) -> None:
        await self._execute_unclaim(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="add", description="Add a member to this ticket.")
    @app_commands.describe(member="Member to add")
    async def slash_add(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await self._execute_add(UnifiedContext.from_interaction(interaction), member)

    @app_commands.command(name="remove", description="Remove a member from this ticket.")
    @app_commands.describe(member="Member to remove")
    async def slash_remove(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await self._execute_remove(UnifiedContext.from_interaction(interaction), member)

    @app_commands.command(name="lock", description="Lock this ticket channel.")
    async def slash_lock(self, interaction: discord.Interaction) -> None:
        await self._execute_lock(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="unlock", description="Unlock this ticket channel.")
    async def slash_unlock(self, interaction: discord.Interaction) -> None:
        await self._execute_unlock(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="transcript", description="Generate an HTML transcript of this ticket.")
    async def slash_transcript(self, interaction: discord.Interaction) -> None:
        await self._execute_transcript(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="reason", description="Set or update the note/reason for this ticket.")
    @app_commands.describe(reason="Note or reason")
    async def slash_reason(self, interaction: discord.Interaction, reason: str) -> None:
        await self._execute_reason(UnifiedContext.from_interaction(interaction), reason)

    @app_commands.command(name="category", description="Manage ticket categories.")
    @app_commands.describe(action="add, delete, or list", name="Category name", emoji="Category emoji", description="Category description")
    async def slash_category(self, interaction: discord.Interaction, action: str, name: str = "", emoji: str = "🎫", description: str = "") -> None:
        await self._execute_category(UnifiedContext.from_interaction(interaction), action, name, emoji, description)

    @app_commands.command(name="role", description="Configure the support staff role.")
    @app_commands.describe(role="Role allowed to manage tickets")
    async def slash_role(self, interaction: discord.Interaction, role: discord.Role) -> None:
        await self._execute_role(UnifiedContext.from_interaction(interaction), role)

    @app_commands.command(name="limit", description="Set maximum concurrent tickets per user.")
    @app_commands.describe(limit="Limit between 1 and 10")
    async def slash_limit(self, interaction: discord.Interaction, limit: int) -> None:
        await self._execute_limit(UnifiedContext.from_interaction(interaction), limit)

    @app_commands.command(name="cooldown", description="Set ticket creation cooldown.")
    @app_commands.describe(seconds="Cooldown in seconds")
    async def slash_cooldown(self, interaction: discord.Interaction, seconds: int) -> None:
        await self._execute_cooldown(UnifiedContext.from_interaction(interaction), seconds)

    @app_commands.command(name="stats", description="View server ticket statistics and resolution counts.")
    async def slash_stats(self, interaction: discord.Interaction) -> None:
        await self._execute_stats(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="rating", description="Rate the support received on this ticket (1-5 stars).")
    @app_commands.describe(stars="1 to 5 stars", feedback="Optional feedback note")
    async def slash_rating(self, interaction: discord.Interaction, stars: int, feedback: Optional[str] = None) -> None:
        await self._execute_rating(UnifiedContext.from_interaction(interaction), stars, feedback)

    @app_commands.command(name="logs", description="Set dedicated channel for ticket event logs.")
    @app_commands.describe(channel="Channel for ticket audit logs")
    async def slash_logs(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await self._execute_logs(UnifiedContext.from_interaction(interaction), channel)

    @app_commands.command(name="delete", description="Force delete a ticket channel immediately.")
    async def slash_delete(self, interaction: discord.Interaction) -> None:
        await self._execute_delete(UnifiedContext.from_interaction(interaction))

    @app_commands.command(name="rename", description="Rename a ticket channel.")
    @app_commands.describe(new_name="New channel name")
    async def slash_rename(self, interaction: discord.Interaction, new_name: str) -> None:
        await self._execute_rename(UnifiedContext.from_interaction(interaction), new_name)

    @app_commands.command(name="blacklist", description="Block a user from opening tickets.")
    @app_commands.describe(user="User to block", reason="Reason for blocking")
    async def slash_blacklist(self, interaction: discord.Interaction, user: discord.User, reason: str = "Ticket abuse") -> None:
        await self._execute_blacklist(UnifiedContext.from_interaction(interaction), user, reason)

    @app_commands.command(name="unblacklist", description="Unblock a user from opening tickets.")
    @app_commands.describe(user="User to unblock")
    async def slash_unblacklist(self, interaction: discord.Interaction, user: discord.User) -> None:
        await self._execute_unblacklist(UnifiedContext.from_interaction(interaction), user)

    @app_commands.command(name="export", description="Export ticket metadata and participants.")
    async def slash_export(self, interaction: discord.Interaction) -> None:
        await self._execute_export(UnifiedContext.from_interaction(interaction))

    # =========================================================
    # PREFIX COMMANDS (25 commands)
    # =========================================================

    @commands.command(name="ticketsetup", help="Configure ticket parent category, staff role, and transcript channel.")
    @commands.has_permissions(administrator=True)
    async def prefix_ticketsetup(self, ctx: commands.Context, category: Optional[discord.CategoryChannel] = None, staff_role: Optional[discord.Role] = None, transcript_channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_setup(UnifiedContext.from_prefix(ctx), category, staff_role, transcript_channel)

    @commands.command(name="ticketpanel", help="Deploy ticket creation panel in a channel.")
    @commands.has_permissions(administrator=True)
    async def prefix_ticketpanel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None, *, title: str = "Support Tickets") -> None:
        await self._execute_panel(UnifiedContext.from_prefix(ctx), channel, title)

    @commands.command(name="ticketcreate", help="Create a support ticket manually.")
    async def prefix_ticketcreate(self, ctx: commands.Context, *, category_name: Optional[str] = None) -> None:
        await self._execute_create(UnifiedContext.from_prefix(ctx), category_name)

    @commands.command(name="ticketclose", help="Close the active ticket channel.")
    async def prefix_ticketclose(self, ctx: commands.Context, *, reason: Optional[str] = None) -> None:
        await self._execute_close(UnifiedContext.from_prefix(ctx), reason)

    @commands.command(name="ticketreopen", help="Reopen a closed ticket channel.")
    async def prefix_ticketreopen(self, ctx: commands.Context) -> None:
        await self._execute_reopen(UnifiedContext.from_prefix(ctx))

    @commands.command(name="ticketclaim", help="Claim responsibility for handling this ticket.")
    async def prefix_ticketclaim(self, ctx: commands.Context) -> None:
        await self._execute_claim(UnifiedContext.from_prefix(ctx))

    @commands.command(name="ticketunclaim", help="Release claim on this ticket.")
    async def prefix_ticketunclaim(self, ctx: commands.Context) -> None:
        await self._execute_unclaim(UnifiedContext.from_prefix(ctx))

    @commands.command(name="ticketadd", help="Add a member to the current ticket.")
    async def prefix_ticketadd(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._execute_add(UnifiedContext.from_prefix(ctx), member)

    @commands.command(name="ticketremove", help="Remove a member from the current ticket.")
    async def prefix_ticketremove(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._execute_remove(UnifiedContext.from_prefix(ctx), member)

    @commands.command(name="ticketlock", help="Lock the current ticket channel.")
    async def prefix_ticketlock(self, ctx: commands.Context) -> None:
        await self._execute_lock(UnifiedContext.from_prefix(ctx))

    @commands.command(name="ticketunlock", help="Unlock the current ticket channel.")
    async def prefix_ticketunlock(self, ctx: commands.Context) -> None:
        await self._execute_unlock(UnifiedContext.from_prefix(ctx))

    @commands.command(name="tickettranscript", help="Export an HTML transcript of the current ticket.")
    async def prefix_tickettranscript(self, ctx: commands.Context) -> None:
        await self._execute_transcript(UnifiedContext.from_prefix(ctx))

    @commands.command(name="ticketreason", help="Set the reason or note for this ticket.")
    async def prefix_ticketreason(self, ctx: commands.Context, *, reason: str) -> None:
        await self._execute_reason(UnifiedContext.from_prefix(ctx), reason)

    @commands.command(name="ticketcategory", help="Manage ticket categories (add/delete/list).")
    @commands.has_permissions(administrator=True)
    async def prefix_ticketcategory(self, ctx: commands.Context, action: str, name: str = "", *, description: str = "") -> None:
        await self._execute_category(UnifiedContext.from_prefix(ctx), action, name, description=description)

    @commands.command(name="ticketrole", help="Set the support staff role.")
    @commands.has_permissions(administrator=True)
    async def prefix_ticketrole(self, ctx: commands.Context, role: discord.Role) -> None:
        await self._execute_role(UnifiedContext.from_prefix(ctx), role)

    @commands.command(name="ticketlimit", help="Set max open tickets per user.")
    @commands.has_permissions(administrator=True)
    async def prefix_ticketlimit(self, ctx: commands.Context, limit: int) -> None:
        await self._execute_limit(UnifiedContext.from_prefix(ctx), limit)

    @commands.command(name="ticketcooldown", help="Set cooldown for ticket creation.")
    @commands.has_permissions(administrator=True)
    async def prefix_ticketcooldown(self, ctx: commands.Context, seconds: int) -> None:
        await self._execute_cooldown(UnifiedContext.from_prefix(ctx), seconds)

    @commands.command(name="ticketstats", help="View server ticket statistics.")
    async def prefix_ticketstats(self, ctx: commands.Context) -> None:
        await self._execute_stats(UnifiedContext.from_prefix(ctx))

    @commands.command(name="ticketrating", help="Rate ticket support (1-5 stars).")
    async def prefix_ticketrating(self, ctx: commands.Context, stars: int, *, feedback: Optional[str] = None) -> None:
        await self._execute_rating(UnifiedContext.from_prefix(ctx), stars, feedback)

    @commands.command(name="ticketlogs", help="Set ticket audit logs channel.")
    @commands.has_permissions(administrator=True)
    async def prefix_ticketlogs(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        await self._execute_logs(UnifiedContext.from_prefix(ctx), channel)

    @commands.command(name="ticketdelete", help="Immediately delete ticket channel.")
    @commands.has_permissions(manage_channels=True)
    async def prefix_ticketdelete(self, ctx: commands.Context) -> None:
        await self._execute_delete(UnifiedContext.from_prefix(ctx))

    @commands.command(name="ticketrename", help="Rename the ticket channel.")
    async def prefix_ticketrename(self, ctx: commands.Context, *, new_name: str) -> None:
        await self._execute_rename(UnifiedContext.from_prefix(ctx), new_name)

    @commands.command(name="ticketblacklist", help="Block a user from opening tickets.")
    @commands.has_permissions(manage_guild=True)
    async def prefix_ticketblacklist(self, ctx: commands.Context, user: discord.User, *, reason: str = "Ticket abuse") -> None:
        await self._execute_blacklist(UnifiedContext.from_prefix(ctx), user, reason)

    @commands.command(name="ticketunblacklist", help="Unblock a user from opening tickets.")
    @commands.has_permissions(manage_guild=True)
    async def prefix_ticketunblacklist(self, ctx: commands.Context, user: discord.User) -> None:
        await self._execute_unblacklist(UnifiedContext.from_prefix(ctx), user)

    @commands.command(name="ticketexport", help="Export ticket metadata and participants.")
    async def prefix_ticketexport(self, ctx: commands.Context) -> None:
        await self._execute_export(UnifiedContext.from_prefix(ctx))


async def setup(bot: DeathBot) -> None:
    """Setup hook to register the TicketsCog."""
    await bot.add_cog(TicketsCog(bot))
