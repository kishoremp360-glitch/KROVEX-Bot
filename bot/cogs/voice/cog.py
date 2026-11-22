"""Voice channel activity tracking and status cog."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder

if TYPE_CHECKING:
    from bot.core.bot import DeathBot


class Voice(commands.Cog, name="Voice System"):
    """Voice channel activity monitoring, statistics, and live status displays."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    async def _execute_voicestats(self, ctx: UnifiedContext) -> None:
        """Shared logic for voicestats."""
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        if not self.bot.voice_service:
            await ctx.send_error("Service Offline", "Voice service is currently uninitialized.")
            return

        total_connected = self.bot.voice_service.get_active_voice_count(ctx.guild)
        channels_summary = self.bot.voice_service.get_voice_channels_summary(ctx.guild)

        embed = EmbedBuilder.base(
            title=f"🎙️ Voice Activity • {ctx.guild.name}",
            description=f"Total Connected Members: **{total_connected}**",
            color=0x9D4EDD,
        )

        if channels_summary:
            for item in channels_summary[:8]:
                names = ", ".join(item["members"])
                embed.add_field(
                    name=f"🔊 {item['channel_name']} ({item['member_count']})",
                    value=names[:1024] or "Empty",
                    inline=False,
                )
        else:
            embed.add_field(
                name="Voice Channels",
                value="*No members currently in voice channels.*",
                inline=False,
            )

        await ctx.reply(embed=embed)

    @commands.command(name="voicestats", aliases=["voiceinfo", "voicestat"], help="View live voice channel statistics for this server.")
    async def voicestats_prefix(self, ctx: commands.Context) -> None:
        await self._execute_voicestats(UnifiedContext.from_prefix(ctx))

    async def _execute_voicetime(self, ctx: UnifiedContext, target_user: Optional[discord.Member] = None) -> None:
        """Shared logic for voice time tracking."""
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return

        member = target_user or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if not member:
            await ctx.send_error("Error", "Could not resolve target member.")
            return

        total_seconds = 0
        if self.bot.voice_repo:
            total_seconds = await self.bot.voice_repo.get_total_voice_time(ctx.guild.id, member.id)

        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        embed = EmbedBuilder.base(
            title=f"⏱️ Voice Time Tracker",
            description=f"Recorded voice activity for **{member.display_name}** in **{ctx.guild.name}**:",
            color=0x9D4EDD,
            thumbnail=member.display_avatar.url,
        )
        embed.add_field(
            name="Total Duration",
            value=f"**{hours}** hours, **{minutes}** minutes, **{seconds}** seconds",
            inline=False,
        )
        await ctx.reply(embed=embed)

    @commands.command(name="voicetime", aliases=["vctime"], help="Check total voice time spent in this server.")
    async def voicetime_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_voicetime(UnifiedContext.from_prefix(ctx), member)

    async def _execute_vcclaim(self, ctx: commands.Context) -> None:
        """Shared logic for claiming temporary voice channel ownership."""
        author = ctx.author
        if not isinstance(author, discord.Member) or not ctx.guild:
            await ctx.reply("❌ This command must be used inside a server.")
            return

        if not author.voice or not isinstance(author.voice.channel, discord.VoiceChannel):
            await ctx.reply("❌ You must be connected to a voice channel to claim it.")
            return

        vc = author.voice.channel
        if not self.bot.vc_repo:
            await ctx.reply("❌ VC service is unavailable.")
            return

        record = await self.bot.vc_repo.get_vc_owner(ctx.guild.id, vc.id)
        current_owner_id = record.get("owner_id") if record else None

        if current_owner_id == author.id:
            await ctx.reply("👑 You are already the designated owner of this voice channel.")
            return

        # Check if the previous owner is still present in the VC
        if current_owner_id:
            existing_owner_member = ctx.guild.get_member(current_owner_id)
            if existing_owner_member and existing_owner_member in vc.members:
                await ctx.reply(f"⛔ Cannot claim: Channel owner {existing_owner_member.mention} is still connected.")
                return

        # Grant ownership
        await self.bot.vc_repo.set_vc_owner(ctx.guild.id, vc.id, author.id)
        embed = EmbedBuilder.success(
            title="👑 Voice Channel Ownership Claimed",
            description=f"{author.mention} is now the recognized sovereign of {vc.mention}.",
        )
        await ctx.reply(embed=embed)

    @commands.command(name="vcclaim", aliases=["claimvc"], help="Claim ownership of an abandoned temporary voice channel.")
    async def vc_claim(self, ctx: commands.Context) -> None:
        await self._execute_vcclaim(ctx)

    async def _execute_vctransfer(self, ctx: commands.Context, target: discord.Member) -> None:
        """Shared logic for transferring voice channel ownership."""
        author = ctx.author
        if not isinstance(author, discord.Member) or not ctx.guild:
            await ctx.reply("❌ This command must be used inside a server.")
            return

        if not author.voice or not isinstance(author.voice.channel, discord.VoiceChannel):
            await ctx.reply("❌ You must be connected to a voice channel to transfer it.")
            return

        vc = author.voice.channel
        if not self.bot.vc_repo:
            await ctx.reply("❌ VC service is unavailable.")
            return

        record = await self.bot.vc_repo.get_vc_owner(ctx.guild.id, vc.id)
        current_owner_id = record.get("owner_id") if record else None

        is_sovereign = author.id == ctx.guild.owner_id
        is_owner = current_owner_id == author.id

        if not (is_sovereign or is_owner):
            await ctx.reply("⛔ Only the current channel owner or server sovereign can transfer ownership.")
            return

        if target not in vc.members or target.bot:
            await ctx.reply(f"❌ {target.mention} must be an active human member in {vc.mention}.")
            return

        await self.bot.vc_repo.set_vc_owner(ctx.guild.id, vc.id, target.id)
        embed = EmbedBuilder.success(
            title="👑 Voice Channel Ownership Transferred",
            description=f"Ownership of {vc.mention} was transferred to {target.mention}.",
        )
        await ctx.reply(embed=embed)

    @commands.command(name="vctransfer", aliases=["transfervc"], help="Transfer voice channel ownership to another participant.")
    async def vc_transfer(self, ctx: commands.Context, target: discord.Member) -> None:
        await self._execute_vctransfer(ctx, target)

    async def _execute_vcowner(self, ctx: commands.Context) -> None:
        """Shared logic for inspecting voice channel ownership."""
        author = ctx.author
        if not isinstance(author, discord.Member) or not ctx.guild:
            await ctx.reply("❌ This command must be used inside a server.")
            return

        if not author.voice or not isinstance(author.voice.channel, discord.VoiceChannel):
            await ctx.reply("❌ You must be connected to a voice channel.")
            return

        vc = author.voice.channel
        if not self.bot.vc_repo:
            await ctx.reply("❌ VC service is unavailable.")
            return

        record = await self.bot.vc_repo.get_vc_owner(ctx.guild.id, vc.id)
        owner_id = record.get("owner_id") if record else None

        if not owner_id:
            await ctx.reply(f"ℹ️ {vc.mention} has no registered owner.")
            return

        owner_member = ctx.guild.get_member(owner_id)
        owner_name = owner_member.mention if owner_member else f"`{owner_id}` (Offline)"
        embed = EmbedBuilder.base(
            title="👑 Channel Ownership Directory",
            description=f"The current registered owner of {vc.mention} is {owner_name}.",
            color=0x9D4EDD,
        )
        await ctx.reply(embed=embed)

    @commands.command(name="vcowner", aliases=["whoowns"], help="Inspect the recognized owner of your current voice channel.")
    async def vc_owner(self, ctx: commands.Context) -> None:
        await self._execute_vcowner(ctx)


async def setup(bot: DeathBot) -> None:
    """Setup hook to register cog."""
    await bot.add_cog(Voice(bot))

