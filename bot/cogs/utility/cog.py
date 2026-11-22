"""Comprehensive utility and server information cog for Death Bot."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Union

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.permissions import get_krovex_invite_url

if TYPE_CHECKING:
    from bot.core.bot import DeathBot


class Utility(commands.Cog, name="Utility"):
    """Server diagnostics, user lookups, server statistics, and utility tools."""

    util = app_commands.Group(name="util", description="KROVEX Utility & diagnostic tools")

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    # --------------------------------------------------------------------------
    # 1. Ping / Latency
    # --------------------------------------------------------------------------
    async def _execute_ping(self, ctx: UnifiedContext) -> None:
        """Measure gateway and REST API round-trip latency."""
        start_time = time.perf_counter()
        msg = await ctx.reply("🏓 Pinging gateway...")
        end_time = time.perf_counter()

        rest_latency = (end_time - start_time) * 1000
        ws_latency = self.bot.latency * 1000

        embed = EmbedBuilder.base(
            title="🏓 Pong!",
            description="Diagnostic latency measurements to Discord Gateway and API.",
            color=0x9D4EDD,
        )
        embed.add_field(name="🌐 WebSocket Gateway", value=f"`{ws_latency:.2f} ms`", inline=True)
        embed.add_field(name=f"{KrovexEmoji.LIGHTNING} REST API Latency", value=f"`{rest_latency:.2f} ms`", inline=True)
        if ctx.guild:
            embed.add_field(name="💎 Shard ID", value=f"`{ctx.guild.shard_id}`", inline=True)

        await ctx.edit(msg, content=None, embed=embed)

    @commands.command(name="ping", aliases=["latency"], help="Check bot response latency.")
    async def ping_prefix(self, ctx: commands.Context) -> None:
        await self._execute_ping(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="ping", description="Check bot gateway and REST API response latency.")
    async def ping_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_ping(UnifiedContext.from_interaction(interaction))

    # --------------------------------------------------------------------------
    # 2. Uptime
    # --------------------------------------------------------------------------
    async def _execute_uptime(self, ctx: UnifiedContext) -> None:
        """Display continuous bot runtime duration."""
        uptime_sec = int(self.bot.uptime_seconds)
        days, rem = divmod(uptime_sec, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        formatted = " ".join(parts)

        embed = EmbedBuilder.base(
            title="⏱️ Process Uptime",
            description=f"Death Bot has been running continuously for:\n`{formatted}`",
            color=0x9D4EDD,
        )
        embed.add_field(
            name=f"{KrovexEmoji.ROCKET} Started At",
            value=f"<t:{int(self.bot.start_time.timestamp())}:F>",
            inline=False,
        )
        await ctx.reply(embed=embed)

    @commands.command(name="uptime", help="Display how long the bot has been online.")
    async def uptime_prefix(self, ctx: commands.Context) -> None:
        await self._execute_uptime(UnifiedContext.from_prefix(ctx))

    @util.command(name="uptime", description="Display bot process uptime and launch timestamp.")
    async def uptime_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_uptime(UnifiedContext.from_interaction(interaction))

    # --------------------------------------------------------------------------
    # 3. Botinfo
    # --------------------------------------------------------------------------
    async def _execute_botinfo(self, ctx: UnifiedContext) -> None:
        """Display bot architecture, hardware metrics, and platform info."""
        import platform
        import psutil

        process = psutil.Process()
        memory_mb = process.memory_info().rss / (1024 * 1024)
        cpu_usage = process.cpu_percent()

        total_guilds = len(self.bot.guilds)
        total_users = sum(g.member_count or 0 for g in self.bot.guilds)
        total_shards = self.bot.shard_count or 1

        embed = EmbedBuilder.base(
            title="🔮 Death Bot • System Specifications",
            description="Next-Generation Discord Automation & Entertainment Engine.",
            color=0x9D4EDD,
            thumbnail=self.bot.user.display_avatar.url if self.bot.user else None,
        )
        embed.add_field(
            name="🤖 Application",
            value=f"**Guilds:** `{total_guilds}`\n**Cached Users:** `{total_users}`\n**Shards:** `{total_shards}`",
            inline=True,
        )
        embed.add_field(
            name="⚙️ Hardware / Host",
            value=f"**Memory:** `{memory_mb:.1f} MB`\n**CPU:** `{cpu_usage:.1f}%`\n**Threads:** `{process.num_threads()}`",
            inline=True,
        )
        embed.add_field(
            name="📦 Platform",
            value=f"**Python:** `{platform.python_version()}`\n**discord.py:** `{discord.__version__}`\n**OS:** `{platform.system()} {platform.release()}`",
            inline=True,
        )
        db_status = "Connected (SQLite WAL)" if self.bot.db_manager and self.bot.db_manager.is_connected else "Degraded / Offline"
        embed.add_field(name="🗄️ Database Engine", value=f"`{db_status}`", inline=True)
        embed.add_field(
            name="👑 Developers",
            value=", ".join(f"<@{oid}>" for oid in self.bot.config.owner_ids) or "Not configured",
            inline=True,
        )

        await ctx.reply(embed=embed)

    @commands.command(name="botinfo", aliases=["about", "stats"], help="View bot system specifications and stats.")
    async def botinfo_prefix(self, ctx: commands.Context) -> None:
        await self._execute_botinfo(UnifiedContext.from_prefix(ctx))

    @util.command(name="botinfo", description="View bot specifications, hardware metrics, and runtime stats.")
    async def botinfo_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_botinfo(UnifiedContext.from_interaction(interaction))

    # --------------------------------------------------------------------------
    # 4. Serverinfo
    # --------------------------------------------------------------------------
    async def _execute_serverinfo(self, ctx: UnifiedContext) -> None:
        """Display comprehensive guild metadata, member breakdown, and security level."""
        guild = ctx.guild
        if not guild:
            await ctx.send_error("Server Only", "This command can only be executed within a Discord server.")
            return

        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        roles_count = len(guild.roles)
        emojis_count = len(guild.emojis)
        stickers_count = len(guild.stickers)

        bot_count = sum(1 for m in guild.members if m.bot)
        human_count = (guild.member_count or len(guild.members)) - bot_count

        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.SHIELD_CROWN} Server Information • {guild.name}",
            description=guild.description or "No server description provided.",
            color=0x9D4EDD,
            thumbnail=guild.icon.url if guild.icon else None,
        )
        embed.add_field(name=f"{KrovexEmoji.WHITE_CROWN} Server Owner", value=f"<@{guild.owner_id}>", inline=True)
        embed.add_field(name="🆔 Server ID", value=f"`{guild.id}`", inline=True)
        embed.add_field(name=f"{KrovexEmoji.CRESCENT_MOON} Created On", value=f"<t:{int(guild.created_at.timestamp())}:D>", inline=True)

        embed.add_field(
            name=f"👥 Members ({guild.member_count})",
            value=f"👤 Humans: `{human_count}`\n🤖 Bots: `{bot_count}`",
            inline=True,
        )
        embed.add_field(
            name="📊 Channels",
            value=f"💬 Text: `{text_channels}`\n🔊 Voice: `{voice_channels}`\n📁 Categories: `{categories}`",
            inline=True,
        )
        embed.add_field(
            name=f"{KrovexEmoji.NITRO} Boost Status",
            value=f"**Level:** `Tier {guild.premium_tier}` ({guild.premium_subscription_count} boosts)\n**Verification:** `{guild.verification_level.name.capitalize()}`",
            inline=True,
        )
        embed.add_field(
            name="🎨 Assets",
            value=f"**Roles:** `{roles_count}` | **Emojis:** `{emojis_count}` | **Stickers:** `{stickers_count}`",
            inline=False,
        )
        if guild.banner:
            embed.set_image(url=guild.banner.url)

        await ctx.reply(embed=embed)

    @commands.command(name="serverinfo", aliases=["guildinfo", "si"], help="Display detailed server information.")
    async def serverinfo_prefix(self, ctx: commands.Context) -> None:
        await self._execute_serverinfo(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="serverinfo", description="Display detailed server statistics and guild specifications.")
    async def serverinfo_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_serverinfo(UnifiedContext.from_interaction(interaction))

    # --------------------------------------------------------------------------
    # 5. Userinfo
    # --------------------------------------------------------------------------
    async def _execute_userinfo(self, ctx: UnifiedContext, target: Optional[Union[discord.Member, discord.User]] = None) -> None:
        """Display user identity, account age, guild join timestamp, and roles."""
        user = target or ctx.author
        is_member = isinstance(user, discord.Member)

        embed = EmbedBuilder.base(
            title=f"👤 User Profile • {user.name}",
            color=user.color.value if is_member and user.color.value else 0x9D4EDD,
            thumbnail=user.display_avatar.url,
        )
        embed.add_field(name="Tag / Mention", value=f"{user.mention} (`{user}`)", inline=True)
        embed.add_field(name="🆔 User ID", value=f"`{user.id}`", inline=True)
        embed.add_field(name="🤖 Bot Account", value="`Yes`" if user.bot else "`No`", inline=True)
        embed.add_field(name="📅 Account Created", value=f"<t:{int(user.created_at.timestamp())}:R>", inline=True)

        if is_member:
            if user.joined_at:
                embed.add_field(name="📥 Server Joined", value=f"<t:{int(user.joined_at.timestamp())}:R>", inline=True)
            non_everyone_roles = [r.mention for r in reversed(user.roles) if not r.is_default()]
            roles_text = " ".join(non_everyone_roles[:12]) if non_everyone_roles else "None"
            if len(non_everyone_roles) > 12:
                roles_text += f" (+{len(non_everyone_roles) - 12} more)"
            embed.add_field(name=f"{KrovexEmoji.CUTE_STAR_STATIC} Roles ({len(non_everyone_roles)})", value=roles_text, inline=False)
            embed.add_field(name=f"{KrovexEmoji.LIGHTNING} Key Permissions", value="Administrator" if user.guild_permissions.administrator else ("Manage Server" if user.guild_permissions.manage_guild else "Standard Member"), inline=True)

        await ctx.reply(embed=embed)

    @commands.command(name="userinfo", aliases=["whois", "ui"], help="Display detailed user profile information.")
    async def userinfo_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_userinfo(UnifiedContext.from_prefix(ctx), member)

    @app_commands.command(name="userinfo", description="Display profile information, roles, and dates for a user.")
    @app_commands.describe(user="The user to lookup (defaults to yourself)")
    async def userinfo_slash(self, interaction: discord.Interaction, user: Optional[discord.Member] = None) -> None:
        await self._execute_userinfo(UnifiedContext.from_interaction(interaction), user)

    # --------------------------------------------------------------------------
    # 6. Avatar
    # --------------------------------------------------------------------------
    async def _execute_avatar(self, ctx: UnifiedContext, target: Optional[Union[discord.Member, discord.User]] = None) -> None:
        """Display high-resolution user avatar."""
        user = target or ctx.author
        avatar_url = user.display_avatar.url

        embed = EmbedBuilder.base(
            title=f"🖼️ Avatar • {user.name}",
            description=f"[Click here for Full Resolution]({avatar_url})",
            color=0x9D4EDD,
            image=avatar_url,
        )
        await ctx.reply(embed=embed)

    @commands.command(name="avatar", aliases=["av", "pfp"], help="Display a user's avatar.")
    async def avatar_prefix(self, ctx: commands.Context, member: Optional[Union[discord.Member, discord.User]] = None) -> None:
        await self._execute_avatar(UnifiedContext.from_prefix(ctx), member)

    @app_commands.command(name="avatar", description="View and download a user's avatar.")
    @app_commands.describe(user="The user whose avatar you want to view")
    async def avatar_slash(self, interaction: discord.Interaction, user: Optional[discord.Member] = None) -> None:
        await self._execute_avatar(UnifiedContext.from_interaction(interaction), user)

    # --------------------------------------------------------------------------
    # 7. Banner
    # --------------------------------------------------------------------------
    async def _execute_banner(self, ctx: UnifiedContext, target: Optional[Union[discord.Member, discord.User]] = None) -> None:
        """Fetch and display a user's banner if set."""
        target_user = target or ctx.author
        fetched = await self.bot.fetch_user(target_user.id)

        if not fetched.banner:
            await ctx.send_info("No Banner", f"**{target_user.name}** does not have a custom profile banner set.")
            return

        embed = EmbedBuilder.base(
            title=f"🎨 Profile Banner • {target_user.name}",
            description=f"[Click here for Full Resolution]({fetched.banner.url})",
            color=0x9D4EDD,
            image=fetched.banner.url,
        )
        await ctx.reply(embed=embed)

    @commands.command(name="banner", help="Display a user's profile banner.")
    async def banner_prefix(self, ctx: commands.Context, member: Optional[Union[discord.Member, discord.User]] = None) -> None:
        await self._execute_banner(UnifiedContext.from_prefix(ctx), member)

    @util.command(name="banner", description="View and download a user's profile banner.")
    @app_commands.describe(user="The user whose banner you want to view")
    async def banner_slash(self, interaction: discord.Interaction, user: Optional[discord.Member] = None) -> None:
        await self._execute_banner(UnifiedContext.from_interaction(interaction), user)

    # --------------------------------------------------------------------------
    # 8. Invite
    # --------------------------------------------------------------------------
    async def _execute_invite(self, ctx: UnifiedContext) -> None:
        """Provide bot authorization and OAuth2 invitation link."""
        app_id = (
            getattr(self.bot.config, "client_id", None)
            or getattr(self.bot.config, "application_id", None)
            or (self.bot.user.id if getattr(self.bot, "user", None) else None)
            or getattr(self.bot, "application_id", None)
            or 1570428426974662718
        )
        url = get_krovex_invite_url(int(app_id))

        embed = EmbedBuilder.base(
            title="🔗 Invite KROVEX",
            description=f"Empower your Discord server with advanced Music, Security, and Voice systems.\n\n[**Click here to invite KROVEX**]({url})",
            color=0x9D4EDD,
        )
        embed.add_field(
            name="Security & Permissions",
            value="`Administrator` (Permission integer `8`)\n*(Grants full administrative authority, unremovable role protection, and security shielding)*",
            inline=False,
        )
        await ctx.reply(embed=embed)

    @commands.command(name="invite", help="Get the official bot invite link.")
    async def invite_prefix(self, ctx: commands.Context) -> None:
        await self._execute_invite(UnifiedContext.from_prefix(ctx))

    @util.command(name="invite", description="Get the bot OAuth2 invite link to add Death Bot to your server.")
    async def invite_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_invite(UnifiedContext.from_interaction(interaction))

    # --------------------------------------------------------------------------
    # 9. Support
    # --------------------------------------------------------------------------
    async def _execute_support(self, ctx: UnifiedContext) -> None:
        """Provide community and technical support references."""
        support_url = (
            getattr(self.bot.config, "support_server_url", None)
            or getattr(self.bot.config, "support_url", None)
            or "https://discord.gg/89tXm2ZEqR"
        )
        website_url = getattr(self.bot.config, "website_url", None) or "https://krovex.bot"
        embed = EmbedBuilder.base(
            title=f"{KrovexEmoji.MAKE_TICKET} KROVEX Technical Support",
            description="Need assistance configuring KROVEX or setting up Anti-Nuke, Music, and Voice features?\n\nJoin our official support network and visit our official website.",
            color=0x9D4EDD,
        )
        embed.add_field(name="🌐 Official Website", value=f"[KROVEX Portal]({website_url})", inline=True)
        embed.add_field(name="💬 Discord Community", value=f"[Official Support Server]({support_url})", inline=True)
        await ctx.reply(embed=embed)

    @commands.command(name="support", help="Get link to the official support server and documentation.")
    async def support_prefix(self, ctx: commands.Context) -> None:
        await self._execute_support(UnifiedContext.from_prefix(ctx))

    @util.command(name="support", description="Get links to KROVEX technical support and community.")
    async def support_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_support(UnifiedContext.from_interaction(interaction))

    # --------------------------------------------------------------------------
    # 10. Membercount
    # --------------------------------------------------------------------------
    async def _execute_membercount(self, ctx: UnifiedContext) -> None:
        """Display detailed count of members, humans, and bots in current guild."""
        guild = ctx.guild
        if not guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        total = guild.member_count or len(guild.members)
        bots = sum(1 for m in guild.members if m.bot)
        humans = total - bots

        embed = EmbedBuilder.base(
            title=f"👥 Member Count • {guild.name}",
            color=0x9D4EDD,
        )
        embed.add_field(name="Total Members", value=f"**{total:,}**", inline=True)
        embed.add_field(name="Humans", value=f"**{humans:,}**", inline=True)
        embed.add_field(name="Bots", value=f"**{bots:,}**", inline=True)
        await ctx.reply(embed=embed)

    @commands.command(name="membercount", aliases=["mc", "members"], help="Display total server member count.")
    async def membercount_prefix(self, ctx: commands.Context) -> None:
        await self._execute_membercount(UnifiedContext.from_prefix(ctx))

    @util.command(name="membercount", description="Display real-time member, human, and bot statistics for this server.")
    async def membercount_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_membercount(UnifiedContext.from_interaction(interaction))

    # --------------------------------------------------------------------------
    # 11. Roleinfo
    # --------------------------------------------------------------------------
    async def _execute_roleinfo(self, ctx: UnifiedContext, role: discord.Role) -> None:
        """Display role permissions, color, hoist status, and member count."""
        guild = ctx.guild
        if not guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        embed = EmbedBuilder.base(
            title=f"🎭 Role Information • {role.name}",
            color=role.color.value if role.color.value else 0x9D4EDD,
        )
        embed.add_field(name="Role Mention", value=role.mention, inline=True)
        embed.add_field(name="🆔 Role ID", value=f"`{role.id}`", inline=True)
        embed.add_field(name="Color Hex", value=f"`{str(role.color)}`", inline=True)
        embed.add_field(name="Position", value=f"`{role.position}`", inline=True)
        embed.add_field(name="Members with Role", value=f"**{len(role.members)}**", inline=True)
        embed.add_field(name="Hoisted / Separated", value="`Yes`" if role.hoist else "`No`", inline=True)
        embed.add_field(name="Mentionable", value="`Yes`" if role.mentionable else "`No`", inline=True)
        embed.add_field(name="Managed (Bot / Integration)", value="`Yes`" if role.is_bot_managed() or role.managed else "`No`", inline=True)
        embed.add_field(name="Created On", value=f"<t:{int(role.created_at.timestamp())}:D>", inline=True)

        await ctx.reply(embed=embed)

    @commands.command(name="roleinfo", aliases=["ri"], help="Display detailed specifications for a role.")
    async def roleinfo_prefix(self, ctx: commands.Context, role: discord.Role) -> None:
        await self._execute_roleinfo(UnifiedContext.from_prefix(ctx), role)

    @util.command(name="roleinfo", description="View detailed information, permissions, and members for a role.")
    @app_commands.describe(role="The role to inspect")
    async def roleinfo_slash(self, interaction: discord.Interaction, role: discord.Role) -> None:
        await self._execute_roleinfo(UnifiedContext.from_interaction(interaction), role)

    # --------------------------------------------------------------------------
    # 12. Channelinfo
    # --------------------------------------------------------------------------
    async def _execute_channelinfo(self, ctx: UnifiedContext, channel: Optional[discord.abc.GuildChannel] = None) -> None:
        """Display channel category, type, topic, slowmode, and creation timestamp."""
        target_chan = channel or ctx.channel
        if not isinstance(target_chan, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.CategoryChannel)):
            await ctx.send_error("Error", "Unsupported channel type.")
            return

        embed = EmbedBuilder.base(
            title=f"📁 Channel Information • #{target_chan.name}",
            color=0x9D4EDD,
        )
        embed.add_field(name="Channel Mention", value=target_chan.mention, inline=True)
        embed.add_field(name="🆔 Channel ID", value=f"`{target_chan.id}`", inline=True)
        embed.add_field(name="Type", value=f"`{target_chan.type.name}`", inline=True)
        embed.add_field(name="Category", value=target_chan.category.name if target_chan.category else "None", inline=True)
        embed.add_field(name="Position", value=f"`{target_chan.position}`", inline=True)
        embed.add_field(name="Created On", value=f"<t:{int(target_chan.created_at.timestamp())}:D>", inline=True)

        if isinstance(target_chan, discord.TextChannel):
            embed.add_field(name="Slowmode Delay", value=f"`{target_chan.slowmode_delay}s`", inline=True)
            embed.add_field(name="NSFW", value="`Yes`" if target_chan.is_nsfw() else "`No`", inline=True)
            if target_chan.topic:
                embed.add_field(name="Topic", value=target_chan.topic[:500], inline=False)
        elif isinstance(target_chan, discord.VoiceChannel):
            embed.add_field(name="Bitrate", value=f"`{target_chan.bitrate // 1000} kbps`", inline=True)
            embed.add_field(name="User Limit", value=f"`{target_chan.user_limit or 'Unlimited'}`", inline=True)

        await ctx.reply(embed=embed)

    @commands.command(name="channelinfo", aliases=["ci"], help="Display specifications for a text or voice channel.")
    async def channelinfo_prefix(self, ctx: commands.Context, channel: Optional[discord.abc.GuildChannel] = None) -> None:
        await self._execute_channelinfo(UnifiedContext.from_prefix(ctx), channel)

    @util.command(name="channelinfo", description="View specifications, bitrate, slowmode, and topic of a channel.")
    @app_commands.describe(channel="The channel to inspect (defaults to current channel)")
    async def channelinfo_slash(self, interaction: discord.Interaction, channel: Optional[discord.abc.GuildChannel] = None) -> None:
        await self._execute_channelinfo(UnifiedContext.from_interaction(interaction), channel)

    # --------------------------------------------------------------------------
    # 13. Emojiinfo
    # --------------------------------------------------------------------------
    async def _execute_emojiinfo(self, ctx: UnifiedContext, emoji: discord.Emoji) -> None:
        """Display custom server emoji details."""
        embed = EmbedBuilder.base(
            title=f"😃 Emoji Information • {emoji.name}",
            color=0x9D4EDD,
            thumbnail=emoji.url,
        )
        embed.add_field(name="Name", value=f"`{emoji.name}`", inline=True)
        embed.add_field(name="🆔 Emoji ID", value=f"`{emoji.id}`", inline=True)
        embed.add_field(name="Animated", value="`Yes`" if emoji.animated else "`No`", inline=True)
        embed.add_field(name="Managed", value="`Yes`" if emoji.managed else "`No`", inline=True)
        embed.add_field(name="Created On", value=f"<t:{int(emoji.created_at.timestamp())}:D>", inline=True)
        embed.add_field(name="Syntax", value=f"`<{'a' if emoji.animated else ''}:{emoji.name}:{emoji.id}>`", inline=False)
        embed.add_field(name="Direct Link", value=f"[Click here to view/download]({emoji.url})", inline=False)

        await ctx.reply(embed=embed)

    @commands.command(name="emojiinfo", aliases=["ei"], help="Display details for a custom server emoji.")
    async def emojiinfo_prefix(self, ctx: commands.Context, emoji: discord.Emoji) -> None:
        await self._execute_emojiinfo(UnifiedContext.from_prefix(ctx), emoji)

    @util.command(name="emojiinfo", description="View details, animation status, and URL for a custom emoji.")
    @app_commands.describe(emoji="The custom emoji name or identifier to inspect")
    async def emojiinfo_slash(self, interaction: discord.Interaction, emoji: str) -> None:
        # Search emoji in guild
        found_emoji = None
        if interaction.guild:
            for e in interaction.guild.emojis:
                if e.name.lower() == emoji.lower() or str(e.id) == emoji.strip("<:>:"):
                    found_emoji = e
                    break
        if not found_emoji:
            u_ctx = UnifiedContext.from_interaction(interaction)
            await u_ctx.send_error("Emoji Not Found", f"Could not find custom emoji `{emoji}` in this server.")
            return
        await self._execute_emojiinfo(UnifiedContext.from_interaction(interaction), found_emoji)

    # --------------------------------------------------------------------------
    # 14. Permissions
    # --------------------------------------------------------------------------
    async def _execute_permissions(self, ctx: UnifiedContext, member: Optional[discord.Member] = None) -> None:
        """Display effective channel and server permissions for a member."""
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        target_member = member or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if not target_member:
            await ctx.send_error("Error", "Could not resolve target member.")
            return

        perms = target_member.guild_permissions
        allowed = []
        denied = []

        important_perms = [
            ("Administrator", perms.administrator),
            ("Manage Server", perms.manage_guild),
            ("Manage Roles", perms.manage_roles),
            ("Manage Channels", perms.manage_channels),
            ("Kick Members", perms.kick_members),
            ("Ban Members", perms.ban_members),
            ("Moderate Members (Timeout)", perms.moderate_members),
            ("Manage Messages", perms.manage_messages),
            ("Mention Everyone", perms.mention_everyone),
            ("Manage Webhooks", perms.manage_webhooks),
            ("View Audit Log", perms.view_audit_log),
            ("Mute Members (Voice)", perms.mute_members),
            ("Deafen Members (Voice)", perms.deafen_members),
            ("Move Members (Voice)", perms.move_members),
        ]

        for name, has_perm in important_perms:
            if has_perm:
                allowed.append(f"✅ {name}")
            else:
                denied.append(f"❌ {name}")

        embed = EmbedBuilder.base(
            title=f"🛡️ Key Permissions • {target_member.display_name}",
            color=0x9D4EDD,
            thumbnail=target_member.display_avatar.url,
        )
        embed.add_field(name="Granted Privileges", value="\n".join(allowed) or "None", inline=True)
        embed.add_field(name="Denied Privileges", value="\n".join(denied) or "None", inline=True)

        await ctx.reply(embed=embed)

    @commands.command(name="permissions", aliases=["perms"], help="Check granted key server permissions for a member.")
    async def permissions_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_permissions(UnifiedContext.from_prefix(ctx), member)

    @util.command(name="permissions", description="View key administrative and governance permissions for a member.")
    @app_commands.describe(member="The member whose permissions you want to inspect")
    async def permissions_slash(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        await self._execute_permissions(UnifiedContext.from_interaction(interaction), member)

    # --------------------------------------------------------------------------
    # 15. Delegated Subcommands on /util (Health, Prefix, Profile)
    # --------------------------------------------------------------------------
    @util.command(name="health", description="Run comprehensive subsystem diagnostic health check.")
    async def health_slash(self, interaction: discord.Interaction) -> None:
        sys_cog = self.bot.cogs.get("System & Utility")
        if sys_cog and hasattr(sys_cog, "_execute_health"):
            await sys_cog._execute_health(UnifiedContext.from_interaction(interaction))
        else:
            await interaction.response.send_message("Health subsystem offline.", ephemeral=True)

    @util.command(name="prefix", description="View or set the server command prefix.")
    @app_commands.describe(new_prefix="The new command prefix (leave empty to view current prefix)")
    async def prefix_slash(self, interaction: discord.Interaction, new_prefix: Optional[str] = None) -> None:
        sys_cog = self.bot.cogs.get("System & Utility")
        if sys_cog and hasattr(sys_cog, "_execute_prefix"):
            await sys_cog._execute_prefix(UnifiedContext.from_interaction(interaction), new_prefix)
        else:
            await interaction.response.send_message("System cog offline.", ephemeral=True)

    @util.command(name="profile", description="View a member's profile card, level, and balance.")
    @app_commands.describe(member="Member whose profile to view (defaults to yourself)")
    async def profile_slash(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        soc_cog = self.bot.cogs.get("Social")
        if soc_cog and hasattr(soc_cog, "_execute_profile"):
            await soc_cog._execute_profile(UnifiedContext.from_interaction(interaction), member)
        else:
            await interaction.response.send_message("Social cog offline.", ephemeral=True)


async def setup(bot: DeathBot) -> None:
    """Setup hook to register utility cog."""
    await bot.add_cog(Utility(bot))
