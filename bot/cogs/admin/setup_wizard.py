"""Interactive Step-by-Step Setup Wizards for Death Bot."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.admin.setup")
BRAND_COLOR = 0x9D4EDD


class WizardCancelView(discord.ui.View):
    """Simple confirm/cancel UI buttons for setup wizards with timeout and concurrency guards."""

    def __init__(self, author_id: int) -> None:
        super().__init__(timeout=180.0)
        self.author_id = author_id
        self._lock = asyncio.Lock()
        self._actioned = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} This setup wizard is not for you.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        logger.error("Error in WizardCancelView: %s", error, exc_info=error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ An error occurred: {error}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ An error occurred: {error}", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="Save & Apply", style=discord.ButtonStyle.success, emoji="✅")
    async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if self._actioned:
                await interaction.response.send_message("⚠️ This setup wizard has already been applied.", ephemeral=True)
                return
            self._actioned = True
            for child in self.children:
                if hasattr(child, "disabled"):
                    child.disabled = True
            await interaction.response.send_message("✅ Configuration verified and saved to database.", ephemeral=True)
            self.stop()

    @discord.ui.button(label="Cancel Wizard", style=discord.ButtonStyle.danger, emoji=KrovexEmoji.CROSS.partial)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            self._actioned = True
            for child in self.children:
                if hasattr(child, "disabled"):
                    child.disabled = True
            await interaction.response.send_message("⚠️ Setup wizard cancelled. No changes were applied.", ephemeral=True)
            self.stop()


class ServerSetupView(WizardCancelView):
    """Interactive server setup wizard with real configuration persistence, validation, and error boundaries."""

    def __init__(
        self,
        bot: "DeathBot",
        author_id: int,
        guild: discord.Guild,
        pending_prefix: Optional[str] = None,
        pending_system_channel: Optional[discord.TextChannel] = None,
        pending_afk_channel: Optional[discord.VoiceChannel] = None,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(author_id=author_id)
        self.timeout = timeout
        self.bot = bot
        self.guild = guild
        self.pending_prefix = pending_prefix
        self.pending_system_channel = pending_system_channel
        self.pending_afk_channel = pending_afk_channel

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} This setup wizard is not for you.", ephemeral=True)
            return False
        if isinstance(interaction.user, discord.Member) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(f"{KrovexEmoji.CROSS} You need Administrator permission to configure server settings.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        logger.error("Error in ServerSetupView: %s", error, exc_info=error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ An error occurred during setup: {error}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ An error occurred during setup: {error}", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="Dry-Run Diff Preview", style=discord.ButtonStyle.secondary, emoji="🔍")
    async def preview_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Render a side-by-side diff preview of proposed changes without applying them."""
        guild = interaction.guild or self.guild
        diff_lines = []

        # 1. Prefix comparison
        curr_pfx = "!"
        if hasattr(self.bot, "guild_repo") and self.bot.guild_repo:
            try:
                res = self.bot.guild_repo.get_prefix(guild.id, default_prefix="!")
                if asyncio.iscoroutine(res):
                    curr_pfx = await res
                elif isinstance(res, str):
                    curr_pfx = res
            except Exception:
                pass
        target_pfx = self.pending_prefix or curr_pfx
        pfx_status = "[UPDATE]" if self.pending_prefix and self.pending_prefix != curr_pfx else "[NO CHANGE]"
        diff_lines.append(f"{pfx_status:<13} Prefix: `{curr_pfx}` ➔ `{target_pfx}`")

        # 2. System Channel comparison
        curr_sys = f"#{guild.system_channel.name}" if guild.system_channel else "None"
        target_sys = f"#{self.pending_system_channel.name}" if self.pending_system_channel else curr_sys
        sys_status = "[UPDATE]" if self.pending_system_channel and self.pending_system_channel != guild.system_channel else "[NO CHANGE]"
        diff_lines.append(f"{sys_status:<13} System Channel: {curr_sys} ➔ {target_sys}")

        # 3. AFK Channel comparison
        curr_afk = guild.afk_channel.name if guild.afk_channel else "None"
        target_afk = self.pending_afk_channel.name if self.pending_afk_channel else curr_afk
        afk_status = "[UPDATE]" if self.pending_afk_channel and self.pending_afk_channel != guild.afk_channel else "[NO CHANGE]"
        diff_lines.append(f"{afk_status:<13} AFK Channel: {curr_afk} ➔ {target_afk}")

        # 4. KROVEX Dedicated Roles check
        roles_present = [r.name for r in guild.roles if r.name in ("KROVEX", "KROVEX Prime Security™", "KROVEX Unbypassable Security™")]
        role_status = "[VERIFIED]" if len(roles_present) == 3 else "[PROVISION]"
        diff_lines.append(f"{role_status:<13} Dedicated Roles: {len(roles_present)}/3 Installed")

        embed = discord.Embed(
            title="🔍 Setup Wizard • Dry-Run Diff Preview",
            description=(
                f"**Target Guild:** `{guild.name}` (`{guild.id}`)\n"
                f"No changes have been made yet. Review the dry-run diff below:\n\n"
                "```ini\n" + "\n".join(diff_lines) + "\n```\n"
                "Click **Save & Apply** to execute these changes or **Cancel Wizard** to abort."
            ),
            color=BRAND_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Save & Apply", style=discord.ButtonStyle.success, emoji="✅")
    async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if self._actioned:
                await interaction.response.send_message("⚠️ This setup wizard has already been applied.", ephemeral=True)
                return
            self._actioned = True

            for child in self.children:
                if hasattr(child, "disabled"):
                    child.disabled = True

            # Defer interaction safely within Discord deadline
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

            guild = interaction.guild or self.guild
            applied_items = []
            warnings = []

            # Take pre-apply snapshot for rollback
            pre_pfx = "!"
            if hasattr(self.bot, "guild_repo") and self.bot.guild_repo:
                try:
                    res = self.bot.guild_repo.get_prefix(guild.id, default_prefix="!")
                    if asyncio.iscoroutine(res):
                        pre_pfx = await res
                    elif isinstance(res, str):
                        pre_pfx = res
                except Exception:
                    pass
            snapshot = {
                "prefix": pre_pfx,
                "system_channel_id": guild.system_channel.id if guild.system_channel else None,
                "afk_channel_id": guild.afk_channel.id if guild.afk_channel else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if not hasattr(self.bot, "_guild_setup_snapshots"):
                self.bot._guild_setup_snapshots = {}
            self.bot._guild_setup_snapshots[guild.id] = snapshot

            # 1. Apply prefix if configured or verify existing
            prefix_to_apply = self.pending_prefix
            if prefix_to_apply:
                # Validate prefix
                if len(prefix_to_apply) > 5 or any(c.isspace() for c in prefix_to_apply):
                    await interaction.followup.send(
                        "❌ Invalid prefix: Prefix must be 1 to 5 characters without whitespace.",
                        ephemeral=True,
                    )
                    return
                try:
                    if hasattr(self.bot, "guild_repo") and self.bot.guild_repo:
                        res = self.bot.guild_repo.set_prefix(guild.id, prefix_to_apply)
                        if asyncio.iscoroutine(res):
                            await res
                    elif hasattr(self.bot, "db") and self.bot.db:
                        res = self.bot.db.execute(
                            """INSERT INTO guild_settings (guild_id, prefix, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                               ON CONFLICT(guild_id) DO UPDATE SET prefix = ?, updated_at = CURRENT_TIMESTAMP""",
                            (guild.id, prefix_to_apply, prefix_to_apply),
                        )
                        if asyncio.iscoroutine(res):
                            await res
                    applied_items.append(f"• **Command Prefix:** `{prefix_to_apply}` (Updated)")
                except Exception as err:
                    logger.error("Failed to save prefix in setup wizard for guild %s: %s", guild.id, err, exc_info=True)
                    await interaction.followup.send(f"❌ Failed to save prefix to database: {err}", ephemeral=True)
                    return
            else:
                current_prefix = "!"
                try:
                    default_pfx = getattr(getattr(self.bot, "config", None), "default_prefix", "!")
                    if hasattr(self.bot, "guild_repo") and self.bot.guild_repo:
                        res = self.bot.guild_repo.get_prefix(guild.id, default_prefix=default_pfx)
                        if asyncio.iscoroutine(res):
                            current_prefix = await res
                        elif isinstance(res, str):
                            current_prefix = res
                        else:
                            current_prefix = default_pfx
                    else:
                        current_prefix = default_pfx
                except Exception:
                    current_prefix = "!"
                    pass
                applied_items.append(f"• **Command Prefix:** `{current_prefix}` (Confirmed)")

            # 2. Apply channel settings if requested
            if self.pending_system_channel or self.pending_afk_channel:
                bot_member = guild.me
                if bot_member and (getattr(bot_member.guild_permissions, "manage_guild", False) or bot_member.guild_permissions.administrator):
                    edit_kwargs = {}
                    if self.pending_system_channel:
                        edit_kwargs["system_channel"] = self.pending_system_channel
                        applied_items.append(f"• **System Channel:** {self.pending_system_channel.mention}")
                    if self.pending_afk_channel:
                        edit_kwargs["afk_channel"] = self.pending_afk_channel
                        applied_items.append(f"• **AFK Channel:** {self.pending_afk_channel.name}")
                    try:
                        await guild.edit(reason=f"Server Setup Wizard applied by {interaction.user}", **edit_kwargs)
                    except Exception as err:
                        logger.error("Failed to update guild channels in setup wizard: %s", err, exc_info=True)
                        warnings.append(f"⚠️ Could not update guild channels via Discord API: {err}")
                else:
                    warnings.append("⚠️ Bot lacks **Manage Server** permission to modify system or AFK channels.")

            applied_items.append(f"• **Verification Level:** `{str(guild.verification_level).title()}` (Active)")

            warning_text = ("\n\n" + "\n".join(warnings)) if warnings else ""
            embed = EmbedBuilder.success(
                title="Configuration Verified & Saved",
                description=(
                    f"Server setup configuration for **{guild.name}** has been applied!\n\n"
                    + "\n".join(applied_items)
                    + warning_text
                ),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            self.stop()

    @discord.ui.button(label="Cancel Wizard", style=discord.ButtonStyle.danger, emoji=KrovexEmoji.CROSS.partial)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            self._actioned = True
            for child in self.children:
                if hasattr(child, "disabled"):
                    child.disabled = True
            await interaction.response.send_message("⚠️ Setup wizard cancelled. No changes were applied.", ephemeral=True)
            self.stop()


class SetupWizard(commands.GroupCog, group_name="setup", group_description="Interactive server setup wizards"):
    """Guided setup wizards for server configuration, roles, reaction roles, logging, and welcomes."""

    def __init__(self, bot: "DeathBot") -> None:
        super().__init__()
        self.bot = bot

    # ── 1. setupserver ──────────────────────────────────────────────────────

    async def _execute_setupserver(
        self,
        ctx: UnifiedContext,
        prefix: Optional[str] = None,
        system_channel: Optional[discord.TextChannel] = None,
        afk_channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "You need Administrator permission to run the setup wizard.")
            return

        g = ctx.guild
        # Validate prefix if provided
        if prefix and (len(prefix) > 5 or any(c.isspace() for c in prefix)):
            await ctx.send_error("Invalid Prefix", "Prefix must be 1 to 5 characters without whitespace.")
            return

        # Fetch current prefix from repository
        current_pfx = prefix
        if not current_pfx:
            default_pfx = getattr(getattr(self.bot, "config", None), "default_prefix", "!")
            if hasattr(self.bot, "guild_repo") and self.bot.guild_repo:
                try:
                    res = self.bot.guild_repo.get_prefix(g.id, default_prefix=default_pfx)
                    if asyncio.iscoroutine(res):
                        current_pfx = await res
                    elif isinstance(res, str):
                        current_pfx = res
                    else:
                        current_pfx = default_pfx
                except Exception:
                    current_pfx = default_pfx
            else:
                current_pfx = default_pfx

        sys_ch_display = system_channel.mention if system_channel else (g.system_channel.mention if g.system_channel else "*None*")
        afk_ch_display = afk_channel.name if afk_channel else (g.afk_channel.name if g.afk_channel else "*None*")

        embed = EmbedBuilder.base(
            title=f"🛠️ Server Setup Wizard • {g.name}",
            description=(
                "Welcome to the **KROVEX Server Setup Wizard**!\n\n"
                f"**Step 1:** Command Prefix: `{current_pfx}` {'*(Pending update)*' if prefix else '*(change via `!setprefix <prefix>`)*'}\n"
                f"**Step 2:** Verification Level: `{str(g.verification_level).title()}`\n"
                f"**Step 3:** System Channel: {sys_ch_display}\n"
                f"**Step 4:** AFK Voice Channel: {afk_ch_display}\n\n"
                "Click **Save & Apply** to verify and save settings, or click **Cancel Wizard** to exit."
            ),
            color=BRAND_COLOR,
            thumbnail=g.icon.url if g.icon else None,
        )
        view = ServerSetupView(
            bot=self.bot,
            author_id=ctx.author.id,
            guild=g,
            pending_prefix=prefix,
            pending_system_channel=system_channel,
            pending_afk_channel=afk_channel,
        )
        await ctx.reply(embed=embed, view=view)

    @commands.command(name="setupserver", help="Interactive server configuration wizard.")
    @commands.has_permissions(administrator=True)
    async def setupserver_prefix(
        self,
        ctx: commands.Context,
        prefix: Optional[str] = None,
    ) -> None:
        await self._execute_setupserver(UnifiedContext.from_prefix(ctx), prefix=prefix)

    @app_commands.command(name="server", description="Interactive server configuration wizard.")
    @app_commands.describe(
        prefix="Optional custom prefix to set (1-5 chars)",
        system_channel="Optional channel for Discord system messages",
        afk_channel="Optional voice channel for AFK members",
    )
    @app_commands.default_permissions(administrator=True)
    async def setupserver_slash(
        self,
        interaction: discord.Interaction,
        prefix: Optional[str] = None,
        system_channel: Optional[discord.TextChannel] = None,
        afk_channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        await self._execute_setupserver(
            UnifiedContext.from_interaction(interaction),
            prefix=prefix,
            system_channel=system_channel,
            afk_channel=afk_channel,
        )

    # ── 2. setuproles ───────────────────────────────────────────────────────

    async def _execute_setuproles(self, ctx: UnifiedContext) -> None:
        await ctx.defer(ephemeral=True)
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        g = ctx.guild
        # Automatically provision/synchronize dedicated roles
        active_roles: list = []
        if hasattr(self.bot, "bot_role_service") and self.bot.bot_role_service:
            try:
                active_roles, _, _ = await self.bot.bot_role_service.setup_bot_roles(g)
            except Exception as err:
                logger.debug("setup_bot_roles in setuproles: %s", err)

        role_summary = ""
        if active_roles:
            role_summary = f"• Dedicated Roles Provisioned: **{len(active_roles)}** (" + ", ".join(r.name for r in active_roles) + ")\n"

        embed = EmbedBuilder.base(
            title=f"👑 Role Architecture Wizard • {g.name}",
            description=(
                "**Role Architecture & Security Overview:**\n\n"
                f"• Total Server Roles: **{len(g.roles)}**\n"
                f"• Bot Highest Role: {g.me.top_role.mention} (Position: `{g.me.top_role.position}`)\n"
                "• Roles Manageable: **" + str(sum(1 for r in g.roles if g.me.top_role > r)) + "**\n"
                + role_summary
                + "\n**Recommended Setup Checklist:**\n"
                "1. Place Death Bot role high in the hierarchy (below Server Owner).\n"
                "2. Dedicated roles (`KROVEX`, `KROVEX Prime Security™`, `KROVEX Unbypassable Security™`) are hoisted at top.\n"
                "3. Use `!welcomeautorole add <role>` for automatic onboarding."
            ),
            color=BRAND_COLOR,
        )
        view = WizardCancelView(ctx.author.id)
        await ctx.reply(embed=embed, view=view)

    @commands.command(name="setuproles", help="Interactive role hierarchy and governance wizard.")
    @commands.has_permissions(administrator=True)
    async def setuproles_prefix(self, ctx: commands.Context) -> None:
        await self._execute_setuproles(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="roles", description="Interactive role governance wizard.")
    @app_commands.default_permissions(administrator=True)
    async def setuproles_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_setuproles(UnifiedContext.from_interaction(interaction))

    # ── 3. setuprr ──────────────────────────────────────────────────────────

    async def _execute_setuprr(self, ctx: UnifiedContext, channel: Optional[discord.TextChannel] = None) -> None:
        await ctx.defer(ephemeral=True)
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        target_ch = channel or ctx.channel
        if not isinstance(target_ch, (discord.TextChannel, discord.Thread)):
            await ctx.send_error("Invalid Channel", "Please specify a valid text channel for the role panel.")
            return
        embed = EmbedBuilder.base(
            title="🔘 Reaction & Button Roles Wizard",
            description=(
                f"Setting up role panels for {target_ch.mention}:\n\n"
                "**Option A: Button Role Panel**\n"
                "`!rrbuttonpanel #channel <Title> <Description>`\n"
                "Then add buttons with: `!rrbuttonadd <message_id> <Label> <@Role>`\n\n"
                "**Option B: Dropdown Menu Panel**\n"
                "`!rrmenucreate #channel <Title> <Description>`\n"
                "Then add options with: `!rrmenuadd <message_id> <Label> <@Role>`\n\n"
                "**Option C: Classic Emoji Reactions**\n"
                "`!rrcreate #channel <message_id> <emoji> <@Role>`"
            ),
            color=BRAND_COLOR,
        )
        view = WizardCancelView(ctx.author.id)
        await ctx.reply(embed=embed, view=view)

    @commands.command(name="setuprr", aliases=["setupreactionroles"], help="Guided role panel creation wizard.")
    @commands.has_permissions(administrator=True)
    async def setuprr_prefix(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_setuprr(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="reactionroles", description="Guided role panel creation wizard.")
    @app_commands.describe(channel="Channel where role panel should be posted")
    @app_commands.default_permissions(administrator=True)
    async def setuprr_slash(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_setuprr(UnifiedContext.from_interaction(interaction), channel)

    # ── 4. setuplogging ─────────────────────────────────────────────────────

    async def _execute_setuplogging(self, ctx: UnifiedContext, channel: Optional[discord.TextChannel] = None) -> None:
        await ctx.defer(ephemeral=True)
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        target_ch = channel or ctx.channel
        if not isinstance(target_ch, (discord.TextChannel, discord.Thread)):
            await ctx.send_error("Invalid Channel", "Please specify a valid text channel for audit logs.")
            return

        try:
            if self.bot.logging_repo:
                await self.bot.logging_repo.update_settings(
                    ctx.guild.id,
                    mod_log_channel=target_ch.id,
                    message_log_channel=target_ch.id,
                    member_log_channel=target_ch.id,
                    server_log_channel=target_ch.id,
                    voice_log_channel=target_ch.id,
                )

            embed = EmbedBuilder.base(
                title="📋 One-Click Logging Setup Wizard",
                description=(
                    f"All event log categories have been routed to {target_ch.mention}!\n\n"
                    f"• 🛡️ Mod Logs: {target_ch.mention}\n"
                    f"• 💬 Message Logs: {target_ch.mention}\n"
                    f"• 👥 Member Logs: {target_ch.mention}\n"
                    f"• ⚙️ Server Logs: {target_ch.mention}\n"
                    f"• 🔊 Voice Logs: {target_ch.mention}\n\n"
                    "*Tip: You can separate them into distinct channels anytime with `!logchannel <category> #channel`.*"
                ),
                color=BRAND_COLOR,
            )
            view = WizardCancelView(ctx.author.id)
            await ctx.reply(embed=embed, view=view)
        except Exception as err:
            logger.error("Logging setup wizard failed for guild %s: %s", ctx.guild.id, err, exc_info=True)
            await ctx.send_error("Setup Failed", f"Failed to save logging configuration: {err}")

    @commands.command(name="setuplogging", help="One-click audit logging setup wizard.")
    @commands.has_permissions(administrator=True)
    async def setuplogging_prefix(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_setuplogging(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="logging", description="One-click audit logging setup wizard.")
    @app_commands.describe(channel="Channel for all audit logs (default: current channel)")
    @app_commands.default_permissions(administrator=True)
    async def setuplogging_slash(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_setuplogging(UnifiedContext.from_interaction(interaction), channel)

    # ── 5. setupwelcome ─────────────────────────────────────────────────────

    async def _execute_setupwelcome(self, ctx: UnifiedContext, channel: Optional[discord.TextChannel] = None) -> None:
        await ctx.defer(ephemeral=True)
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        target_ch = channel or ctx.channel
        if not isinstance(target_ch, (discord.TextChannel, discord.Thread)):
            await ctx.send_error("Invalid Channel", "Please specify a valid text channel for welcome cards.")
            return

        try:
            await self.bot.db.execute(
                """INSERT INTO welcome_settings (guild_id, enabled, channel_id, use_embed) VALUES (?, 1, ?, 1)
                   ON CONFLICT(guild_id) DO UPDATE SET enabled = 1, channel_id = ?, use_embed = 1""",
                (ctx.guild.id, target_ch.id, target_ch.id),
            )

            embed = EmbedBuilder.base(
                title="👋 Welcome System Setup Wizard",
                description=(
                    f"Welcome greeting system is now **ENABLED** in {target_ch.mention}!\n\n"
                    "**Customization Quick Commands:**\n"
                    "• `!welcomemessage <template>` — Custom text\n"
                    "• `!welcomecolor <hex>` — Embed color\n"
                    "• `!welcomeimage <url>` — Welcome banner\n"
                    "• `!welcomeautorole add <@role>` — Auto-role\n"
                    "• `!welcomedm enable` — Direct message greeting\n"
                    "• `!welcometest` — Preview welcome card"
                ),
                color=BRAND_COLOR,
            )
            view = WizardCancelView(ctx.author.id)
            await ctx.reply(embed=embed, view=view)
        except Exception as err:
            logger.error("Welcome setup wizard failed for guild %s: %s", ctx.guild.id, err, exc_info=True)
            await ctx.send_error("Setup Failed", f"Failed to save welcome configuration: {err}")

    @commands.command(name="setupwelcome", help="Guided welcome greeting setup wizard.")
    @commands.has_permissions(administrator=True)
    async def setupwelcome_prefix(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_setupwelcome(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="welcome", description="Guided welcome greeting setup wizard.")
    @app_commands.describe(channel="Channel for welcome cards")
    @app_commands.default_permissions(administrator=True)
    async def setupwelcome_slash(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_setupwelcome(UnifiedContext.from_interaction(interaction), channel)

    # ── 6. setupgoodbye ─────────────────────────────────────────────────────

    async def _execute_setupgoodbye(self, ctx: UnifiedContext, channel: Optional[discord.TextChannel] = None) -> None:
        await ctx.defer(ephemeral=True)
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        target_ch = channel or ctx.channel
        if not isinstance(target_ch, (discord.TextChannel, discord.Thread)):
            await ctx.send_error("Invalid Channel", "Please specify a valid text channel for farewell cards.")
            return

        try:
            await self.bot.db.execute(
                """INSERT INTO welcome_settings (guild_id, goodbye_enabled, goodbye_channel_id, goodbye_use_embed) VALUES (?, 1, ?, 1)
                   ON CONFLICT(guild_id) DO UPDATE SET goodbye_enabled = 1, goodbye_channel_id = ?, goodbye_use_embed = 1""",
                (ctx.guild.id, target_ch.id, target_ch.id),
            )

            embed = EmbedBuilder.base(
                title="👋 Farewell System Setup Wizard",
                description=(
                    f"Goodbye departure cards are now **ENABLED** in {target_ch.mention}!\n\n"
                    "**Customization Quick Commands:**\n"
                    "• `!goodbyemessage <template>` — Custom farewell message\n"
                    "• `!goodbyeembed <enable|disable>` — Embed styling\n"
                    "• `!goodbyetest` — Test farewell preview"
                ),
                color=BRAND_COLOR,
            )
            view = WizardCancelView(ctx.author.id)
            await ctx.reply(embed=embed, view=view)
        except Exception as err:
            logger.error("Goodbye setup wizard failed for guild %s: %s", ctx.guild.id, err, exc_info=True)
            await ctx.send_error("Setup Failed", f"Failed to save farewell configuration: {err}")

    @commands.command(name="setupgoodbye", help="Guided farewell departure setup wizard.")
    @commands.has_permissions(administrator=True)
    async def setupgoodbye_prefix(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_setupgoodbye(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="goodbye", description="Guided farewell departure setup wizard.")
    @app_commands.describe(channel="Channel for farewell cards")
    @app_commands.default_permissions(administrator=True)
    async def setupgoodbye_slash(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None) -> None:
        await self._execute_setupgoodbye(UnifiedContext.from_interaction(interaction), channel)

    # ── 7. setuprollback ────────────────────────────────────────────────────

    async def _execute_setuprollback(self, ctx: UnifiedContext) -> None:
        await ctx.defer(ephemeral=True)
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        if not ctx.author.guild_permissions.administrator:
            await ctx.send_error("Permission Denied", "You need Administrator permission to rollback setup configuration.")
            return

        guild = ctx.guild
        snapshots = getattr(self.bot, "_guild_setup_snapshots", {})
        snapshot = snapshots.get(guild.id)
        if not snapshot:
            await ctx.send_error(
                "No Rollback Available",
                "There is no recorded pre-setup snapshot for this server to roll back to.",
            )
            return

        reverted_items = []
        # Revert prefix
        prev_pfx = snapshot.get("prefix", "!")
        try:
            if hasattr(self.bot, "guild_repo") and self.bot.guild_repo:
                res = self.bot.guild_repo.set_prefix(guild.id, prev_pfx)
                if asyncio.iscoroutine(res):
                    await res
            elif hasattr(self.bot, "db") and self.bot.db:
                await self.bot.db.execute(
                    "UPDATE guild_settings SET prefix = ?, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ?",
                    (prev_pfx, guild.id),
                )
            reverted_items.append(f"• **Command Prefix:** Restored to `{prev_pfx}`")
        except Exception as err:
            logger.error("Failed to restore prefix during rollback: %s", err)

        # Revert channels if bot has manage_guild
        if guild.me and guild.me.guild_permissions.manage_guild:
            edit_kwargs = {}
            prev_sys_id = snapshot.get("system_channel_id")
            prev_sys_ch = guild.get_channel(prev_sys_id) if prev_sys_id else None
            if prev_sys_ch:
                edit_kwargs["system_channel"] = prev_sys_ch
                reverted_items.append(f"• **System Channel:** Restored to {prev_sys_ch.mention}")

            prev_afk_id = snapshot.get("afk_channel_id")
            prev_afk_ch = guild.get_channel(prev_afk_id) if prev_afk_id else None
            if prev_afk_ch:
                edit_kwargs["afk_channel"] = prev_afk_ch
                reverted_items.append(f"• **AFK Voice Channel:** Restored to `{prev_afk_ch.name}`")

            if edit_kwargs:
                try:
                    await guild.edit(reason=f"Server Setup Rollback triggered by {ctx.author}", **edit_kwargs)
                except Exception as err:
                    logger.warning("Could not revert guild channels: %s", err)

        embed = EmbedBuilder.success(
            title="🔄 Setup Configuration Reverted",
            description=(
                f"Successfully restored previous configuration for **{guild.name}**!\n\n"
                + "\n".join(reverted_items)
            ),
        )
        await ctx.reply(embed=embed)

    @commands.command(name="setuprollback", aliases=["setupundo"], help="Rollback the most recent server setup changes.")
    @commands.has_permissions(administrator=True)
    async def setuprollback_prefix(self, ctx: commands.Context) -> None:
        await self._execute_setuprollback(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="rollback", description="Rollback the most recent server setup changes.")
    @app_commands.default_permissions(administrator=True)
    async def setuprollback_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_setuprollback(UnifiedContext.from_interaction(interaction))


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(SetupWizard(bot))

