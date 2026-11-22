"""Reaction Roles, Button Panels, and Dropdown Menus Cog for Death Bot."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.reactionroles")
BRAND_COLOR = 0x9D4EDD


class RoleButton(discord.ui.Button):
    """Button representing a single assignable role."""

    def __init__(self, role_id: int, label: str, emoji: Optional[str] = None, style: discord.ButtonStyle = discord.ButtonStyle.primary) -> None:
        super().__init__(label=label, emoji=emoji, style=style, custom_id=f"rr_btn_{role_id}")
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        role = guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("❌ This role no longer exists.", ephemeral=True)
            return

        if guild.me.top_role.position <= role.position:
            await interaction.response.send_message("❌ I cannot manage this role due to role hierarchy.", ephemeral=True)
            return

        if role in interaction.user.roles:
            try:
                await interaction.user.remove_roles(role, reason="Reaction Role Button toggle")
                await interaction.response.send_message(f"➖ Removed {role.mention}.", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"❌ Failed to remove role: {e}", ephemeral=True)
        else:
            try:
                await interaction.user.add_roles(role, reason="Reaction Role Button toggle")
                await interaction.response.send_message(f"➕ Granted {role.mention}!", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"❌ Failed to grant role: {e}", ephemeral=True)


class RoleSelect(discord.ui.Select):
    """Dropdown menu for selecting one or more roles."""

    def __init__(self, placeholder: str, options: List[discord.SelectOption], max_values: int = 1) -> None:
        super().__init__(placeholder=placeholder, min_values=0, max_values=max_values, options=options, custom_id="rr_select_menu")

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return

        selected_role_ids = {int(v) for v in self.values}
        added, removed = [], []

        for opt in self.options:
            r_id = int(opt.value)
            role = guild.get_role(r_id)
            if not role or guild.me.top_role.position <= role.position:
                continue

            if r_id in selected_role_ids and role not in interaction.user.roles:
                try:
                    await interaction.user.add_roles(role, reason="Role Dropdown Selection")
                    added.append(role.name)
                except Exception:
                    pass
            elif r_id not in selected_role_ids and role in interaction.user.roles:
                try:
                    await interaction.user.remove_roles(role, reason="Role Dropdown Deselection")
                    removed.append(role.name)
                except Exception:
                    pass

        msg = []
        if added:
            msg.append(f"➕ Granted: {', '.join(added)}")
        if removed:
            msg.append(f"➖ Removed: {', '.join(removed)}")
        if not msg:
            msg.append("No changes applied.")

        await interaction.response.send_message("\n".join(msg), ephemeral=True)


class ReactionRoles(commands.GroupCog, group_name="rr", group_description="Reaction roles, button panels, and menu roles"):
    """Comprehensive reaction role, button panel, and dropdown role administration."""

    def __init__(self, bot: "DeathBot") -> None:
        super().__init__()
        self.bot = bot

    # ── 1. rrcreate ─────────────────────────────────────────────────────────

    async def _execute_rrcreate(self, ctx: UnifiedContext, channel: discord.TextChannel, message_id: int, emoji: str, role: discord.Role) -> None:
        if not ctx.guild:
            return
        if ctx.guild.me.top_role.position <= role.position:
            await ctx.send_error("Hierarchy Error", "The bot's highest role must be higher than the target role.")
            return

        try:
            msg = await channel.fetch_message(message_id)
            await msg.add_reaction(emoji)
        except discord.NotFound:
            await ctx.send_error("Message Not Found", f"Could not find message ID `{message_id}` in {channel.mention}.")
            return
        except Exception as e:
            await ctx.send_error("Failed to Add Reaction", str(e))
            return

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO reaction_roles (guild_id, channel_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?, ?)",
            (ctx.guild.id, channel.id, message_id, emoji, role.id),
        )
        await ctx.send_success("Reaction Role Created", f"Bound {emoji} to {role.mention} on message `{message_id}`.")

    @commands.command(name="rrcreate", help="Create a classic reaction role on an existing message.")
    @commands.has_permissions(manage_roles=True)
    async def rrcreate_prefix(self, ctx: commands.Context, channel: discord.TextChannel, message_id: int, emoji: str, role: discord.Role) -> None:
        await self._execute_rrcreate(UnifiedContext.from_prefix(ctx), channel, message_id, emoji, role)

    @app_commands.command(name="create", description="Create a classic reaction role on an existing message.")
    @app_commands.describe(channel="Target channel", message_id="Message ID", emoji="Emoji to react with", role="Role to assign")
    @app_commands.default_permissions(manage_roles=True)
    async def rrcreate_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, message_id: str, emoji: str, role: discord.Role) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid Message ID.", ephemeral=True)
            return
        await self._execute_rrcreate(UnifiedContext.from_interaction(interaction), channel, mid, emoji, role)

    # ── 2. rrremove ─────────────────────────────────────────────────────────

    async def _execute_rrremove(self, ctx: UnifiedContext, channel: discord.TextChannel, message_id: int, emoji: str) -> None:
        if not ctx.guild:
            return
        cursor = await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND channel_id = ? AND message_id = ? AND emoji = ?",
            (ctx.guild.id, channel.id, message_id, emoji),
        )
        if cursor.rowcount > 0:
            try:
                msg = await channel.fetch_message(message_id)
                await msg.clear_reaction(emoji)
            except Exception:
                pass
            await ctx.send_success("Reaction Role Removed", f"Unbound {emoji} from message `{message_id}`.")
        else:
            await ctx.send_error("Not Found", "No reaction role matching that emoji was found on that message.")

    @commands.command(name="rrremove", aliases=["rrdel"], help="Remove a reaction role mapping from a message.")
    @commands.has_permissions(manage_roles=True)
    async def rrremove_prefix(self, ctx: commands.Context, channel: discord.TextChannel, message_id: int, emoji: str) -> None:
        await self._execute_rrremove(UnifiedContext.from_prefix(ctx), channel, message_id, emoji)

    @app_commands.command(name="remove", description="Remove a reaction role mapping.")
    @app_commands.describe(channel="Channel", message_id="Message ID", emoji="Emoji")
    @app_commands.default_permissions(manage_roles=True)
    async def rrremove_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, message_id: str, emoji: str) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid Message ID.", ephemeral=True)
            return
        await self._execute_rrremove(UnifiedContext.from_interaction(interaction), channel, mid, emoji)

    # ── 3. rrbuttonpanel ────────────────────────────────────────────────────

    async def _execute_rrbuttonpanel(self, ctx: UnifiedContext, channel: discord.TextChannel, title: str, description: str) -> None:
        if not ctx.guild:
            return
        embed = EmbedBuilder.base(
            title=f"🔘 {title}",
            description=description,
            color=BRAND_COLOR,
            footer_text="Click the buttons below to toggle your roles",
        )
        msg = await channel.send(embed=embed)
        if self.bot.rr_repo:
            await self.bot.rr_repo.create_panel(
                message_id=msg.id,
                guild_id=ctx.guild.id,
                channel_id=channel.id,
                panel_type="button",
                title=title,
                description=description,
            )
        await ctx.send_success("Button Panel Created", f"Created button role panel in {channel.mention} with Message ID `{msg.id}`. Use `!rrbuttonadd {msg.id} <label> <role>` to add buttons.")

    @commands.command(name="rrbuttonpanel", help="Create a new button-based role panel.")
    @commands.has_permissions(manage_roles=True)
    async def rrbuttonpanel_prefix(self, ctx: commands.Context, channel: discord.TextChannel, title: str, *, description: str) -> None:
        await self._execute_rrbuttonpanel(UnifiedContext.from_prefix(ctx), channel, title, description)

    @app_commands.command(name="buttonpanel", description="Create a new button-based role panel.")
    @app_commands.describe(channel="Target channel", title="Panel title", description="Panel instructions")
    @app_commands.default_permissions(manage_roles=True)
    async def rrbuttonpanel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, title: str, description: str) -> None:
        await self._execute_rrbuttonpanel(UnifiedContext.from_interaction(interaction), channel, title, description)

    # ── 4. rrbuttonadd ──────────────────────────────────────────────────────

    async def _execute_rrbuttonadd(self, ctx: UnifiedContext, message_id: int, label: str, role: discord.Role, emoji: Optional[str] = None, style: str = "primary") -> None:
        if not ctx.guild:
            return
        panel = await self.bot.rr_repo.get_panel(message_id) if self.bot.rr_repo else None
        if not panel:
            await ctx.send_error("Panel Not Found", f"No panel found with Message ID `{message_id}`.")
            return

        if self.bot.rr_repo:
            await self.bot.rr_repo.add_item(
                message_id=message_id,
                guild_id=ctx.guild.id,
                role_id=role.id,
                emoji=emoji,
                label=label,
                style=style,
            )

        # Refresh panel
        await self._refresh_panel_ui(ctx.guild, panel["channel_id"], message_id)
        await ctx.send_success("Button Added", f"Added button **{label}** for {role.mention} to panel `{message_id}`.")

    async def _refresh_panel_ui(self, guild: discord.Guild, channel_id: int, message_id: int) -> None:
        ch = guild.get_channel(channel_id)
        if not isinstance(ch, discord.TextChannel):
            return
        panel = await self.bot.rr_repo.get_panel(message_id) if self.bot.rr_repo else None
        if not panel:
            return
        items = await self.bot.rr_repo.get_items(message_id) if self.bot.rr_repo else []

        embed = EmbedBuilder.base(
            title=f"🔘 {panel['title']}",
            description=panel["description"],
            color=BRAND_COLOR,
            footer_text="Click below to select your roles",
        )

        view = discord.ui.View(timeout=None)
        if panel["panel_type"] == "button":
            for it in items[:25]:
                style_map = {
                    "primary": discord.ButtonStyle.primary,
                    "secondary": discord.ButtonStyle.secondary,
                    "success": discord.ButtonStyle.success,
                    "danger": discord.ButtonStyle.danger,
                }
                b_style = style_map.get(it.get("style", "primary"), discord.ButtonStyle.primary)
                btn = RoleButton(role_id=it["role_id"], label=it["label"] or "Role", emoji=it.get("emoji"), style=b_style)
                view.add_item(btn)
        elif panel["panel_type"] == "menu":
            opts = []
            for it in items[:25]:
                role = guild.get_role(it["role_id"])
                opts.append(discord.SelectOption(label=it["label"] or (role.name if role else "Role"), value=str(it["role_id"]), description=it.get("description"), emoji=it.get("emoji")))
            if opts:
                view.add_item(RoleSelect(placeholder="Choose your roles...", options=opts, max_values=len(opts)))

        try:
            msg = await ch.fetch_message(message_id)
            await msg.edit(embed=embed, view=view)
        except Exception as e:
            logger.warning("Could not refresh panel UI for %s: %s", message_id, e)

    @commands.command(name="rrbuttonadd", help="Add a button to an existing button panel.")
    @commands.has_permissions(manage_roles=True)
    async def rrbuttonadd_prefix(self, ctx: commands.Context, message_id: int, label: str, role: discord.Role, emoji: Optional[str] = None, style: str = "primary") -> None:
        await self._execute_rrbuttonadd(UnifiedContext.from_prefix(ctx), message_id, label, role, emoji, style)

    @app_commands.command(name="buttonadd", description="Add a button to an existing button panel.")
    @app_commands.describe(message_id="Panel message ID", label="Button text", role="Role to give", emoji="Optional emoji", style="primary, secondary, success, danger")
    @app_commands.default_permissions(manage_roles=True)
    async def rrbuttonadd_slash(self, interaction: discord.Interaction, message_id: str, label: str, role: discord.Role, emoji: Optional[str] = None, style: str = "primary") -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid Message ID.", ephemeral=True)
            return
        await self._execute_rrbuttonadd(UnifiedContext.from_interaction(interaction), mid, label, role, emoji, style)

    # ── 5. rrbuttonremove ───────────────────────────────────────────────────

    async def _execute_rrbuttonremove(self, ctx: UnifiedContext, message_id: int, role: discord.Role) -> None:
        if not ctx.guild:
            return
        panel = await self.bot.rr_repo.get_panel(message_id) if self.bot.rr_repo else None
        if not panel:
            await ctx.send_error("Panel Not Found", f"No panel found with Message ID `{message_id}`.")
            return

        if self.bot.rr_repo:
            removed = await self.bot.rr_repo.remove_item(message_id, role.id)
            if removed:
                await self._refresh_panel_ui(ctx.guild, panel["channel_id"], message_id)
                await ctx.send_success("Button Removed", f"Removed role {role.mention} from panel `{message_id}`.")
            else:
                await ctx.send_error("Not Found", f"Role {role.mention} was not found on panel `{message_id}`.")

    @commands.command(name="rrbuttonremove", aliases=["rrbuttondel"], help="Remove a button from a panel.")
    @commands.has_permissions(manage_roles=True)
    async def rrbuttonremove_prefix(self, ctx: commands.Context, message_id: int, role: discord.Role) -> None:
        await self._execute_rrbuttonremove(UnifiedContext.from_prefix(ctx), message_id, role)

    @app_commands.command(name="buttonremove", description="Remove a button from a panel.")
    @app_commands.describe(message_id="Panel message ID", role="Role to remove")
    @app_commands.default_permissions(manage_roles=True)
    async def rrbuttonremove_slash(self, interaction: discord.Interaction, message_id: str, role: discord.Role) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid Message ID.", ephemeral=True)
            return
        await self._execute_rrbuttonremove(UnifiedContext.from_interaction(interaction), mid, role)

    # ── 6. rrmenucreate ─────────────────────────────────────────────────────

    async def _execute_rrmenucreate(self, ctx: UnifiedContext, channel: discord.TextChannel, title: str, description: str) -> None:
        if not ctx.guild:
            return
        embed = EmbedBuilder.base(
            title=f"📋 {title}",
            description=description,
            color=BRAND_COLOR,
            footer_text="Select your roles from the dropdown menu below",
        )
        msg = await channel.send(embed=embed)
        if self.bot.rr_repo:
            await self.bot.rr_repo.create_panel(
                message_id=msg.id,
                guild_id=ctx.guild.id,
                channel_id=channel.id,
                panel_type="menu",
                title=title,
                description=description,
            )
        await ctx.send_success("Menu Panel Created", f"Created select-menu panel in {channel.mention} with Message ID `{msg.id}`. Use `!rrmenuadd {msg.id} <label> <role>` to add options.")

    @commands.command(name="rrmenucreate", help="Create a dropdown menu role panel.")
    @commands.has_permissions(manage_roles=True)
    async def rrmenucreate_prefix(self, ctx: commands.Context, channel: discord.TextChannel, title: str, *, description: str) -> None:
        await self._execute_rrmenucreate(UnifiedContext.from_prefix(ctx), channel, title, description)

    @app_commands.command(name="menucreate", description="Create a dropdown menu role panel.")
    @app_commands.describe(channel="Target channel", title="Menu title", description="Menu instructions")
    @app_commands.default_permissions(manage_roles=True)
    async def rrmenucreate_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, title: str, description: str) -> None:
        await self._execute_rrmenucreate(UnifiedContext.from_interaction(interaction), channel, title, description)

    # ── 7. rrmenuadd ────────────────────────────────────────────────────────

    async def _execute_rrmenuadd(self, ctx: UnifiedContext, message_id: int, label: str, role: discord.Role, description: Optional[str] = None, emoji: Optional[str] = None) -> None:
        if not ctx.guild:
            return
        panel = await self.bot.rr_repo.get_panel(message_id) if self.bot.rr_repo else None
        if not panel:
            await ctx.send_error("Panel Not Found", f"No panel found with Message ID `{message_id}`.")
            return

        if self.bot.rr_repo:
            await self.bot.rr_repo.add_item(
                message_id=message_id,
                guild_id=ctx.guild.id,
                role_id=role.id,
                emoji=emoji,
                label=label,
                description=description,
            )
        await self._refresh_panel_ui(ctx.guild, panel["channel_id"], message_id)
        await ctx.send_success("Menu Option Added", f"Added option **{label}** for {role.mention} to menu `{message_id}`.")

    @commands.command(name="rrmenuadd", help="Add an option to a dropdown role menu.")
    @commands.has_permissions(manage_roles=True)
    async def rrmenuadd_prefix(self, ctx: commands.Context, message_id: int, label: str, role: discord.Role, description: Optional[str] = None, emoji: Optional[str] = None) -> None:
        await self._execute_rrmenuadd(UnifiedContext.from_prefix(ctx), message_id, label, role, description, emoji)

    @app_commands.command(name="menuadd", description="Add an option to a dropdown role menu.")
    @app_commands.describe(message_id="Panel message ID", label="Option label", role="Role to assign", description="Short explanation", emoji="Optional emoji")
    @app_commands.default_permissions(manage_roles=True)
    async def rrmenuadd_slash(self, interaction: discord.Interaction, message_id: str, label: str, role: discord.Role, description: Optional[str] = None, emoji: Optional[str] = None) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid Message ID.", ephemeral=True)
            return
        await self._execute_rrmenuadd(UnifiedContext.from_interaction(interaction), mid, label, role, description, emoji)

    # ── 8. rrmenuremove ─────────────────────────────────────────────────────

    async def _execute_rrmenuremove(self, ctx: UnifiedContext, message_id: int, role: discord.Role) -> None:
        await self._execute_rrbuttonremove(ctx, message_id, role)

    @commands.command(name="rrmenuremove", help="Remove an option from a dropdown role menu.")
    @commands.has_permissions(manage_roles=True)
    async def rrmenuremove_prefix(self, ctx: commands.Context, message_id: int, role: discord.Role) -> None:
        await self._execute_rrmenuremove(UnifiedContext.from_prefix(ctx), message_id, role)

    @app_commands.command(name="menuremove", description="Remove an option from a dropdown role menu.")
    @app_commands.describe(message_id="Panel message ID", role="Role to remove")
    @app_commands.default_permissions(manage_roles=True)
    async def rrmenuremove_slash(self, interaction: discord.Interaction, message_id: str, role: discord.Role) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid Message ID.", ephemeral=True)
            return
        await self._execute_rrmenuremove(UnifiedContext.from_interaction(interaction), mid, role)

    # ── 9. rrlist ───────────────────────────────────────────────────────────

    async def _execute_rrlist(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            return
        panels = await self.bot.rr_repo.get_panels(ctx.guild.id) if self.bot.rr_repo else []
        classic = await self.bot.db.fetchall("SELECT * FROM reaction_roles WHERE guild_id = ?", (ctx.guild.id,))

        if not panels and not classic:
            await ctx.send_error("No Panels", "No reaction role or button panels configured in this server.")
            return

        embed = EmbedBuilder.base(
            title=f"🔘 Active Role Panels • {ctx.guild.name}",
            description=f"Total Panels: **{len(panels)}** | Classic Mappings: **{len(classic)}**",
            color=BRAND_COLOR,
        )
        for p in panels[:10]:
            items = await self.bot.rr_repo.get_items(p["message_id"]) if self.bot.rr_repo else []
            embed.add_field(
                name=f"{'🔘 Button' if p['panel_type'] == 'button' else '📋 Menu'}: {p['title']}",
                value=f"Channel: <#{p['channel_id']}>\nMessage ID: `{p['message_id']}`\nOptions: **{len(items)}**",
                inline=True,
            )
        await ctx.reply(embed=embed)

    @commands.command(name="rrlist", help="List all reaction and button role panels.")
    async def rrlist_prefix(self, ctx: commands.Context) -> None:
        await self._execute_rrlist(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="list", description="List all reaction and button role panels.")
    async def rrlist_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_rrlist(UnifiedContext.from_interaction(interaction))

    # ── 10. rrdelete ────────────────────────────────────────────────────────

    async def _execute_rrdelete(self, ctx: UnifiedContext, message_id: int) -> None:
        if not ctx.guild:
            return
        if self.bot.rr_repo:
            deleted = await self.bot.rr_repo.delete_panel(message_id)
            if deleted:
                await ctx.send_success("Panel Deleted", f"Role panel `{message_id}` and its mappings were removed from database.")
            else:
                await ctx.send_error("Not Found", f"No role panel with Message ID `{message_id}` found.")

    @commands.command(name="rrdelete", help="Delete a role panel and its configuration.")
    @commands.has_permissions(manage_roles=True)
    async def rrdelete_prefix(self, ctx: commands.Context, message_id: int) -> None:
        await self._execute_rrdelete(UnifiedContext.from_prefix(ctx), message_id)

    @app_commands.command(name="delete", description="Delete a role panel.")
    @app_commands.describe(message_id="Panel message ID to delete")
    @app_commands.default_permissions(manage_roles=True)
    async def rrdelete_slash(self, interaction: discord.Interaction, message_id: str) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid Message ID.", ephemeral=True)
            return
        await self._execute_rrdelete(UnifiedContext.from_interaction(interaction), mid)

    # ── 11. rredit ──────────────────────────────────────────────────────────

    async def _execute_rredit(self, ctx: UnifiedContext, message_id: int, field: str, value: str) -> None:
        if not ctx.guild:
            return
        field = field.lower()
        if field not in ("title", "description"):
            await ctx.send_error("Invalid Field", "Only `title` or `description` can be edited.")
            return

        panel = await self.bot.rr_repo.get_panel(message_id) if self.bot.rr_repo else None
        if not panel:
            await ctx.send_error("Not Found", f"No panel found with Message ID `{message_id}`.")
            return

        if self.bot.rr_repo:
            await self.bot.rr_repo.update_panel(message_id, **{field: value})
        await self._refresh_panel_ui(ctx.guild, panel["channel_id"], message_id)
        await ctx.send_success("Panel Updated", f"Updated **{field}** of panel `{message_id}`.")

    @commands.command(name="rredit", help="Edit the title or description of an existing panel.")
    @commands.has_permissions(manage_roles=True)
    async def rredit_prefix(self, ctx: commands.Context, message_id: int, field: str, *, value: str) -> None:
        await self._execute_rredit(UnifiedContext.from_prefix(ctx), message_id, field, value)

    @app_commands.command(name="edit", description="Edit panel title or description.")
    @app_commands.describe(message_id="Panel message ID", field="Field to edit (title, description)", value="New text value")
    @app_commands.default_permissions(manage_roles=True)
    async def rredit_slash(self, interaction: discord.Interaction, message_id: str, field: str, value: str) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid Message ID.", ephemeral=True)
            return
        await self._execute_rredit(UnifiedContext.from_interaction(interaction), mid, field, value)

    # ── 12. rrlimit ─────────────────────────────────────────────────────────

    async def _execute_rrlimit(self, ctx: UnifiedContext, message_id: int, max_roles: int) -> None:
        if not ctx.guild:
            return
        if not (0 <= max_roles <= 25):
            await ctx.send_error("Invalid Limit", "Role limit must be between 0 (unlimited) and 25.")
            return

        if self.bot.rr_repo:
            await self.bot.rr_repo.update_panel(message_id, max_roles=max_roles)
        limit_str = f"**{max_roles}**" if max_roles > 0 else "Unlimited"
        await ctx.send_success("Role Limit Set", f"Max roles from panel `{message_id}` set to: {limit_str}.")

    @commands.command(name="rrlimit", help="Set the maximum number of roles a user can choose from a panel.")
    @commands.has_permissions(manage_roles=True)
    async def rrlimit_prefix(self, ctx: commands.Context, message_id: int, max_roles: int) -> None:
        await self._execute_rrlimit(UnifiedContext.from_prefix(ctx), message_id, max_roles)

    @app_commands.command(name="limit", description="Set maximum roles per user on a panel.")
    @app_commands.describe(message_id="Panel message ID", max_roles="Max roles (0 for unlimited)")
    @app_commands.default_permissions(manage_roles=True)
    async def rrlimit_slash(self, interaction: discord.Interaction, message_id: str, max_roles: int) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid Message ID.", ephemeral=True)
            return
        await self._execute_rrlimit(UnifiedContext.from_interaction(interaction), mid, max_roles)

    # ── 13. rrexclusive ─────────────────────────────────────────────────────

    async def _execute_rrexclusive(self, ctx: UnifiedContext, message_id: int, toggle: str) -> None:
        if not ctx.guild:
            return
        enable = toggle.lower() in ("enable", "true", "on", "yes", "1")
        if self.bot.rr_repo:
            await self.bot.rr_repo.update_panel(message_id, exclusive=1 if enable else 0)
        status = "ENABLED (selecting one role will remove others)" if enable else "DISABLED"
        await ctx.send_success("Exclusive Mode Updated", f"Exclusive mode for panel `{message_id}` is now **{status}**.")

    @commands.command(name="rrexclusive", help="Toggle mutually-exclusive mode for a panel.")
    @commands.has_permissions(manage_roles=True)
    async def rrexclusive_prefix(self, ctx: commands.Context, message_id: int, toggle: str) -> None:
        await self._execute_rrexclusive(UnifiedContext.from_prefix(ctx), message_id, toggle)

    @app_commands.command(name="exclusive", description="Toggle mutually-exclusive mode on a panel.")
    @app_commands.describe(message_id="Panel message ID", toggle="enable or disable")
    @app_commands.default_permissions(manage_roles=True)
    async def rrexclusive_slash(self, interaction: discord.Interaction, message_id: str, toggle: str) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid Message ID.", ephemeral=True)
            return
        await self._execute_rrexclusive(UnifiedContext.from_interaction(interaction), mid, toggle)

    # ── 14. rrrequiredrole ──────────────────────────────────────────────────

    async def _execute_rrrequiredrole(self, ctx: UnifiedContext, message_id: int, role: Optional[discord.Role] = None) -> None:
        if not ctx.guild:
            return
        role_id = role.id if role else None
        if self.bot.rr_repo:
            await self.bot.rr_repo.update_panel(message_id, required_role_id=role_id)
        req_str = f"Must have {role.mention}" if role else "No prerequisite role"
        await ctx.send_success("Requirement Updated", f"Access requirement for panel `{message_id}` set to: {req_str}.")

    @commands.command(name="rrrequiredrole", help="Set a prerequisite role required to use a panel.")
    @commands.has_permissions(manage_roles=True)
    async def rrrequiredrole_prefix(self, ctx: commands.Context, message_id: int, role: Optional[discord.Role] = None) -> None:
        await self._execute_rrrequiredrole(UnifiedContext.from_prefix(ctx), message_id, role)

    @app_commands.command(name="requiredrole", description="Set prerequisite role required to use a panel.")
    @app_commands.describe(message_id="Panel message ID", role="Prerequisite role (empty to remove)")
    @app_commands.default_permissions(manage_roles=True)
    async def rrrequiredrole_slash(self, interaction: discord.Interaction, message_id: str, role: Optional[discord.Role] = None) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid Message ID.", ephemeral=True)
            return
        await self._execute_rrrequiredrole(UnifiedContext.from_interaction(interaction), mid, role)

    # ── 15. rrrefresh ───────────────────────────────────────────────────────

    async def _execute_rrrefresh(self, ctx: UnifiedContext, message_id: int) -> None:
        if not ctx.guild:
            return
        panel = await self.bot.rr_repo.get_panel(message_id) if self.bot.rr_repo else None
        if not panel:
            await ctx.send_error("Not Found", f"No panel found with Message ID `{message_id}`.")
            return

        await self._refresh_panel_ui(ctx.guild, panel["channel_id"], message_id)
        await ctx.send_success("Panel Refreshed", f"Re-rendered components and embed for panel `{message_id}`.")

    @commands.command(name="rrrefresh", help="Force refresh and re-render a role panel.")
    @commands.has_permissions(manage_roles=True)
    async def rrrefresh_prefix(self, ctx: commands.Context, message_id: int) -> None:
        await self._execute_rrrefresh(UnifiedContext.from_prefix(ctx), message_id)

    @app_commands.command(name="refresh", description="Force refresh a role panel.")
    @app_commands.describe(message_id="Panel message ID")
    @app_commands.default_permissions(manage_roles=True)
    async def rrrefresh_slash(self, interaction: discord.Interaction, message_id: str) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid Message ID.", ephemeral=True)
            return
        await self._execute_rrrefresh(UnifiedContext.from_interaction(interaction), mid)

    # ── 16. rrlogs ──────────────────────────────────────────────────────────

    async def _execute_rrlogs(self, ctx: UnifiedContext, limit: int = 10) -> None:
        if not ctx.guild:
            return
        limit = min(max(1, limit), 25)
        logs = await self.bot.db.fetchall(
            "SELECT * FROM audit_event_logs WHERE guild_id = ? AND event_type LIKE 'rr_%' ORDER BY timestamp DESC LIMIT ?",
            (ctx.guild.id, limit),
        )
        if not logs:
            await ctx.send_error("No Logs", "No reaction role assignment logs recorded yet.")
            return

        lines = [f"`{l['timestamp'][:19]}` • <@{l['actor_id']}>: {l['details']}" for l in logs]
        embed = EmbedBuilder.base(
            title=f"📜 Reaction Role Logs • {ctx.guild.name}",
            description="\n".join(lines),
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    @commands.command(name="rrlogs", help="View recent reaction/button role assignments.")
    @commands.has_permissions(manage_roles=True)
    async def rrlogs_prefix(self, ctx: commands.Context, limit: int = 10) -> None:
        await self._execute_rrlogs(UnifiedContext.from_prefix(ctx), limit)

    @app_commands.command(name="logs", description="View recent reaction role logs.")
    @app_commands.describe(limit="Number of entries to fetch (max 25)")
    @app_commands.default_permissions(manage_roles=True)
    async def rrlogs_slash(self, interaction: discord.Interaction, limit: int = 10) -> None:
        await self._execute_rrlogs(UnifiedContext.from_interaction(interaction), limit)

    # ── Event Listeners ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == self.bot.user.id or not payload.guild_id:
            return
        emoji_str = str(payload.emoji)
        row = await self.bot.db.fetchone(
            "SELECT role_id FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (payload.guild_id, payload.message_id, emoji_str),
        )
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = payload.member or guild.get_member(payload.user_id)
        role = guild.get_role(row["role_id"])
        if member and role and guild.me.top_role.position > role.position:
            try:
                await member.add_roles(role, reason="Reaction Role Add")
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id:
            return
        emoji_str = str(payload.emoji)
        row = await self.bot.db.fetchone(
            "SELECT role_id FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (payload.guild_id, payload.message_id, emoji_str),
        )
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        role = guild.get_role(row["role_id"])
        if member and role and guild.me.top_role.position > role.position:
            try:
                await member.remove_roles(role, reason="Reaction Role Remove")
            except Exception:
                pass


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(ReactionRoles(bot))
