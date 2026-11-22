"""Welcome and goodbye system management cog."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.welcome")
BRAND_COLOR = 0x9D4EDD


class Welcome(commands.GroupCog, group_name="welcome", group_description="Welcome greetings, farewells, and autoroles"):
    """Automated member greetings, farewells, auto-roles, and welcome verification."""

    def __init__(self, bot: "DeathBot") -> None:
        super().__init__()
        self.bot = bot

    # ── 1. welcomestatus ────────────────────────────────────────────────────

    async def _execute_welcomestatus(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        settings = None
        if self.bot.welcome_repo:
            settings = await self.bot.welcome_repo.get_or_create(ctx.guild.id)

        enabled = settings.enabled if settings else False
        channel_mention = f"<#{settings.channel_id}>" if (settings and settings.channel_id) else "None"
        auto_roles = (
            ", ".join(f"<@&{r}>" for r in settings.auto_role_ids)
            if (settings and settings.auto_role_ids)
            else "None"
        )
        dm_enabled = "Enabled" if (settings and settings.dm_enabled) else "Disabled"
        goodbye_enabled = "Enabled" if (settings and settings.send_goodbye) else "Disabled"
        goodbye_ch = f"<#{settings.goodbye_channel_id}>" if (settings and settings.goodbye_channel_id) else "None"

        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.WELCOME} Welcome Settings • {ctx.guild.name}",
            description="Overview of greeting configurations and automated member onboarding.",
            color=BRAND_COLOR,
        )
        embed.add_field(name="Welcome System", value=f"{KrovexEmoji.GREEN_SPARKLES} Enabled" if enabled else f"{KrovexEmoji.ANIMATED_CROSS} Disabled", inline=True)
        embed.add_field(name="Welcome Channel", value=channel_mention, inline=True)
        embed.add_field(name=f"{KrovexEmoji.WHITE_FLOWERS} Auto Roles", value=auto_roles, inline=True)
        embed.add_field(name=f"{KrovexEmoji.ANGEL_STATIC} Direct Message Greeting", value=dm_enabled, inline=True)
        embed.add_field(name="Farewell / Goodbye", value=goodbye_enabled, inline=True)
        embed.add_field(name="Goodbye Channel", value=goodbye_ch, inline=True)

        await ctx.reply(embed=embed)

    @commands.command(name="welcomestatus", aliases=["welcomesettings"], help="View current welcome and onboarding settings.")
    async def welcomestatus_prefix(self, ctx: commands.Context) -> None:
        await self._execute_welcomestatus(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="status", description="View current server welcome system settings.")
    async def welcomestatus_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_welcomestatus(UnifiedContext.from_interaction(interaction))

    # ── 2. welcometest ──────────────────────────────────────────────────────

    async def _execute_welcometest(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        member = ctx.author if isinstance(ctx.author, discord.Member) else ctx.guild.me
        if not member:
            await ctx.send_error("Error", "Could not resolve member instance.")
            return

        settings = None
        if self.bot.welcome_repo:
            settings = await self.bot.welcome_repo.get_or_create(ctx.guild.id)

        template = settings.message_template if settings else "Welcome {user} to **{server}**! You are member #{member_count}."
        formatted = (
            template.replace("{user}", member.mention)
            .replace("{user_name}", member.name)
            .replace("{server}", ctx.guild.name)
            .replace("{member_count}", str(ctx.guild.member_count))
        )

        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.ANGEL_STATIC} [TEST] Welcome to {ctx.guild.name}!",
            description=formatted,
            color=BRAND_COLOR,
            thumbnail=member.display_avatar.url,
            footer_text=f"Member #{ctx.guild.member_count} • Simulated Preview",
        )
        await ctx.reply(embed=embed)

    @commands.command(name="welcometest", help="Simulate a welcome message preview in the current channel.")
    @commands.has_permissions(manage_guild=True)
    async def welcometest_prefix(self, ctx: commands.Context) -> None:
        await self._execute_welcometest(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="test", description="Simulate a welcome greeting preview to test formatting.")
    @app_commands.default_permissions(manage_guild=True)
    async def welcometest_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_welcometest(UnifiedContext.from_interaction(interaction))

    # ── 3. welcomesetup ─────────────────────────────────────────────────────

    async def _execute_welcomesetup(self, ctx: UnifiedContext, channel: discord.TextChannel) -> None:
        if not ctx.guild:
            return
        await self.bot.db.execute(
            """INSERT INTO welcome_settings (guild_id, enabled, channel_id) VALUES (?, 1, ?)
               ON CONFLICT(guild_id) DO UPDATE SET enabled = 1, channel_id = ?""",
            (ctx.guild.id, channel.id, channel.id),
        )
        await ctx.send_success("Welcome Channel Configured", f"Welcome greetings enabled and set to {channel.mention}.")

    @commands.command(name="welcomesetup", help="Set the welcome greetings channel and enable welcome system.")
    @commands.has_permissions(manage_guild=True)
    async def welcomesetup_prefix(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        await self._execute_welcomesetup(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="setup", description="Configure welcome announcement channel.")
    @app_commands.describe(channel="Text channel for welcome cards")
    @app_commands.default_permissions(manage_guild=True)
    async def welcomesetup_slash(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await self._execute_welcomesetup(UnifiedContext.from_interaction(interaction), channel)

    # ── 4. welcomemessage ───────────────────────────────────────────────────

    async def _execute_welcomemessage(self, ctx: UnifiedContext, template: str) -> None:
        if not ctx.guild:
            return
        await self.bot.db.execute(
            """INSERT INTO welcome_settings (guild_id, message_template) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET message_template = ?""",
            (ctx.guild.id, template, template),
        )
        await ctx.send_success("Welcome Template Saved", f"New template:\n> {template}\n\n*Placeholders: {{user}}, {{user_name}}, {{server}}, {{member_count}}*")

    @commands.command(name="welcomemessage", aliases=["welcomemsg"], help="Set custom message template for welcomes.")
    @commands.has_permissions(manage_guild=True)
    async def welcomemessage_prefix(self, ctx: commands.Context, *, template: str) -> None:
        await self._execute_welcomemessage(UnifiedContext.from_prefix(ctx), template)

    @app_commands.command(name="message", description="Set custom message template for welcomes.")
    @app_commands.describe(template="Template text with placeholders {user}, {server}, {member_count}")
    @app_commands.default_permissions(manage_guild=True)
    async def welcomemessage_slash(self, interaction: discord.Interaction, template: str) -> None:
        await self._execute_welcomemessage(UnifiedContext.from_interaction(interaction), template)

    # ── 5. welcomeembed ─────────────────────────────────────────────────────

    async def _execute_welcomeembed(self, ctx: UnifiedContext, toggle: str) -> None:
        if not ctx.guild:
            return
        enable = toggle.lower() in ("enable", "true", "on", "yes", "1")
        await self.bot.db.execute(
            """INSERT INTO welcome_settings (guild_id, use_embed) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET use_embed = ?""",
            (ctx.guild.id, 1 if enable else 0, 1 if enable else 0),
        )
        status = "ENABLED (rich embed)" if enable else "DISABLED (plain text)"
        await ctx.send_success("Welcome Embed Updated", f"Welcome embed styling is now **{status}**.")

    @commands.command(name="welcomeembed", help="Toggle embed styling for welcome greetings.")
    @commands.has_permissions(manage_guild=True)
    async def welcomeembed_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._execute_welcomeembed(UnifiedContext.from_prefix(ctx), toggle)

    @app_commands.command(name="embed", description="Toggle embed styling for welcome greetings.")
    @app_commands.describe(toggle="enable or disable")
    @app_commands.default_permissions(manage_guild=True)
    async def welcomeembed_slash(self, interaction: discord.Interaction, toggle: str) -> None:
        await self._execute_welcomeembed(UnifiedContext.from_interaction(interaction), toggle)

    # ── 6. welcomecolor ─────────────────────────────────────────────────────

    async def _execute_welcomecolor(self, ctx: UnifiedContext, hex_color: str) -> None:
        if not ctx.guild:
            return
        cleaned = hex_color.strip().lstrip("#")
        try:
            val = int(cleaned, 16)
        except ValueError:
            await ctx.send_error("Invalid Color", "Please provide a valid 6-character hex code (e.g. `#9D4EDD`).")
            return
        await self.bot.db.execute(
            """INSERT INTO welcome_settings (guild_id, embed_color) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET embed_color = ?""",
            (ctx.guild.id, val, val),
        )
        await ctx.send_success("Welcome Color Set", f"Welcome embed accent color updated to `#{cleaned.upper()}`.")

    @commands.command(name="welcomecolor", help="Set the accent color for welcome embeds.")
    @commands.has_permissions(manage_guild=True)
    async def welcomecolor_prefix(self, ctx: commands.Context, hex_color: str) -> None:
        await self._execute_welcomecolor(UnifiedContext.from_prefix(ctx), hex_color)

    @app_commands.command(name="color", description="Set accent color for welcome embeds.")
    @app_commands.describe(hex_color="Hex code (e.g. #9D4EDD)")
    @app_commands.default_permissions(manage_guild=True)
    async def welcomecolor_slash(self, interaction: discord.Interaction, hex_color: str) -> None:
        await self._execute_welcomecolor(UnifiedContext.from_interaction(interaction), hex_color)

    # ── 7. welcomeimage ─────────────────────────────────────────────────────

    async def _execute_welcomeimage(self, ctx: UnifiedContext, url: Optional[str] = None) -> None:
        if not ctx.guild:
            return
        val = url if url and url.lower() != "none" else None
        await self.bot.db.execute(
            """INSERT INTO welcome_card_settings (guild_id, image_url) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET image_url = ?""",
            (ctx.guild.id, val, val),
        )
        if val:
            await ctx.send_success("Welcome Banner Configured", f"Welcome banner image set to:\n<{val}>")
        else:
            await ctx.send_success("Welcome Banner Removed", "Welcome banner image has been cleared.")

    @commands.command(name="welcomeimage", aliases=["welcomebanner"], help="Set or remove a custom welcome banner image.")
    @commands.has_permissions(manage_guild=True)
    async def welcomeimage_prefix(self, ctx: commands.Context, url: Optional[str] = None) -> None:
        await self._execute_welcomeimage(UnifiedContext.from_prefix(ctx), url)

    @app_commands.command(name="image", description="Set or remove custom welcome banner image.")
    @app_commands.describe(url="Image URL (or 'none' to remove)")
    @app_commands.default_permissions(manage_guild=True)
    async def welcomeimage_slash(self, interaction: discord.Interaction, url: Optional[str] = None) -> None:
        await self._execute_welcomeimage(UnifiedContext.from_interaction(interaction), url)

    # ── 8. welcomedm ────────────────────────────────────────────────────────

    async def _execute_welcomedm(self, ctx: UnifiedContext, toggle: str, template: Optional[str] = None) -> None:
        if not ctx.guild:
            return
        enable = toggle.lower() in ("enable", "true", "on", "yes", "1")
        if template:
            await self.bot.db.execute(
                """INSERT INTO welcome_settings (guild_id, send_dm, dm_template) VALUES (?, ?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET send_dm = ?, dm_template = ?""",
                (ctx.guild.id, 1 if enable else 0, template, 1 if enable else 0, template),
            )
        else:
            await self.bot.db.execute(
                """INSERT INTO welcome_settings (guild_id, send_dm) VALUES (?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET send_dm = ?""",
                (ctx.guild.id, 1 if enable else 0, 1 if enable else 0),
            )
        status = "ENABLED" if enable else "DISABLED"
        await ctx.send_success("Welcome DM Updated", f"Direct message greetings are now **{status}**.")

    @commands.command(name="welcomedm", help="Configure direct message sent to new joiners.")
    @commands.has_permissions(manage_guild=True)
    async def welcomedm_prefix(self, ctx: commands.Context, toggle: str, *, template: Optional[str] = None) -> None:
        await self._execute_welcomedm(UnifiedContext.from_prefix(ctx), toggle, template)

    @app_commands.command(name="dm", description="Configure direct message greeting.")
    @app_commands.describe(toggle="enable or disable", template="Optional custom DM text")
    @app_commands.default_permissions(manage_guild=True)
    async def welcomedm_slash(self, interaction: discord.Interaction, toggle: str, template: Optional[str] = None) -> None:
        await self._execute_welcomedm(UnifiedContext.from_interaction(interaction), toggle, template)

    # ── 9. welcomeautorole ──────────────────────────────────────────────────

    async def _execute_welcomeautorole(self, ctx: UnifiedContext, action: str, role: discord.Role) -> None:
        if not ctx.guild:
            return
        if ctx.guild.me.top_role <= role:
            await ctx.send_error("Hierarchy Error", "I cannot assign this role because it is higher than my highest role.")
            return

        action = action.lower()
        row = await self.bot.db.fetchone("SELECT auto_roles FROM welcome_settings WHERE guild_id = ?", (ctx.guild.id,))
        current_roles: List[int] = []
        if row and row["auto_roles"]:
            try:
                current_roles = json.loads(row["auto_roles"])
            except Exception:
                current_roles = []

        if action in ("add", "enable"):
            if role.id not in current_roles:
                current_roles.append(role.id)
            await self.bot.db.execute(
                """INSERT INTO welcome_settings (guild_id, auto_roles) VALUES (?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET auto_roles = ?""",
                (ctx.guild.id, json.dumps(current_roles), json.dumps(current_roles)),
            )
            await ctx.send_success("Auto-Role Added", f"Added {role.mention} to automatic onboarding roles.")
        else:
            if role.id in current_roles:
                current_roles.remove(role.id)
            await self.bot.db.execute(
                """INSERT INTO welcome_settings (guild_id, auto_roles) VALUES (?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET auto_roles = ?""",
                (ctx.guild.id, json.dumps(current_roles), json.dumps(current_roles)),
            )
            await ctx.send_success("Auto-Role Removed", f"Removed {role.mention} from automatic onboarding roles.")

    @commands.command(name="welcomeautorole", aliases=["autorole"], help="Add or remove automatic join roles.")
    @commands.has_permissions(manage_roles=True)
    async def welcomeautorole_prefix(self, ctx: commands.Context, action: str, role: discord.Role) -> None:
        await self._execute_welcomeautorole(UnifiedContext.from_prefix(ctx), action, role)

    @app_commands.command(name="autorole", description="Add or remove automatic onboarding role.")
    @app_commands.describe(action="add or remove", role="Target role")
    @app_commands.default_permissions(manage_roles=True)
    async def welcomeautorole_slash(self, interaction: discord.Interaction, action: str, role: discord.Role) -> None:
        await self._execute_welcomeautorole(UnifiedContext.from_interaction(interaction), action, role)

    # ── 10. goodbyesetup ────────────────────────────────────────────────────

    async def _execute_goodbyesetup(self, ctx: UnifiedContext, channel: discord.TextChannel) -> None:
        if not ctx.guild:
            return
        await self.bot.db.execute(
            """INSERT INTO welcome_settings (guild_id, goodbye_enabled, goodbye_channel_id) VALUES (?, 1, ?)
               ON CONFLICT(guild_id) DO UPDATE SET goodbye_enabled = 1, goodbye_channel_id = ?""",
            (ctx.guild.id, channel.id, channel.id),
        )
        await ctx.send_success("Farewell Channel Configured", f"Goodbye farewells enabled and set to {channel.mention}.")

    @commands.command(name="goodbyesetup", help="Set the farewell channel and enable goodbye announcements.")
    @commands.has_permissions(manage_guild=True)
    async def goodbyesetup_prefix(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        await self._execute_goodbyesetup(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="goodbyesetup", description="Configure farewell announcement channel.")
    @app_commands.describe(channel="Text channel for farewell cards")
    @app_commands.default_permissions(manage_guild=True)
    async def goodbyesetup_slash(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await self._execute_goodbyesetup(UnifiedContext.from_interaction(interaction), channel)

    # ── 11. goodbyemessage ──────────────────────────────────────────────────

    async def _execute_goodbyemessage(self, ctx: UnifiedContext, template: str) -> None:
        if not ctx.guild:
            return
        await self.bot.db.execute(
            """INSERT INTO welcome_settings (guild_id, goodbye_template) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET goodbye_template = ?""",
            (ctx.guild.id, template, template),
        )
        await ctx.send_success("Goodbye Template Saved", f"New farewell template:\n> {template}\n\n*Placeholders: {{user}}, {{user_name}}, {{server}}, {{member_count}}*")

    @commands.command(name="goodbyemessage", aliases=["goodbyemsg"], help="Set custom farewell message template.")
    @commands.has_permissions(manage_guild=True)
    async def goodbyemessage_prefix(self, ctx: commands.Context, *, template: str) -> None:
        await self._execute_goodbyemessage(UnifiedContext.from_prefix(ctx), template)

    @app_commands.command(name="goodbyemessage", description="Set custom farewell template.")
    @app_commands.describe(template="Template text with placeholders")
    @app_commands.default_permissions(manage_guild=True)
    async def goodbyemessage_slash(self, interaction: discord.Interaction, template: str) -> None:
        await self._execute_goodbyemessage(UnifiedContext.from_interaction(interaction), template)

    # ── 12. goodbyeembed ────────────────────────────────────────────────────

    async def _execute_goodbyeembed(self, ctx: UnifiedContext, toggle: str) -> None:
        if not ctx.guild:
            return
        enable = toggle.lower() in ("enable", "true", "on", "yes", "1")
        await self.bot.db.execute(
            """INSERT INTO welcome_settings (guild_id, goodbye_use_embed) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET goodbye_use_embed = ?""",
            (ctx.guild.id, 1 if enable else 0, 1 if enable else 0),
        )
        status = "ENABLED (rich embed)" if enable else "DISABLED (plain text)"
        await ctx.send_success("Goodbye Embed Updated", f"Goodbye embed styling is now **{status}**.")

    @commands.command(name="goodbyeembed", help="Toggle embed styling for goodbye messages.")
    @commands.has_permissions(manage_guild=True)
    async def goodbyeembed_prefix(self, ctx: commands.Context, toggle: str) -> None:
        await self._execute_goodbyeembed(UnifiedContext.from_prefix(ctx), toggle)

    @app_commands.command(name="goodbyeembed", description="Toggle embed styling for goodbye messages.")
    @app_commands.describe(toggle="enable or disable")
    @app_commands.default_permissions(manage_guild=True)
    async def goodbyeembed_slash(self, interaction: discord.Interaction, toggle: str) -> None:
        await self._execute_goodbyeembed(UnifiedContext.from_interaction(interaction), toggle)

    # ── 13. goodbyetest ─────────────────────────────────────────────────────

    async def _execute_goodbyetest(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            return
        member = ctx.author if isinstance(ctx.author, discord.Member) else ctx.guild.me
        row = await self.bot.db.fetchone("SELECT goodbye_template FROM welcome_settings WHERE guild_id = ?", (ctx.guild.id,))
        template = row["goodbye_template"] if row and row["goodbye_template"] else "**{user}** left the server. Farewell!"
        formatted = (
            template.replace("{user}", member.mention)
            .replace("{user_name}", member.name)
            .replace("{server}", ctx.guild.name)
            .replace("{member_count}", str(ctx.guild.member_count))
        )
        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.PINK_BUTTERFLIES} [TEST] Farewell from {ctx.guild.name}",
            description=formatted,
            color=0xFF5555,
            thumbnail=member.display_avatar.url,
            footer_text=f"Total members remaining: {ctx.guild.member_count}",
        )
        await ctx.reply(embed=embed)

    @commands.command(name="goodbyetest", help="Simulate a farewell message preview in the current channel.")
    @commands.has_permissions(manage_guild=True)
    async def goodbyetest_prefix(self, ctx: commands.Context) -> None:
        await self._execute_goodbyetest(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="goodbyetest", description="Simulate a farewell preview.")
    @app_commands.default_permissions(manage_guild=True)
    async def goodbyetest_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_goodbyetest(UnifiedContext.from_interaction(interaction))

    # ── 14. welcomereset ────────────────────────────────────────────────────

    async def _execute_welcomereset(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            return
        await self.bot.db.execute("DELETE FROM welcome_settings WHERE guild_id = ?", (ctx.guild.id,))
        await self.bot.db.execute("DELETE FROM welcome_card_settings WHERE guild_id = ?", (ctx.guild.id,))
        await ctx.send_success("Welcome Reset", "Welcome and goodbye configurations have been reset to default values.")

    @commands.command(name="welcomereset", help="Reset all welcome and goodbye configurations to default.")
    @commands.has_permissions(manage_guild=True)
    async def welcomereset_prefix(self, ctx: commands.Context) -> None:
        await self._execute_welcomereset(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="reset", description="Reset all welcome and goodbye settings.")
    @app_commands.default_permissions(manage_guild=True)
    async def welcomereset_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_welcomereset(UnifiedContext.from_interaction(interaction))


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(Welcome(bot))
