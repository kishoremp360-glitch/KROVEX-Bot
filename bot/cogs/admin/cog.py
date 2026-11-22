"""Server Administration and Governance Cog for Death Bot."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional, Union

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.admin")
BRAND_COLOR = 0x9D4EDD


def _parse_color(hex_str: Optional[str]) -> Optional[discord.Color]:
    """Parse a hex string into a discord.Color."""
    if not hex_str:
        return None
    cleaned = hex_str.strip().lstrip("#")
    try:
        val = int(cleaned, 16)
        return discord.Color(val)
    except ValueError:
        return None


class ServerAdmin(commands.GroupCog, group_name="admin", group_description="Server administration and governance commands"):
    """Core server management, role administration, channel operations, and governance."""

    def __init__(self, bot: "DeathBot") -> None:
        super().__init__()
        self.bot = bot

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _can_manage_role(self, actor: discord.Member, target_role: discord.Role, guild: discord.Guild) -> bool:
        """Check if actor and bot can manage the target role based on hierarchy."""
        if actor.id == guild.owner_id:
            return guild.me.top_role > target_role
        return actor.top_role > target_role and guild.me.top_role > target_role

    # ── 1. setprefix ────────────────────────────────────────────────────────

    async def _execute_setprefix(self, ctx: UnifiedContext, prefix: str) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        prefix = prefix.strip()
        if not (1 <= len(prefix) <= 5):
            await ctx.send_error("Invalid Prefix", "Prefix must be between 1 and 5 characters.")
            return
        if self.bot.admin_repo:
            await self.bot.admin_repo.set_prefix(ctx.guild.id, prefix)
        else:
            await self.bot.db.execute(
                "INSERT INTO guild_settings (guild_id, prefix) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET prefix = ?",
                (ctx.guild.id, prefix, prefix),
            )
        await ctx.send_success("Prefix Updated", f"Server command prefix set to: `{prefix}`")

    @commands.command(name="setprefix", help="Change the bot command prefix for this server.")
    @commands.has_permissions(administrator=True)
    async def setprefix_prefix(self, ctx: commands.Context, prefix: str) -> None:
        await self._execute_setprefix(UnifiedContext.from_prefix(ctx), prefix)

    @app_commands.command(name="prefix", description="Change the bot command prefix for this server.")
    @app_commands.describe(prefix="New prefix string (1-5 characters)")
    @app_commands.default_permissions(administrator=True)
    async def prefix_slash(self, interaction: discord.Interaction, prefix: str) -> None:
        await self._execute_setprefix(UnifiedContext.from_interaction(interaction), prefix)

    # ── 2. channelcreate ────────────────────────────────────────────────────

    async def _execute_channelcreate(self, ctx: UnifiedContext, name: str, channel_type: str = "text") -> None:
        if not ctx.guild:
            return
        channel_type = channel_type.lower()
        try:
            if channel_type in ("voice", "vc"):
                ch = await ctx.guild.create_voice_channel(name=name, reason=f"Created by {ctx.author}")
                await ctx.send_success("Channel Created", f"Voice channel {ch.mention} (`{ch.name}`) created successfully.")
            elif channel_type in ("stage", "stagechannel"):
                ch = await ctx.guild.create_stage_channel(name=name, reason=f"Created by {ctx.author}")
                await ctx.send_success("Channel Created", f"Stage channel {ch.mention} (`{ch.name}`) created successfully.")
            else:
                ch = await ctx.guild.create_text_channel(name=name, reason=f"Created by {ctx.author}")
                await ctx.send_success("Channel Created", f"Text channel {ch.mention} (`{ch.name}`) created successfully.")
        except discord.Forbidden:
            await ctx.send_error("Permission Missing", "I do not have `Manage Channels` permission.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="channelcreate", aliases=["chcreate", "createchannel"], help="Create a text, voice, or stage channel.")
    @commands.has_permissions(manage_channels=True)
    async def channelcreate_prefix(self, ctx: commands.Context, name: str, channel_type: str = "text") -> None:
        await self._execute_channelcreate(UnifiedContext.from_prefix(ctx), name, channel_type)

    @app_commands.command(name="channelcreate", description="Create a new guild channel.")
    @app_commands.describe(name="Name for the new channel", channel_type="Channel type (text, voice, stage)")
    @app_commands.default_permissions(manage_channels=True)
    async def channelcreate_slash(self, interaction: discord.Interaction, name: str, channel_type: str = "text") -> None:
        await self._execute_channelcreate(UnifiedContext.from_interaction(interaction), name, channel_type)

    # ── 3. channeldelete ────────────────────────────────────────────────────

    async def _execute_channeldelete(self, ctx: UnifiedContext, channel: discord.abc.GuildChannel, reason: str = "No reason provided") -> None:
        if not ctx.guild:
            return
        ch_name = channel.name
        try:
            await channel.delete(reason=f"Deleted by {ctx.author}: {reason}")
            await ctx.send_success("Channel Deleted", f"Channel `#{ch_name}` was deleted successfully.")
        except discord.Forbidden:
            await ctx.send_error("Permission Missing", "I lack permission to delete this channel.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="channeldelete", aliases=["chdelete", "delchannel"], help="Delete a channel.")
    @commands.has_permissions(manage_channels=True)
    async def channeldelete_prefix(self, ctx: commands.Context, channel: discord.abc.GuildChannel, *, reason: str = "No reason provided") -> None:
        await self._execute_channeldelete(UnifiedContext.from_prefix(ctx), channel, reason)

    @app_commands.command(name="channeldelete", description="Delete an existing channel.")
    @app_commands.describe(channel="Channel to delete", reason="Reason for deletion")
    @app_commands.default_permissions(manage_channels=True)
    async def channeldelete_slash(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel, reason: str = "No reason provided") -> None:
        await self._execute_channeldelete(UnifiedContext.from_interaction(interaction), channel, reason)

    # ── 4. channelrename ────────────────────────────────────────────────────

    async def _execute_channelrename(self, ctx: UnifiedContext, channel: discord.abc.GuildChannel, new_name: str) -> None:
        if not ctx.guild:
            return
        old_name = channel.name
        try:
            await channel.edit(name=new_name, reason=f"Renamed by {ctx.author}")
            await ctx.send_success("Channel Renamed", f"`#{old_name}` has been renamed to `#{new_name}`.")
        except discord.Forbidden:
            await ctx.send_error("Permission Missing", "I lack permission to rename this channel.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="channelrename", aliases=["chrename"], help="Rename a channel.")
    @commands.has_permissions(manage_channels=True)
    async def channelrename_prefix(self, ctx: commands.Context, channel: discord.abc.GuildChannel, new_name: str) -> None:
        await self._execute_channelrename(UnifiedContext.from_prefix(ctx), channel, new_name)

    @app_commands.command(name="channelrename", description="Rename an existing channel.")
    @app_commands.describe(channel="Channel to rename", new_name="New channel name")
    @app_commands.default_permissions(manage_channels=True)
    async def channelrename_slash(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel, new_name: str) -> None:
        await self._execute_channelrename(UnifiedContext.from_interaction(interaction), channel, new_name)

    # ── 5. channeltopic ─────────────────────────────────────────────────────

    async def _execute_channeltopic(self, ctx: UnifiedContext, channel: discord.TextChannel, topic: str) -> None:
        if not ctx.guild:
            return
        try:
            await channel.edit(topic=topic, reason=f"Topic updated by {ctx.author}")
            await ctx.send_success("Topic Updated", f"Topic for {channel.mention} updated to:\n> {topic}")
        except discord.Forbidden:
            await ctx.send_error("Permission Missing", "I lack permission to edit this channel's topic.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="channeltopic", aliases=["settopic"], help="Set text channel topic.")
    @commands.has_permissions(manage_channels=True)
    async def channeltopic_prefix(self, ctx: commands.Context, channel: discord.TextChannel, *, topic: str) -> None:
        await self._execute_channeltopic(UnifiedContext.from_prefix(ctx), channel, topic)

    @app_commands.command(name="channeltopic", description="Set topic for a text channel.")
    @app_commands.describe(channel="Text channel", topic="New topic text")
    @app_commands.default_permissions(manage_channels=True)
    async def channeltopic_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, topic: str) -> None:
        await self._execute_channeltopic(UnifiedContext.from_interaction(interaction), channel, topic)

    # ── 6. categorycreate ───────────────────────────────────────────────────

    async def _execute_categorycreate(self, ctx: UnifiedContext, name: str) -> None:
        if not ctx.guild:
            return
        try:
            cat = await ctx.guild.create_category(name=name, reason=f"Created by {ctx.author}")
            await ctx.send_success("Category Created", f"Category **{cat.name}** created.")
        except discord.Forbidden:
            await ctx.send_error("Permission Missing", "I lack `Manage Channels` permission.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="categorycreate", aliases=["catcreate"], help="Create a channel category.")
    @commands.has_permissions(manage_channels=True)
    async def categorycreate_prefix(self, ctx: commands.Context, *, name: str) -> None:
        await self._execute_categorycreate(UnifiedContext.from_prefix(ctx), name)

    @app_commands.command(name="categorycreate", description="Create a new channel category.")
    @app_commands.describe(name="Category name")
    @app_commands.default_permissions(manage_channels=True)
    async def categorycreate_slash(self, interaction: discord.Interaction, name: str) -> None:
        await self._execute_categorycreate(UnifiedContext.from_interaction(interaction), name)

    # ── 7. categorydelete ───────────────────────────────────────────────────

    async def _execute_categorydelete(self, ctx: UnifiedContext, category: discord.CategoryChannel) -> None:
        if not ctx.guild:
            return
        name = category.name
        try:
            await category.delete(reason=f"Deleted by {ctx.author}")
            await ctx.send_success("Category Deleted", f"Category **{name}** deleted.")
        except discord.Forbidden:
            await ctx.send_error("Permission Missing", "I lack permission to delete this category.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="categorydelete", aliases=["catdelete"], help="Delete a channel category.")
    @commands.has_permissions(manage_channels=True)
    async def categorydelete_prefix(self, ctx: commands.Context, category: discord.CategoryChannel) -> None:
        await self._execute_categorydelete(UnifiedContext.from_prefix(ctx), category)

    @app_commands.command(name="categorydelete", description="Delete a channel category.")
    @app_commands.describe(category="Category to delete")
    @app_commands.default_permissions(manage_channels=True)
    async def categorydelete_slash(self, interaction: discord.Interaction, category: discord.CategoryChannel) -> None:
        await self._execute_categorydelete(UnifiedContext.from_interaction(interaction), category)

    # ── 8. channelmove ──────────────────────────────────────────────────────

    async def _execute_channelmove(self, ctx: UnifiedContext, channel: discord.abc.GuildChannel, category: discord.CategoryChannel) -> None:
        if not ctx.guild:
            return
        try:
            await channel.edit(category=category, reason=f"Moved by {ctx.author}")
            await ctx.send_success("Channel Moved", f"Moved `#{channel.name}` to **{category.name}**.")
        except discord.Forbidden:
            await ctx.send_error("Permission Missing", "I lack permission to move this channel.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="channelmove", aliases=["chmove"], help="Move a channel to a category.")
    @commands.has_permissions(manage_channels=True)
    async def channelmove_prefix(self, ctx: commands.Context, channel: discord.abc.GuildChannel, category: discord.CategoryChannel) -> None:
        await self._execute_channelmove(UnifiedContext.from_prefix(ctx), channel, category)

    @app_commands.command(name="channelmove", description="Move a channel to a category.")
    @app_commands.describe(channel="Channel to move", category="Target category")
    @app_commands.default_permissions(manage_channels=True)
    async def channelmove_slash(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel, category: discord.CategoryChannel) -> None:
        await self._execute_channelmove(UnifiedContext.from_interaction(interaction), channel, category)

    # ── 9. rolecreate ───────────────────────────────────────────────────────

    async def _execute_rolecreate(self, ctx: UnifiedContext, name: str, color_hex: Optional[str] = None) -> None:
        if not ctx.guild:
            return
        color = _parse_color(color_hex) or discord.Color.default()
        try:
            role = await ctx.guild.create_role(name=name, color=color, reason=f"Created by {ctx.author}")
            await ctx.send_success("Role Created", f"Role {role.mention} (`{role.name}`) created.")
        except discord.Forbidden:
            await ctx.send_error("Permission Missing", "I lack `Manage Roles` permission.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="rolecreate", aliases=["createrole"], help="Create a new guild role.")
    @commands.has_permissions(manage_roles=True)
    async def rolecreate_prefix(self, ctx: commands.Context, name: str, color_hex: Optional[str] = None) -> None:
        await self._execute_rolecreate(UnifiedContext.from_prefix(ctx), name, color_hex)

    @app_commands.command(name="rolecreate", description="Create a new guild role.")
    @app_commands.describe(name="Role name", color_hex="Hex color (e.g. #9D4EDD)")
    @app_commands.default_permissions(manage_roles=True)
    async def rolecreate_slash(self, interaction: discord.Interaction, name: str, color_hex: Optional[str] = None) -> None:
        await self._execute_rolecreate(UnifiedContext.from_interaction(interaction), name, color_hex)

    # ── 10. roledelete ──────────────────────────────────────────────────────

    async def _execute_roledelete(self, ctx: UnifiedContext, role: discord.Role) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not self._can_manage_role(ctx.author, role, ctx.guild):
            await ctx.send_error("Hierarchy Error", "You or the bot cannot delete this role due to role hierarchy.")
            return
        name = role.name
        try:
            await role.delete(reason=f"Deleted by {ctx.author}")
            await ctx.send_success("Role Deleted", f"Role `@{name}` deleted.")
        except discord.Forbidden:
            await ctx.send_error("Permission Missing", "I lack permission to delete this role.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="roledelete", aliases=["delrole"], help="Delete a guild role.")
    @commands.has_permissions(manage_roles=True)
    async def roledelete_prefix(self, ctx: commands.Context, role: discord.Role) -> None:
        await self._execute_roledelete(UnifiedContext.from_prefix(ctx), role)

    @app_commands.command(name="roledelete", description="Delete an existing role.")
    @app_commands.describe(role="Role to delete")
    @app_commands.default_permissions(manage_roles=True)
    async def roledelete_slash(self, interaction: discord.Interaction, role: discord.Role) -> None:
        await self._execute_roledelete(UnifiedContext.from_interaction(interaction), role)

    # ── 11. rolecolor ───────────────────────────────────────────────────────

    async def _execute_rolecolor(self, ctx: UnifiedContext, role: discord.Role, hex_color: str) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not self._can_manage_role(ctx.author, role, ctx.guild):
            await ctx.send_error("Hierarchy Error", "Role is higher than your or the bot's highest role.")
            return
        color = _parse_color(hex_color)
        if not color:
            await ctx.send_error("Invalid Color", "Please provide a valid 6-digit hex code (e.g. `#9D4EDD`).")
            return
        try:
            await role.edit(color=color, reason=f"Color edited by {ctx.author}")
            await ctx.send_success("Color Updated", f"Color for {role.mention} updated to `{hex_color}`.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="rolecolor", help="Change role hex color.")
    @commands.has_permissions(manage_roles=True)
    async def rolecolor_prefix(self, ctx: commands.Context, role: discord.Role, hex_color: str) -> None:
        await self._execute_rolecolor(UnifiedContext.from_prefix(ctx), role, hex_color)

    @app_commands.command(name="rolecolor", description="Change role hex color.")
    @app_commands.describe(role="Role to modify", hex_color="Hex code (e.g. #9D4EDD)")
    @app_commands.default_permissions(manage_roles=True)
    async def rolecolor_slash(self, interaction: discord.Interaction, role: discord.Role, hex_color: str) -> None:
        await self._execute_rolecolor(UnifiedContext.from_interaction(interaction), role, hex_color)

    # ── 12. rolename ────────────────────────────────────────────────────────

    async def _execute_rolename(self, ctx: UnifiedContext, role: discord.Role, new_name: str) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not self._can_manage_role(ctx.author, role, ctx.guild):
            await ctx.send_error("Hierarchy Error", "Role is higher than your or the bot's highest role.")
            return
        old_name = role.name
        try:
            await role.edit(name=new_name, reason=f"Renamed by {ctx.author}")
            await ctx.send_success("Role Renamed", f"Renamed `@{old_name}` to {role.mention}.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="rolename", help="Rename an existing role.")
    @commands.has_permissions(manage_roles=True)
    async def rolename_prefix(self, ctx: commands.Context, role: discord.Role, *, new_name: str) -> None:
        await self._execute_rolename(UnifiedContext.from_prefix(ctx), role, new_name)

    @app_commands.command(name="rolename", description="Rename an existing role.")
    @app_commands.describe(role="Role to modify", new_name="New role name")
    @app_commands.default_permissions(manage_roles=True)
    async def rolename_slash(self, interaction: discord.Interaction, role: discord.Role, new_name: str) -> None:
        await self._execute_rolename(UnifiedContext.from_interaction(interaction), role, new_name)

    # ── 13. rolehoist ───────────────────────────────────────────────────────

    async def _execute_rolehoist(self, ctx: UnifiedContext, role: discord.Role, toggle: str) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not self._can_manage_role(ctx.author, role, ctx.guild):
            await ctx.send_error("Hierarchy Error", "Role is above your or the bot's highest role.")
            return
        enable = toggle.lower() in ("enable", "true", "on", "yes", "1")
        try:
            await role.edit(hoist=enable, reason=f"Hoist toggled by {ctx.author}")
            status = "now displayed separately" if enable else "no longer hoisted"
            await ctx.send_success("Role Hoist Updated", f"{role.mention} is {status}.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="rolehoist", help="Toggle whether a role is hoisted separately on member list.")
    @commands.has_permissions(manage_roles=True)
    async def rolehoist_prefix(self, ctx: commands.Context, role: discord.Role, toggle: str) -> None:
        await self._execute_rolehoist(UnifiedContext.from_prefix(ctx), role, toggle)

    @app_commands.command(name="rolehoist", description="Toggle role hoisting.")
    @app_commands.describe(role="Role to modify", toggle="enable or disable")
    @app_commands.default_permissions(manage_roles=True)
    async def rolehoist_slash(self, interaction: discord.Interaction, role: discord.Role, toggle: str) -> None:
        await self._execute_rolehoist(UnifiedContext.from_interaction(interaction), role, toggle)

    # ── 14. rolementionable ─────────────────────────────────────────────────

    async def _execute_rolementionable(self, ctx: UnifiedContext, role: discord.Role, toggle: str) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not self._can_manage_role(ctx.author, role, ctx.guild):
            await ctx.send_error("Hierarchy Error", "Role is above your or the bot's highest role.")
            return
        enable = toggle.lower() in ("enable", "true", "on", "yes", "1")
        try:
            await role.edit(mentionable=enable, reason=f"Mentionable toggled by {ctx.author}")
            status = "now mentionable by everyone" if enable else "no longer mentionable"
            await ctx.send_success("Role Mentionable Updated", f"{role.mention} is {status}.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="rolementionable", help="Toggle whether a role can be mentioned by anyone.")
    @commands.has_permissions(manage_roles=True)
    async def rolementionable_prefix(self, ctx: commands.Context, role: discord.Role, toggle: str) -> None:
        await self._execute_rolementionable(UnifiedContext.from_prefix(ctx), role, toggle)

    @app_commands.command(name="rolementionable", description="Toggle role mentionability.")
    @app_commands.describe(role="Role to modify", toggle="enable or disable")
    @app_commands.default_permissions(manage_roles=True)
    async def rolementionable_slash(self, interaction: discord.Interaction, role: discord.Role, toggle: str) -> None:
        await self._execute_rolementionable(UnifiedContext.from_interaction(interaction), role, toggle)

    # ── 15. roleadd ─────────────────────────────────────────────────────────

    async def _execute_roleadd(self, ctx: UnifiedContext, member: discord.Member, role: discord.Role) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not self._can_manage_role(ctx.author, role, ctx.guild):
            await ctx.send_error("Hierarchy Error", "Cannot assign this role due to role hierarchy.")
            return
        if role in member.roles:
            await ctx.send_error("Already Assigned", f"{member.mention} already has {role.mention}.")
            return
        try:
            await member.add_roles(role, reason=f"Role added by {ctx.author}")
            await ctx.send_success("Role Assigned", f"Added {role.mention} to {member.mention}.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="roleadd", aliases=["addrole", "giverole"], help="Assign a role to a member.")
    @commands.has_permissions(manage_roles=True)
    async def roleadd_prefix(self, ctx: commands.Context, member: discord.Member, role: discord.Role) -> None:
        await self._execute_roleadd(UnifiedContext.from_prefix(ctx), member, role)

    @app_commands.command(name="roleadd", description="Assign a role to a member.")
    @app_commands.describe(member="Member to receive role", role="Role to give")
    @app_commands.default_permissions(manage_roles=True)
    async def roleadd_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role) -> None:
        await self._execute_roleadd(UnifiedContext.from_interaction(interaction), member, role)

    # ── 16. roleremove ──────────────────────────────────────────────────────

    async def _execute_roleremove(self, ctx: UnifiedContext, member: discord.Member, role: discord.Role) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not self._can_manage_role(ctx.author, role, ctx.guild):
            await ctx.send_error("Hierarchy Error", "Cannot remove this role due to role hierarchy.")
            return
        if role not in member.roles:
            await ctx.send_error("Not Assigned", f"{member.mention} does not possess {role.mention}.")
            return
        try:
            await member.remove_roles(role, reason=f"Role removed by {ctx.author}")
            await ctx.send_success("Role Removed", f"Removed {role.mention} from {member.mention}.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="roleremove", aliases=["takerole", "removerole"], help="Remove a role from a member.")
    @commands.has_permissions(manage_roles=True)
    async def roleremove_prefix(self, ctx: commands.Context, member: discord.Member, role: discord.Role) -> None:
        await self._execute_roleremove(UnifiedContext.from_prefix(ctx), member, role)

    @app_commands.command(name="roleremove", description="Remove a role from a member.")
    @app_commands.describe(member="Member to strip role from", role="Role to remove")
    @app_commands.default_permissions(manage_roles=True)
    async def roleremove_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role) -> None:
        await self._execute_roleremove(UnifiedContext.from_interaction(interaction), member, role)

    # ── 17. nick ────────────────────────────────────────────────────────────

    async def _execute_nick(self, ctx: UnifiedContext, member: discord.Member, nickname: Optional[str] = None) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if ctx.author.id != ctx.guild.owner_id and ctx.author.top_role <= member.top_role:
            await ctx.send_error("Hierarchy Error", "Cannot manage nickname of a member with equal/higher role.")
            return
        if ctx.guild.me.top_role <= member.top_role:
            await ctx.send_error("Hierarchy Error", "Bot role is not high enough to manage this member's nickname.")
            return
        try:
            await member.edit(nick=nickname, reason=f"Nickname edited by {ctx.author}")
            if nickname:
                await ctx.send_success("Nickname Updated", f"Changed {member.mention}'s nickname to **{nickname}**.")
            else:
                await ctx.send_success("Nickname Reset", f"Reset {member.mention}'s nickname.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="nick", aliases=["setnick", "nickname"], help="Change or reset a member's server nickname.")
    @commands.has_permissions(manage_nicknames=True)
    async def nick_prefix(self, ctx: commands.Context, member: discord.Member, *, nickname: Optional[str] = None) -> None:
        await self._execute_nick(UnifiedContext.from_prefix(ctx), member, nickname)

    @app_commands.command(name="nick", description="Change or reset a member's server nickname.")
    @app_commands.describe(member="Target member", nickname="New nickname (leave empty to reset)")
    @app_commands.default_permissions(manage_nicknames=True)
    async def nick_slash(self, interaction: discord.Interaction, member: discord.Member, nickname: Optional[str] = None) -> None:
        await self._execute_nick(UnifiedContext.from_interaction(interaction), member, nickname)

    # ── 18. setserververification ───────────────────────────────────────────

    async def _execute_setserververification(self, ctx: UnifiedContext, level: str) -> None:
        if not ctx.guild:
            return
        level_map = {
            "none": discord.VerificationLevel.none,
            "low": discord.VerificationLevel.low,
            "medium": discord.VerificationLevel.medium,
            "high": discord.VerificationLevel.high,
            "highest": discord.VerificationLevel.highest,
        }
        v_level = level_map.get(level.lower())
        if not v_level:
            await ctx.send_error("Invalid Level", "Valid levels: `none`, `low`, `medium`, `high`, `highest`.")
            return
        try:
            await ctx.guild.edit(verification_level=v_level, reason=f"Updated by {ctx.author}")
            await ctx.send_success("Verification Level Set", f"Server verification level set to **{level.upper()}**.")
        except discord.Forbidden:
            await ctx.send_error("Permission Missing", "I lack permission to edit server verification level.")
        except Exception as e:
            await ctx.send_error("Operation Failed", str(e))

    @commands.command(name="setserververification", aliases=["setverification"], help="Set server verification level.")
    @commands.has_permissions(administrator=True)
    async def setserververification_prefix(self, ctx: commands.Context, level: str) -> None:
        await self._execute_setserververification(UnifiedContext.from_prefix(ctx), level)

    @app_commands.command(name="setserververification", description="Set server verification level.")
    @app_commands.describe(level="Level: none, low, medium, high, highest")
    @app_commands.default_permissions(administrator=True)
    async def setserververification_slash(self, interaction: discord.Interaction, level: str) -> None:
        await self._execute_setserververification(UnifiedContext.from_interaction(interaction), level)

    # ── 19. rulesadd ────────────────────────────────────────────────────────

    async def _execute_rulesadd(self, ctx: UnifiedContext, title: str, content: str) -> None:
        if not ctx.guild:
            return
        existing = await self.bot.admin_repo.get_rules(ctx.guild.id) if self.bot.admin_repo else []
        new_idx = len(existing) + 1
        if self.bot.admin_repo:
            await self.bot.admin_repo.add_rule(ctx.guild.id, new_idx, title, content)
        await ctx.send_success("Rule Added", f"Added **Rule #{new_idx}: {title}**.")

    @commands.command(name="rulesadd", help="Add a rule to the server rules list.")
    @commands.has_permissions(administrator=True)
    async def rulesadd_prefix(self, ctx: commands.Context, title: str, *, content: str) -> None:
        await self._execute_rulesadd(UnifiedContext.from_prefix(ctx), title, content)

    @app_commands.command(name="rulesadd", description="Add a rule to the server rules list.")
    @app_commands.describe(title="Rule title", content="Rule text content")
    @app_commands.default_permissions(administrator=True)
    async def rulesadd_slash(self, interaction: discord.Interaction, title: str, content: str) -> None:
        await self._execute_rulesadd(UnifiedContext.from_interaction(interaction), title, content)

    # ── 20. rulesremove ─────────────────────────────────────────────────────

    async def _execute_rulesremove(self, ctx: UnifiedContext, index: int) -> None:
        if not ctx.guild:
            return
        if self.bot.admin_repo:
            removed = await self.bot.admin_repo.remove_rule(ctx.guild.id, index)
            if removed:
                await ctx.send_success("Rule Removed", f"Rule #{index} has been deleted.")
            else:
                await ctx.send_error("Not Found", f"No rule with index #{index} exists.")

    @commands.command(name="rulesremove", help="Remove a rule by index number.")
    @commands.has_permissions(administrator=True)
    async def rulesremove_prefix(self, ctx: commands.Context, index: int) -> None:
        await self._execute_rulesremove(UnifiedContext.from_prefix(ctx), index)

    @app_commands.command(name="rulesremove", description="Remove a rule by index number.")
    @app_commands.describe(index="Rule number to delete")
    @app_commands.default_permissions(administrator=True)
    async def rulesremove_slash(self, interaction: discord.Interaction, index: int) -> None:
        await self._execute_rulesremove(UnifiedContext.from_interaction(interaction), index)

    # ── 21. ruleslist ───────────────────────────────────────────────────────

    async def _execute_ruleslist(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            return
        rules = await self.bot.admin_repo.get_rules(ctx.guild.id) if self.bot.admin_repo else []
        if not rules:
            await ctx.send_error("No Rules", "No server rules have been configured yet. Use `!rulesadd` to create rules.")
            return

        embed = EmbedBuilder.base(
            title=f"📜 Server Rules • {ctx.guild.name}",
            description="Please read and adhere to all community guidelines below:",
            color=BRAND_COLOR,
        )
        for r in rules:
            embed.add_field(name=f"#{r['rule_index']}. {r['title']}", value=r["content"], inline=False)
        embed.set_footer(text=f"{len(rules)} Rules • Adherence is mandatory")
        await ctx.reply(embed=embed)

    @commands.command(name="ruleslist", aliases=["rules"], help="Display formatted server rules card.")
    async def ruleslist_prefix(self, ctx: commands.Context) -> None:
        await self._execute_ruleslist(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="ruleslist", description="Display formatted server rules.")
    async def ruleslist_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_ruleslist(UnifiedContext.from_interaction(interaction))

    # ── 22. serverstats ─────────────────────────────────────────────────────

    async def _execute_serverstats(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            return
        g = ctx.guild
        total_members = g.member_count or len(g.members)
        bots = sum(1 for m in g.members if m.bot)
        humans = total_members - bots
        text_channels = len(g.text_channels)
        voice_channels = len(g.voice_channels)
        roles_count = len(g.roles)
        boosts = g.premium_subscription_count or 0
        boost_tier = g.premium_tier

        embed = EmbedBuilder.base(
            title=f"📊 Server Statistics • {g.name}",
            description=f"Comprehensive structural audit for **{g.name}** (`{g.id}`).",
            color=BRAND_COLOR,
            thumbnail=g.icon.url if g.icon else None,
        )
        embed.add_field(name="👥 Members", value=f"Total: **{total_members}**\nHumans: **{humans}**\nBots: **{bots}**", inline=True)
        embed.add_field(name="📁 Channels", value=f"Text: **{text_channels}**\nVoice: **{voice_channels}**\nCategories: **{len(g.categories)}**", inline=True)
        embed.add_field(name=f"{KrovexEmoji.ROCKET} Boost Status", value=f"Level: **Tier {boost_tier}**\nBoosts: **{boosts}**", inline=True)
        embed.add_field(name="🛡️ Security & Roles", value=f"Roles: **{roles_count}**\nVerification: **{str(g.verification_level).title()}**", inline=True)
        embed.add_field(name="👑 Owner", value=f"<@{g.owner_id}>", inline=True)
        embed.add_field(name="📅 Created At", value=f"<t:{int(g.created_at.timestamp())}:R>", inline=True)
        await ctx.reply(embed=embed)

    @commands.command(name="serverstats", help="Display complete server audit statistics.")
    async def serverstats_prefix(self, ctx: commands.Context) -> None:
        await self._execute_serverstats(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="serverstats", description="Display complete server audit statistics.")
    async def serverstats_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_serverstats(UnifiedContext.from_interaction(interaction))

    # ── 23. rolehierarchy ───────────────────────────────────────────────────

    async def _execute_rolehierarchy(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            return
        sorted_roles = sorted(ctx.guild.roles, key=lambda r: r.position, reverse=True)
        lines = []
        for r in sorted_roles[:25]:
            lines.append(f"`{r.position:02d}` • {r.mention} ({len(r.members)} members)")
        if len(sorted_roles) > 25:
            lines.append(f"*...and {len(sorted_roles) - 25} lower roles*")

        embed = EmbedBuilder.base(
            title=f"👑 Role Hierarchy • {ctx.guild.name}",
            description="\n".join(lines),
            color=BRAND_COLOR,
            footer_text=f"Total Roles: {len(sorted_roles)} • Higher position = higher authority",
        )
        await ctx.reply(embed=embed)

    @commands.command(name="rolehierarchy", aliases=["roleshierarchy", "roleshier"], help="Display visual hierarchy tree of server roles.")
    async def rolehierarchy_prefix(self, ctx: commands.Context) -> None:
        await self._execute_rolehierarchy(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="rolehierarchy", description="Display server role hierarchy tree.")
    async def rolehierarchy_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_rolehierarchy(UnifiedContext.from_interaction(interaction))

    # ── 24. permissionaudit ─────────────────────────────────────────────────

    async def _execute_permissionaudit(self, ctx: UnifiedContext, target: Union[discord.Member, discord.Role]) -> None:
        if not ctx.guild:
            return
        perms = target.guild_permissions if isinstance(target, discord.Member) else target.permissions
        key_perms = [
            ("Administrator", perms.administrator),
            ("Manage Server", perms.manage_guild),
            ("Manage Roles", perms.manage_roles),
            ("Manage Channels", perms.manage_channels),
            ("Kick Members", perms.kick_members),
            ("Ban Members", perms.ban_members),
            ("Manage Messages", perms.manage_messages),
            ("Mention Everyone", perms.mention_everyone),
            ("Mute Members", perms.mute_members),
            ("Move Members", perms.move_members),
            ("Manage Webhooks", perms.manage_webhooks),
            ("View Audit Log", perms.view_audit_log),
        ]
        lines = [f"{'🟢' if val else '🔴'} **{name}**" for name, val in key_perms]

        target_name = target.mention if hasattr(target, "mention") else str(target)
        embed = EmbedBuilder.base(
            title=f"🛡️ Permission Audit • {target.name}",
            description=f"Key governance permissions for {target_name}:\n\n" + "\n".join(lines),
            color=BRAND_COLOR,
        )
        await ctx.reply(embed=embed)

    @commands.command(name="permissionaudit", aliases=["permaudit"], help="Deep audit key permissions of a member or role.")
    @commands.has_permissions(administrator=True)
    async def permissionaudit_prefix(self, ctx: commands.Context, target: Union[discord.Member, discord.Role]) -> None:
        await self._execute_permissionaudit(UnifiedContext.from_prefix(ctx), target)

    @app_commands.command(name="permissionaudit", description="Deep audit key permissions of a member or role.")
    @app_commands.describe(target="Member or Role to audit")
    @app_commands.default_permissions(administrator=True)
    async def permissionaudit_slash(self, interaction: discord.Interaction, target: Union[discord.Member, discord.Role]) -> None:
        await self._execute_permissionaudit(UnifiedContext.from_interaction(interaction), target)

    # ── 25. bulkroleadd ─────────────────────────────────────────────────────

    async def _execute_bulkroleadd(self, ctx: UnifiedContext, role: discord.Role, target_filter: str = "humans") -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not self._can_manage_role(ctx.author, role, ctx.guild):
            await ctx.send_error("Hierarchy Error", "Cannot assign this role due to role hierarchy.")
            return

        target_filter = target_filter.lower()
        if target_filter not in ("humans", "bots", "all"):
            await ctx.send_error("Invalid Filter", "Filter must be `humans`, `bots`, or `all`.")
            return

        await ctx.send_success("Bulk Role Started", f"Adding {role.mention} to **{target_filter}** in background...")
        added_count = 0
        for m in ctx.guild.members:
            if target_filter == "humans" and m.bot:
                continue
            if target_filter == "bots" and not m.bot:
                continue
            if role not in m.roles:
                try:
                    await m.add_roles(role, reason=f"Bulk role add by {ctx.author}")
                    added_count += 1
                except Exception:
                    pass
        await ctx.send_success("Bulk Role Complete", f"Successfully granted {role.mention} to **{added_count}** members.")

    @commands.command(name="bulkroleadd", help="Bulk add a role to humans, bots, or all members.")
    @commands.has_permissions(administrator=True)
    async def bulkroleadd_prefix(self, ctx: commands.Context, role: discord.Role, target_filter: str = "humans") -> None:
        await self._execute_bulkroleadd(UnifiedContext.from_prefix(ctx), role, target_filter)

    @app_commands.command(name="bulkroleadd", description="Bulk add a role to humans, bots, or all members.")
    @app_commands.describe(role="Role to assign", target_filter="Filter: humans, bots, all")
    @app_commands.default_permissions(administrator=True)
    async def bulkroleadd_slash(self, interaction: discord.Interaction, role: discord.Role, target_filter: str = "humans") -> None:
        await self._execute_bulkroleadd(UnifiedContext.from_interaction(interaction), role, target_filter)


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(ServerAdmin(bot))

