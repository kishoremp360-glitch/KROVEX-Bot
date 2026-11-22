"""Interactive persistent views and modals for the support ticket management system."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import discord

from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.tickets.views")
BRAND_COLOR = 0x9D4EDD


class TicketCreateSelect(discord.ui.Select):
    """Dropdown menu for selecting ticket category upon creation."""

    def __init__(self, categories: List[Dict[str, Any]]) -> None:
        options = []
        for cat in categories[:25]:
            options.append(
                discord.SelectOption(
                    label=cat["name"],
                    value=str(cat["id"]),
                    description=cat.get("description", "")[:100] or "Create support ticket",
                    emoji=cat.get("emoji") or "🎫",
                )
            )
        super().__init__(
            placeholder="Select a ticket category...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket:select_category",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        cat_id = int(self.values[0])
        await handle_create_ticket(interaction, cat_id)


class TicketPanelView(discord.ui.View):
    """Persistent panel view displayed in ticket creation channels."""

    def __init__(self, categories: Optional[List[Dict[str, Any]]] = None) -> None:
        super().__init__(timeout=None)
        if categories and len(categories) > 1:
            self.add_item(TicketCreateSelect(categories))
        else:
            btn = discord.ui.Button(
                label="Create Ticket",
                emoji=KrovexEmoji.TICKET.partial,
                style=discord.ButtonStyle.primary,
                custom_id="ticket:create_default",
                row=0,
            )
            btn.callback = self.create_ticket_callback
            self.add_item(btn)

    async def create_ticket_callback(self, interaction: discord.Interaction) -> None:
        await handle_create_ticket(interaction)

    @discord.ui.button(label="Help & Info", emoji="ℹ️", style=discord.ButtonStyle.secondary, custom_id="ticket:info_btn", row=1)
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.TICKET} Ticket Support Information",
            description=(
                "Click the button or select a category above to open a private ticket.\n"
                "• A dedicated channel will be created exclusively for you and support staff.\n"
                "• Please state your question or issue clearly upon opening the ticket.\n"
                "• Inappropriate or spam tickets may result in a support blacklist."
            ),
            color=BRAND_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class TicketActionView(discord.ui.View):
    """Persistent controls placed inside active ticket channels."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Close", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket:action_close")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot: "DeathBot" = interaction.client  # type: ignore
        creator_id = None
        if bot.ticket_repo and interaction.channel:
            t = await bot.ticket_repo.get_ticket_by_channel(interaction.channel.id)
            if t:
                creator_id = t.get("creator_id")
        view = TicketCloseConfirmView(creator_id=creator_id)
        embed = EmbedBuilder.warning(
            title="Close Ticket Confirmation",
            description="Are you sure you want to close this ticket? A transcript will be generated.",
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Claim", emoji="🙋", style=discord.ButtonStyle.success, custom_id="ticket:action_claim")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot: "DeathBot" = interaction.client  # type: ignore
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or not bot.ticket_repo:
            return

        settings = await bot.ticket_repo.get_settings(interaction.guild_id)
        staff_role_id = settings.get("staff_role_id")
        is_staff = interaction.user.guild_permissions.manage_channels or interaction.user.guild_permissions.administrator
        if staff_role_id and isinstance(interaction.user, discord.Member):
            is_staff = is_staff or any(r.id == staff_role_id for r in interaction.user.roles)

        if not is_staff:
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} Only support staff can claim tickets.", ephemeral=True)
            return

        ticket = await bot.ticket_repo.get_ticket_by_channel(channel.id)
        if not ticket:
            await interaction.response.send_message("❌ Ticket record not found.", ephemeral=True)
            return

        if ticket.get("claimed_by"):
            if ticket["claimed_by"] == interaction.user.id:
                # Unclaim
                await bot.ticket_repo.unclaim_ticket(channel.id)
                await channel.send(f"🔓 **{interaction.user.display_name}** released their claim on this ticket.")
                if not interaction.response.is_done():
                    await interaction.response.send_message("Claim released.", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ This ticket is already claimed by <@{ticket['claimed_by']}>.", ephemeral=True)
            return

        await bot.ticket_repo.claim_ticket(channel.id, interaction.user.id)
        embed = EmbedBuilder.success(
            title="Ticket Claimed",
            description=f"This ticket is now being handled by **{interaction.user.mention}**.",
        )
        await channel.send(embed=embed)
        if not interaction.response.is_done():
            await interaction.response.send_message("You have claimed this ticket.", ephemeral=True)

    @discord.ui.button(label="Transcript", emoji="📜", style=discord.ButtonStyle.secondary, custom_id="ticket:action_transcript")
    async def transcript_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return
        from bot.cogs.tickets.transcript import generate_transcript
        file = await generate_transcript(channel)
        await interaction.followup.send("📄 Here is the transcript for this ticket:", file=file, ephemeral=True)


class TicketCloseConfirmView(discord.ui.View):
    """Confirmation view before closing a ticket with strict authorization and double-close protection."""

    def __init__(self, creator_id: Optional[int] = None) -> None:
        super().__init__(timeout=60.0)
        self.creator_id = creator_id
        self._lock = asyncio.Lock()
        self._closed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        bot: "DeathBot" = interaction.client  # type: ignore
        user = interaction.user
        if not isinstance(user, discord.Member):
            return False

        # 1. Server administrators or manage_channels always authorized
        if user.guild_permissions.administrator or user.guild_permissions.manage_channels:
            return True

        # 2. Check creator ID
        resolved_creator_id = self.creator_id
        if resolved_creator_id is None and bot.ticket_repo and interaction.channel_id:
            ticket = await bot.ticket_repo.get_ticket_by_channel(interaction.channel_id)
            if ticket:
                resolved_creator_id = ticket.get("creator_id")
                self.creator_id = resolved_creator_id

        if resolved_creator_id and user.id == resolved_creator_id:
            return True

        # 3. Check staff role from settings
        if bot.ticket_repo and interaction.guild_id:
            settings = await bot.ticket_repo.get_settings(interaction.guild_id)
            staff_role_id = settings.get("staff_role_id") if settings else None
            if staff_role_id and any(r.id == staff_role_id for r in user.roles):
                return True

        await interaction.response.send_message(
            f"{KrovexEmoji.CROSS} Only the ticket creator or authorized support staff can close this ticket.",
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True

    @discord.ui.button(label="Confirm Close", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot: "DeathBot" = interaction.client  # type: ignore
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or not bot.ticket_repo:
            return

        async with self._lock:
            if self._closed:
                await interaction.response.send_message("⚠️ This ticket is already being closed.", ephemeral=True)
                return
            self._closed = True

            for child in self.children:
                if hasattr(child, "disabled"):
                    child.disabled = True

            ticket = await bot.ticket_repo.get_ticket_by_channel(channel.id)
            if not ticket:
                await interaction.response.send_message("❌ This channel is not an active support ticket.", ephemeral=True)
                return
            if ticket.get("status") == "closed":
                await interaction.response.send_message("⚠️ This ticket is already closed.", ephemeral=True)
                return

            await interaction.response.send_message("Closing ticket and saving transcript...", ephemeral=True)
            await bot.ticket_repo.close_ticket(channel.id, interaction.user.id, "Closed by user/staff")

            # Generate transcript and send to transcript channel if configured
            settings = await bot.ticket_repo.get_settings(interaction.guild_id)
            transcript_channel_id = settings.get("transcript_channel_id") if settings else None
            if transcript_channel_id and interaction.guild:
                tch = interaction.guild.get_channel(transcript_channel_id)
                if isinstance(tch, discord.TextChannel):
                    from bot.cogs.tickets.transcript import generate_transcript
                    t_file = await generate_transcript(channel)
                    embed = EmbedBuilder.base(
                        title=f"📁 Ticket Closed: #{channel.name}",
                        description=f"Closed by {interaction.user.mention} | Channel ID: `{channel.id}`",
                        color=BRAND_COLOR,
                    )
                    try:
                        await tch.send(embed=embed, file=t_file)
                    except Exception as e:
                        logger.warning("Could not dispatch transcript: %s", e)

            # Send rating view to ticket creator via central rate-limited DM Queue
            if ticket.get("creator_id") and interaction.guild:
                creator_id = ticket["creator_id"]
                r_embed = EmbedBuilder.base(
                    title="⭐ Rate Your Support Experience",
                    description=f"Your ticket in **{interaction.guild.name}** was closed. Please rate the support provided:",
                    color=BRAND_COLOR,
                )
                queue_service = getattr(bot, "dm_queue_service", None)
                if queue_service and hasattr(queue_service, "enqueue"):
                    res = queue_service.enqueue(
                        recipient_id=creator_id,
                        guild_id=interaction.guild_id,
                        message_type="ticket_rating",
                        embed=r_embed,
                        idempotency_key=f"ticket_rating:{interaction.guild_id}:{channel.id}:{creator_id}",
                        metadata={"channel_id": channel.id, "guild_id": interaction.guild_id, "ticket_id": ticket.get("id") or ticket.get("ticket_id")},
                    )
                    if asyncio.iscoroutine(res):
                        await res
                else:
                    creator = interaction.guild.get_member(creator_id)
                    if creator:
                        try:
                            await creator.send(embed=r_embed, view=TicketRatingView(channel.id, interaction.guild_id))
                        except Exception:
                            pass

            await channel.send("🔒 Ticket closed. Deleting channel in 5 seconds...")
            await asyncio.sleep(5)
            try:
                await channel.delete(reason=f"Ticket closed by {interaction.user}")
            except Exception as e:
                logger.warning("Could not delete ticket channel: %s", e)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji=KrovexEmoji.CROSS.partial)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            self._closed = True
            for child in self.children:
                if hasattr(child, "disabled"):
                    child.disabled = True
            await interaction.response.send_message("Ticket closure cancelled.", ephemeral=True)
            self.stop()


async def _send_rating_interaction_error(interaction: discord.Interaction, message: str) -> None:
    """Send an ephemeral error response where supported, falling back gracefully."""
    if interaction.response.is_done():
        try:
            await interaction.followup.send(message, ephemeral=True)
        except Exception:
            try:
                await interaction.followup.send(message)
            except Exception:
                pass
        return

    try:
        await interaction.response.send_message(message, ephemeral=True)
    except Exception:
        try:
            await interaction.response.send_message(message)
        except Exception:
            try:
                await interaction.followup.send(message, ephemeral=True)
            except Exception:
                pass


async def handle_ticket_rating_interaction(
    interaction: discord.Interaction,
    channel_id: Optional[int] = None,
    stars: Optional[int] = None,
    view: Optional[discord.ui.View] = None,
    bot: Optional[Any] = None,
) -> bool:
    """Authorize and process a ticket rating interaction."""
    if interaction.response.is_done():
        return False

    custom_id = ""
    if hasattr(interaction, "data") and isinstance(interaction.data, dict):
        raw_cid = interaction.data.get("custom_id")
        if isinstance(raw_cid, str):
            custom_id = raw_cid

    # Parse and validate custom_id if channel_id or stars not provided directly
    if channel_id is None or stars is None:
        if not custom_id or not custom_id.startswith("ticket_rate:"):
            return False
        parts = custom_id.split(":")
        if len(parts) != 3:
            await _send_rating_interaction_error(interaction, "❌ Invalid rating interaction.")
            return False
        try:
            channel_id = int(parts[1])
            stars = int(parts[2])
        except (ValueError, TypeError):
            await _send_rating_interaction_error(interaction, "❌ Invalid rating parameters.")
            return False
    else:
        # Validate custom_id against supplied parameters if custom_id is present
        if custom_id and custom_id.startswith("ticket_rate:"):
            parts = custom_id.split(":")
            if len(parts) != 3:
                await _send_rating_interaction_error(interaction, "❌ Invalid rating interaction.")
                return False
            try:
                parsed_ch = int(parts[1])
                parsed_stars = int(parts[2])
                if parsed_ch != channel_id or parsed_stars != stars:
                    await _send_rating_interaction_error(interaction, "❌ Conflicting rating parameters.")
                    return False
            except (ValueError, TypeError):
                await _send_rating_interaction_error(interaction, "❌ Invalid rating parameters.")
                return False

    if stars < 1 or stars > 5:
        await _send_rating_interaction_error(interaction, "❌ Rating must be between 1 and 5 stars.")
        return False

    bot = bot or getattr(interaction, "client", None)
    ticket_repo = getattr(bot, "ticket_repo", None)
    if not ticket_repo:
        await _send_rating_interaction_error(interaction, "❌ Ticket system is temporarily unavailable.")
        return False

    ticket = None
    if hasattr(ticket_repo, "get_ticket_by_channel"):
        res = ticket_repo.get_ticket_by_channel(channel_id)
        if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
            ticket = await res
        else:
            ticket = res

    if not ticket or not isinstance(ticket, dict):
        await _send_rating_interaction_error(interaction, "❌ Ticket record not found.")
        return False

    # Explicit Creator Authorization Check
    try:
        creator_id = int(ticket["creator_id"]) if ticket.get("creator_id") is not None else None
        user_id = int(interaction.user.id) if getattr(interaction, "user", None) and hasattr(interaction.user, "id") else None
    except (ValueError, TypeError):
        creator_id = ticket.get("creator_id")
        user_id = getattr(getattr(interaction, "user", None), "id", None)

    if creator_id is None or user_id != creator_id:
        await _send_rating_interaction_error(interaction, "❌ Only the ticket creator can rate this ticket.")
        return False

    # Duplicate / Existing Rating Policy
    if ticket.get("rating") is not None:
        await _send_rating_interaction_error(interaction, "❌ This ticket has already been rated.")
        return False

    # Update database
    updated = True
    if hasattr(ticket_repo, "set_rating"):
        set_res = ticket_repo.set_rating(channel_id, stars)
        if asyncio.iscoroutine(set_res) or hasattr(set_res, "__await__"):
            updated = await set_res
        elif set_res is not None:
            updated = bool(set_res)

    if updated is False:
        # Check if the ticket was rated concurrently by another submission
        latest_ticket = None
        if hasattr(ticket_repo, "get_ticket_by_channel"):
            check_res = ticket_repo.get_ticket_by_channel(channel_id)
            if asyncio.iscoroutine(check_res) or hasattr(check_res, "__await__"):
                latest_ticket = await check_res
            else:
                latest_ticket = check_res

        if latest_ticket and isinstance(latest_ticket, dict) and latest_ticket.get("rating") is not None:
            await _send_rating_interaction_error(interaction, "❌ This ticket has already been rated.")
        else:
            await _send_rating_interaction_error(interaction, "❌ Failed to record rating. Ticket record may no longer exist.")
        return False

    embed = EmbedBuilder.success(
        title="Thank You for Your Feedback!",
        description=f"You rated this support ticket **{stars} / 5 stars** ({'⭐' * stars}).",
    )
    if not interaction.response.is_done():
        try:
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            logger.warning("Could not edit message after rating: %s", e)

    if view is not None:
        view.stop()

    return True


class TicketRatingView(discord.ui.View):
    """User feedback rating view (1-5 stars) dispatched upon ticket closure."""

    def __init__(self, channel_id: int, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.r1.custom_id = f"ticket_rate:{channel_id}:1"
        self.r2.custom_id = f"ticket_rate:{channel_id}:2"
        self.r3.custom_id = f"ticket_rate:{channel_id}:3"
        self.r4.custom_id = f"ticket_rate:{channel_id}:4"
        self.r5.custom_id = f"ticket_rate:{channel_id}:5"

    async def _handle_rating(self, interaction: discord.Interaction, stars: int) -> None:
        await handle_ticket_rating_interaction(interaction, channel_id=self.channel_id, stars=stars, view=self)

    @discord.ui.button(label="1 ⭐", style=discord.ButtonStyle.secondary)
    async def r1(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_rating(interaction, 1)

    @discord.ui.button(label="2 ⭐", style=discord.ButtonStyle.secondary)
    async def r2(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_rating(interaction, 2)

    @discord.ui.button(label="3 ⭐", style=discord.ButtonStyle.secondary)
    async def r3(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_rating(interaction, 3)

    @discord.ui.button(label="4 ⭐", style=discord.ButtonStyle.secondary)
    async def r4(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_rating(interaction, 4)

    @discord.ui.button(label="5 ⭐", style=discord.ButtonStyle.success)
    async def r5(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_rating(interaction, 5)


async def handle_create_ticket(interaction: discord.Interaction, category_id: Optional[int] = None) -> None:
    """Core logic to instantiate a private ticket channel and register it in SQLite."""
    # Instantly defer interaction within milliseconds to eliminate timeout errors
    if not interaction.response.is_done():
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

    bot: "DeathBot" = interaction.client  # type: ignore
    guild = interaction.guild
    user = interaction.user

    if not guild or not isinstance(user, discord.Member) or not bot.ticket_repo:
        if interaction.response.is_done():
            await interaction.followup.send("❌ Error initializing ticket.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Error initializing ticket.", ephemeral=True)
        return

    # Check blacklist
    if await bot.ticket_repo.is_blacklisted(guild.id, user.id):
        await interaction.followup.send("⛔ You are blacklisted from creating tickets in this server.", ephemeral=True)
        return

    # Check open ticket limits
    settings = await bot.ticket_repo.get_settings(guild.id)
    max_tickets = settings.get("max_tickets_per_user") or 1
    open_tickets = await bot.ticket_repo.get_user_open_tickets(guild.id, user.id)
    if len(open_tickets) >= max_tickets:
        await interaction.followup.send(
            f"❌ You have reached the maximum open ticket limit (`{max_tickets}`) for this server.",
            ephemeral=True,
        )
        return

    # Determine category & permissions
    cat_data = None
    if category_id:
        cat_data = await bot.ticket_repo.get_category(category_id)

    target_discord_cat = None
    if cat_data and cat_data.get("category_channel_id"):
        target_discord_cat = guild.get_channel(cat_data["category_channel_id"])
    elif settings.get("category_id"):
        target_discord_cat = guild.get_channel(settings["category_id"])

    # Smart auto-detection fallback if no category is explicitly assigned
    if not target_discord_cat:
        for c in guild.categories:
            c_name = c.name.lower()
            if any(k in c_name for k in ["ticket", "support", "sᴜᴘᴘᴏʀᴛ", "ᴛɪᴄᴋᴇᴛ"]):
                target_discord_cat = c
                break

    # Build permission overwrites
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
            read_message_history=True,
        ),
        guild.me: discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True,
            manage_channels=True,
            manage_messages=True,
            embed_links=True,
            attach_files=True,
        ),
    }

    staff_role_id = (cat_data.get("staff_role_id") if cat_data else None) or settings.get("staff_role_id")
    if staff_role_id:
        s_role = guild.get_role(staff_role_id)
        if s_role:
            overwrites[s_role] = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True,
            )

    ticket_counter = (settings.get("ticket_counter") or 0) + 1
    naming_scheme = (cat_data.get("naming_scheme") if cat_data else None) or settings.get("naming_scheme") or "ticket-{number}"
    ch_name = naming_scheme.replace("{number}", f"{ticket_counter:04d}").replace("{user}", user.name.lower())

    try:
        channel = await guild.create_text_channel(
            name=ch_name,
            category=target_discord_cat if isinstance(target_discord_cat, discord.CategoryChannel) else None,
            overwrites=overwrites,
            topic=f"Support Ticket for {user.display_name} ({user.id}) | Category: {cat_data['name'] if cat_data else 'General'}",
        )
    except Exception as e:
        logger.error("Failed to create ticket channel: %s", e)
        await interaction.followup.send(f"❌ Failed to create channel: {e}", ephemeral=True)
        return

    # Record in database
    ticket_id = await bot.ticket_repo.create_ticket(guild.id, channel.id, user.id, category_id)

    # Send welcome card into ticket channel
    cat_name = cat_data["name"] if cat_data else "General Support"
    embed = EmbedBuilder.base(
        title=f"{KrovexEmoji.TICKET} Support Ticket #{ticket_counter:04d}",
        description=(
            f"Welcome {user.mention}! Support staff has been notified.\n\n"
            f"**Category:** `{cat_name}`\n"
            "Please describe your issue in detail. You can use the buttons below to manage this ticket."
        ),
        color=BRAND_COLOR,
    )
    embed.set_footer(text="Death Bot • Advanced Ticket Management", icon_url=guild.icon.url if guild.icon else None)

    view = TicketActionView()
    await channel.send(content=f"{user.mention}" + (f" <@&{staff_role_id}>" if staff_role_id else ""), embed=embed, view=view)

    await interaction.followup.send(f"✅ Your ticket has been created: {channel.mention}", ephemeral=True)


async def setup(bot: Any) -> None:
    """Extension dummy setup."""
    pass

