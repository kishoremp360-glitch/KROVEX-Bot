"""Owner VC Cog — Advanced voice channel moderation and management commands.

25 unique commands covering voice moderation, state control, channel management,
member movement, and voice statistics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

BRAND_COLOR = 0x9D4EDD
ERROR_COLOR = 0xFF4444

VALID_REGIONS = {
    "automatic": None,
    "us-west": "us-west",
    "us-east": "us-east",
    "us-south": "us-south",
    "us-central": "us-central",
    "singapore": "singapore",
    "southafrica": "southafrica",
    "sydney": "sydney",
    "europe": "europe",
    "brazil": "brazil",
    "hongkong": "hongkong",
    "russia": "russia",
    "japan": "japan",
    "india": "india",
}


class OwnerVC(commands.GroupCog, group_name="vc", group_description="Voice channel management and owner controls"):
    """Advanced owner-level voice channel moderation and management."""

    def __init__(self, bot: "DeathBot") -> None:
        super().__init__()
        self.bot = bot

    # ─────────────────────────── PERMISSION HELPERS ───────────────────────────

    def _has_vc_perms(self, member: discord.Member) -> bool:
        return member.guild_permissions.administrator or member.guild_permissions.manage_channels

    def _check_hierarchy(self, bot_member: discord.Member, target: discord.Member) -> bool:
        return bot_member.top_role > target.top_role

    # ──────────────────────────── DB HELPERS ──────────────────────────────────

    async def _get_vc_bans(self, guild_id: int, channel_id: int) -> List:
        try:
            return await self.bot.db.fetchall(
                "SELECT * FROM vc_bans WHERE guild_id=? AND channel_id=?",
                (guild_id, channel_id),
            )
        except Exception:
            return []

    async def _add_vc_ban(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        banned_by: int,
        reason: str,
    ) -> None:
        try:
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO vc_bans "
                "(guild_id, channel_id, user_id, banned_by, reason) VALUES (?,?,?,?,?)",
                (guild_id, channel_id, user_id, banned_by, reason),
            )
        except Exception:
            pass

    async def _remove_vc_ban(self, guild_id: int, channel_id: int, user_id: int) -> None:
        try:
            await self.bot.db.execute(
                "DELETE FROM vc_bans WHERE guild_id=? AND channel_id=? AND user_id=?",
                (guild_id, channel_id, user_id),
            )
        except Exception:
            pass

    async def _clear_vc_bans(self, guild_id: int, channel_id: int) -> None:
        try:
            await self.bot.db.execute(
                "DELETE FROM vc_bans WHERE guild_id=? AND channel_id=?",
                (guild_id, channel_id),
            )
        except Exception:
            pass

    # ──────────────────── SHARED PERMISSION / STATE CHECKER ───────────────────

    def _resolve_caller_vc(
        self,
        uctx: UnifiedContext,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> tuple[Optional[discord.VoiceChannel], Optional[str]]:
        """Return (voice_channel, error_message).  error_message is None on success."""
        author = uctx.author
        if not isinstance(author, discord.Member):
            return None, "This command must be used in a server."

        if not self._has_vc_perms(author):
            return None, "You need **Manage Channels** or **Administrator** permission."

        if channel is not None:
            if not isinstance(channel, discord.VoiceChannel):
                return None, "The specified channel is not a voice channel."
            return channel, None

        if author.voice and author.voice.channel and isinstance(author.voice.channel, discord.VoiceChannel):
            return author.voice.channel, None

        return None, "You must be in a voice channel, or specify one."

    def _is_protected_member(self, member: Union[discord.Member, discord.User], guild: Optional[discord.Guild]) -> bool:
        if not member:
            return False
        if getattr(member, "bot", False):
            return True
        if guild and member.id == guild.owner_id:
            return True
        if hasattr(self.bot, "is_bot_owner") and callable(self.bot.is_bot_owner):
            try:
                res = self.bot.is_bot_owner(member)
                if isinstance(res, bool) and res:
                    return True
            except Exception:
                pass
        raw_owners = getattr(self.bot.config, "owner_ids", [])
        if member.id in raw_owners or str(member.id) in [str(x) for x in raw_owners]:
            return True
        app_owners = getattr(self.bot, "owner_ids", set()) or set()
        if member.id in app_owners or str(member.id) in [str(x) for x in app_owners]:
            return True
        return False

    def _check_target(
        self,
        uctx: UnifiedContext,
        target: discord.Member,
    ) -> Optional[str]:
        """Return an error string if the target cannot be acted on, else None."""
        guild = uctx.guild
        if guild is None:
            return "No guild context."
        if target.voice is None or target.voice.channel is None:
            return f"{target.mention} is not in a voice channel."
        if self._is_protected_member(target, guild):
            return "Cannot perform this action on the server owner or bot owner."
        bot_member = guild.me
        if bot_member is None:
            return "Cannot resolve bot member."
        if not self._check_hierarchy(bot_member, target):
            return f"My role is not high enough to act on {target.mention}."
        return None

    # ═══════════════════════════════════════════════════════════════════════════
    #  1. VCKICK
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vckick(
        self, uctx: UnifiedContext, member: discord.Member, reason: str
    ) -> None:
        await uctx.defer(ephemeral=True)
        err = self._check_target(uctx, member)
        if err:
            await uctx.send_error("Cannot Kick", err)
            return
        _, perr = self._resolve_caller_vc(uctx)
        if perr:
            await uctx.send_error("Permission Error", perr)
            return
        guild = uctx.guild
        bot_member = guild.me  # type: ignore
        if not bot_member.guild_permissions.move_members:
            await uctx.send_error("Missing Permission", "I need **Move Members** permission.")
            return
        try:
            await member.move_to(None, reason=reason or "Owner VC Kick")
            embed = EmbedBuilder.base(
                title="🎙️ Member Kicked from VC",
                description=f"{member.mention} has been removed from their voice channel.",
                color=BRAND_COLOR,
            )
            embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "I do not have permission to move that member.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vckick", help="Kick a member from their voice channel.")
    async def vckick_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided") -> None:
        uctx = UnifiedContext.from_prefix(ctx)
        await self._execute_vckick(uctx, member, reason)

    @app_commands.command(name="kick", description="Kick a member from their voice channel.")
    @app_commands.describe(member="The member to kick", reason="Reason for the kick")
    async def vckick_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        uctx = UnifiedContext.from_interaction(interaction)
        await self._execute_vckick(uctx, member, reason)

    # ═══════════════════════════════════════════════════════════════════════════
    #  2. VCBAN
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcban(
        self, uctx: UnifiedContext, member: discord.Member, reason: str
    ) -> None:
        await uctx.defer(ephemeral=True)
        err = self._check_target(uctx, member)
        if err:
            await uctx.send_error("Cannot Ban", err)
            return
        _, perr = self._resolve_caller_vc(uctx)
        if perr:
            await uctx.send_error("Permission Error", perr)
            return
        channel = member.voice.channel  # type: ignore
        if not isinstance(channel, discord.VoiceChannel):
            await uctx.send_error("Error", "Target is not in a standard voice channel.")
            return
        try:
            await channel.set_permissions(member, connect=False, reason=reason or "Owner VC Ban")
            await self._add_vc_ban(
                channel.guild.id, channel.id, member.id,
                uctx.author.id, reason or "No reason provided"
            )
            await member.move_to(None, reason=reason or "Owner VC Ban")
            embed = EmbedBuilder.base(
                title="🚫 Member VC Banned",
                description=f"{member.mention} has been banned from **{channel.name}**.",
                color=ERROR_COLOR,
            )
            embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "I lack permissions to manage that channel.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vcban", help="Ban a member from their current voice channel.")
    async def vcban_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided") -> None:
        await self._execute_vcban(UnifiedContext.from_prefix(ctx), member, reason)

    @app_commands.command(name="ban", description="Ban a member from their current voice channel.")
    @app_commands.describe(member="Member to ban", reason="Reason")
    async def vcban_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        await self._execute_vcban(UnifiedContext.from_interaction(interaction), member, reason)

    # ═══════════════════════════════════════════════════════════════════════════
    #  3. VCUNBAN
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcunban(
        self,
        uctx: UnifiedContext,
        member: discord.Member,
        channel: Optional[discord.VoiceChannel],
    ) -> None:
        await uctx.defer(ephemeral=True)
        _, perr = self._resolve_caller_vc(uctx, channel)
        if perr and channel is None:
            # Try to get caller's vc or accept lack of one for guild-wide unban
            pass

        author = uctx.author
        if not isinstance(author, discord.Member) or not self._has_vc_perms(author):
            await uctx.send_error("Permission Error", "You need **Manage Channels** or **Administrator**.")
            return

        guild = uctx.guild
        if guild is None:
            await uctx.send_error("Error", "Must be used in a server.")
            return

        channels_to_unban: List[discord.VoiceChannel] = []
        if channel:
            channels_to_unban = [channel]
        else:
            channels_to_unban = [c for c in guild.voice_channels]

        unbanned_in = []
        for vc in channels_to_unban:
            overwrite = vc.overwrites_for(member)
            if overwrite.connect is False:
                overwrite.connect = None
                try:
                    await vc.set_permissions(member, overwrite=overwrite if not overwrite.is_empty() else None, reason="VC Unban")
                    await self._remove_vc_ban(guild.id, vc.id, member.id)
                    unbanned_in.append(vc.name)
                except discord.Forbidden:
                    pass

        if unbanned_in:
            embed = EmbedBuilder.base(
                title="✅ Member VC Unbanned",
                description=f"{member.mention} can now connect to: **{', '.join(unbanned_in)}**.",
                color=BRAND_COLOR,
            )
        else:
            embed = EmbedBuilder.base(
                title="ℹ️ Nothing to Unban",
                description=f"{member.mention} has no active VC bans.",
                color=BRAND_COLOR,
            )
        await uctx.reply(embed=embed)

    @commands.command(name="vcunban", help="Unban a member from a voice channel.")
    async def vcunban_prefix(self, ctx: commands.Context, member: discord.Member, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcunban(UnifiedContext.from_prefix(ctx), member, channel)

    @app_commands.command(name="unban", description="Remove a voice channel ban from a member.")
    @app_commands.describe(member="Member to unban", channel="Specific VC (or leave blank for all)")
    async def vcunban_slash(self, interaction: discord.Interaction, member: discord.Member, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcunban(UnifiedContext.from_interaction(interaction), member, channel)

    # ═══════════════════════════════════════════════════════════════════════════
    #  4. VCKICKALL
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vckickall(
        self, uctx: UnifiedContext, reason: str
    ) -> None:
        await uctx.defer(ephemeral=True)
        author = uctx.author
        if not isinstance(author, discord.Member):
            await uctx.send_error("Error", "Must be used in a server.")
            return
        if not author.guild_permissions.administrator:
            await uctx.send_error("Permission Error", "You need **Administrator** permission.")
            return
        vc, err = self._resolve_caller_vc(uctx)
        if err:
            await uctx.send_error("Error", err)
            return
        guild = uctx.guild
        kicked = 0
        for m in list(vc.members):  # type: ignore
            if self._is_protected_member(m, guild):  # type: ignore
                continue
            try:
                await m.move_to(None, reason=reason or "Mass VC Kick")
                kicked += 1
            except Exception:
                pass
        embed = EmbedBuilder.base(
            title="🎙️ Mass VC Kick Complete",
            description=f"Kicked **{kicked}** member(s) from **{vc.name}**.",  # type: ignore
            color=BRAND_COLOR,
        )
        await uctx.reply(embed=embed)

    @commands.command(name="vckickall", help="Kick all members from your current voice channel.")
    async def vckickall_prefix(self, ctx: commands.Context, *, reason: str = "No reason provided") -> None:
        await self._execute_vckickall(UnifiedContext.from_prefix(ctx), reason)

    @app_commands.command(name="kickall", description="Kick all members from your current voice channel.")
    @app_commands.describe(reason="Reason for the mass kick")
    async def vckickall_slash(self, interaction: discord.Interaction, reason: str = "No reason provided") -> None:
        await self._execute_vckickall(UnifiedContext.from_interaction(interaction), reason)

    # ═══════════════════════════════════════════════════════════════════════════
    #  5. VCBANALL
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcbanall(
        self, uctx: UnifiedContext, reason: str
    ) -> None:
        await uctx.defer(ephemeral=True)
        author = uctx.author
        if not isinstance(author, discord.Member):
            await uctx.send_error("Error", "Must be used in a server.")
            return
        if not author.guild_permissions.administrator:
            await uctx.send_error("Permission Error", "You need **Administrator** permission.")
            return
        vc, err = self._resolve_caller_vc(uctx)
        if err:
            await uctx.send_error("Error", err)
            return
        guild = uctx.guild
        banned = 0
        for m in list(vc.members):  # type: ignore
            if self._is_protected_member(m, guild):  # type: ignore
                continue
            try:
                await vc.set_permissions(m, connect=False, reason=reason or "Mass VC Ban")  # type: ignore
                await self._add_vc_ban(guild.id, vc.id, m.id, author.id, reason or "Mass VC Ban")  # type: ignore
                await m.move_to(None, reason=reason or "Mass VC Ban")
                banned += 1
            except Exception:
                pass
        embed = EmbedBuilder.base(
            title="🚫 Mass VC Ban Complete",
            description=f"Banned **{banned}** member(s) from **{vc.name}**.",  # type: ignore
            color=ERROR_COLOR,
        )
        await uctx.reply(embed=embed)

    @commands.command(name="vcbanall", help="Ban all current members in your voice channel.")
    async def vcbanall_prefix(self, ctx: commands.Context, *, reason: str = "No reason provided") -> None:
        await self._execute_vcbanall(UnifiedContext.from_prefix(ctx), reason)

    @app_commands.command(name="banall", description="Ban all current members in your voice channel.")
    @app_commands.describe(reason="Reason for the mass ban")
    async def vcbanall_slash(self, interaction: discord.Interaction, reason: str = "No reason provided") -> None:
        await self._execute_vcbanall(UnifiedContext.from_interaction(interaction), reason)

    # ═══════════════════════════════════════════════════════════════════════════
    #  6. VCUNBANALL
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcunbanall(
        self, uctx: UnifiedContext, channel: Optional[discord.VoiceChannel]
    ) -> None:
        await uctx.defer(ephemeral=True)
        vc, err = self._resolve_caller_vc(uctx, channel)
        if err:
            await uctx.send_error("Error", err)
            return
        guild = uctx.guild
        cleared = 0
        for target, overwrite in list(vc.overwrites.items()):  # type: ignore
            if isinstance(target, discord.Member) and overwrite.connect is False:
                overwrite.connect = None
                try:
                    await vc.set_permissions(target, overwrite=overwrite if not overwrite.is_empty() else None)  # type: ignore
                    cleared += 1
                except Exception:
                    pass
        await self._clear_vc_bans(guild.id, vc.id)  # type: ignore
        embed = EmbedBuilder.base(
            title="✅ All VC Bans Cleared",
            description=f"Removed **{cleared}** VC ban overwrite(s) from **{vc.name}**.",  # type: ignore
            color=BRAND_COLOR,
        )
        await uctx.reply(embed=embed)

    @commands.command(name="vcunbanall", help="Remove all VC bans from a voice channel.")
    async def vcunbanall_prefix(self, ctx: commands.Context, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcunbanall(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="unbanall", description="Remove all VC bans from a voice channel.")
    @app_commands.describe(channel="Voice channel to clear bans from (defaults to yours)")
    async def vcunbanall_slash(self, interaction: discord.Interaction, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcunbanall(UnifiedContext.from_interaction(interaction), channel)

    # ═══════════════════════════════════════════════════════════════════════════
    #  7. VCMUTE
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcmute(
        self, uctx: UnifiedContext, member: discord.Member, reason: str
    ) -> None:
        await uctx.defer(ephemeral=True)
        author = uctx.author
        if not isinstance(author, discord.Member) or not author.guild_permissions.mute_members:
            await uctx.send_error("Permission Error", "You need **Mute Members** permission.")
            return
        err = self._check_target(uctx, member)
        if err:
            await uctx.send_error("Error", err)
            return
        try:
            await member.edit(mute=True, reason=reason or "Owner VC Mute")
            embed = EmbedBuilder.base(
                title="🔇 Member Muted",
                description=f"{member.mention} has been server-muted.",
                color=BRAND_COLOR,
            )
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "Cannot mute that member.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vcmute", help="Server-mute a member in voice.")
    async def vcmute_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided") -> None:
        await self._execute_vcmute(UnifiedContext.from_prefix(ctx), member, reason)

    @app_commands.command(name="mute", description="Server-mute a member in voice.")
    @app_commands.describe(member="Member to mute", reason="Reason")
    async def vcmute_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        await self._execute_vcmute(UnifiedContext.from_interaction(interaction), member, reason)

    # ═══════════════════════════════════════════════════════════════════════════
    #  8. VCUNMUTE
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcunmute(
        self, uctx: UnifiedContext, member: discord.Member
    ) -> None:
        await uctx.defer(ephemeral=True)
        author = uctx.author
        if not isinstance(author, discord.Member) or not author.guild_permissions.mute_members:
            await uctx.send_error("Permission Error", "You need **Mute Members** permission.")
            return
        try:
            await member.edit(mute=False, reason="Owner VC Unmute")
            embed = EmbedBuilder.base(
                title="🔊 Member Unmuted",
                description=f"{member.mention} has been server-unmuted.",
                color=BRAND_COLOR,
            )
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "Cannot unmute that member.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vcunmute", help="Remove server-mute from a member in voice.")
    async def vcunmute_prefix(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._execute_vcunmute(UnifiedContext.from_prefix(ctx), member)

    @app_commands.command(name="unmute", description="Remove server-mute from a voice member.")
    @app_commands.describe(member="Member to unmute")
    async def vcunmute_slash(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await self._execute_vcunmute(UnifiedContext.from_interaction(interaction), member)

    # ═══════════════════════════════════════════════════════════════════════════
    #  9. VCMUTEALL
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcmuteall(self, uctx: UnifiedContext) -> None:
        await uctx.defer(ephemeral=True)
        author = uctx.author
        if not isinstance(author, discord.Member):
            await uctx.send_error("Error", "Must be used in a server.")
            return
        perms = author.guild_permissions
        if not (perms.administrator and perms.mute_members):
            await uctx.send_error("Permission Error", "You need **Administrator** + **Mute Members**.")
            return
        vc, err = self._resolve_caller_vc(uctx)
        if err:
            await uctx.send_error("Error", err)
            return
        guild = uctx.guild
        muted = 0
        for m in list(vc.members):  # type: ignore
            if self._is_protected_member(m, guild):  # type: ignore
                continue
            try:
                await m.edit(mute=True, reason="Mass VC Mute")
                muted += 1
            except Exception:
                pass
        embed = EmbedBuilder.base(
            title="🔇 Mass Mute Complete",
            description=f"Muted **{muted}** member(s) in **{vc.name}**.",  # type: ignore
            color=BRAND_COLOR,
        )
        await uctx.reply(embed=embed)

    @commands.command(name="vcmuteall", help="Server-mute all members in your voice channel.")
    async def vcmuteall_prefix(self, ctx: commands.Context) -> None:
        await self._execute_vcmuteall(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="muteall", description="Server-mute all members in your voice channel.")
    async def vcmuteall_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_vcmuteall(UnifiedContext.from_interaction(interaction))

    # ═══════════════════════════════════════════════════════════════════════════
    #  10. VCUNMUTEALL
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcunmuteall(self, uctx: UnifiedContext) -> None:
        await uctx.defer(ephemeral=True)
        author = uctx.author
        if not isinstance(author, discord.Member) or not author.guild_permissions.mute_members:
            await uctx.send_error("Permission Error", "You need **Mute Members** permission.")
            return
        vc, err = self._resolve_caller_vc(uctx)
        if err:
            await uctx.send_error("Error", err)
            return
        unmuted = 0
        for m in list(vc.members):  # type: ignore
            try:
                await m.edit(mute=False, reason="Mass VC Unmute")
                unmuted += 1
            except Exception:
                pass
        embed = EmbedBuilder.base(
            title="🔊 Mass Unmute Complete",
            description=f"Unmuted **{unmuted}** member(s) in **{vc.name}**.",  # type: ignore
            color=BRAND_COLOR,
        )
        await uctx.reply(embed=embed)

    @commands.command(name="vcunmuteall", help="Unmute all members in your voice channel.")
    async def vcunmuteall_prefix(self, ctx: commands.Context) -> None:
        await self._execute_vcunmuteall(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="unmuteall", description="Unmute all members in your voice channel.")
    async def vcunmuteall_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_vcunmuteall(UnifiedContext.from_interaction(interaction))

    # ═══════════════════════════════════════════════════════════════════════════
    #  11. VCDEAFEN
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcdeafen(
        self, uctx: UnifiedContext, member: discord.Member, reason: str
    ) -> None:
        await uctx.defer(ephemeral=True)
        author = uctx.author
        if not isinstance(author, discord.Member) or not author.guild_permissions.deafen_members:
            await uctx.send_error("Permission Error", "You need **Deafen Members** permission.")
            return
        err = self._check_target(uctx, member)
        if err:
            await uctx.send_error("Error", err)
            return
        try:
            await member.edit(deafen=True, reason=reason or "Owner VC Deafen")
            embed = EmbedBuilder.base(
                title="🔕 Member Deafened",
                description=f"{member.mention} has been server-deafened.",
                color=BRAND_COLOR,
            )
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "Cannot deafen that member.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vcdeafen", help="Server-deafen a member in voice.")
    async def vcdeafen_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided") -> None:
        await self._execute_vcdeafen(UnifiedContext.from_prefix(ctx), member, reason)

    @app_commands.command(name="deafen", description="Server-deafen a member in voice.")
    @app_commands.describe(member="Member to deafen", reason="Reason")
    async def vcdeafen_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        await self._execute_vcdeafen(UnifiedContext.from_interaction(interaction), member, reason)

    # ═══════════════════════════════════════════════════════════════════════════
    #  12. VCUNDEAFEN
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcundeafen(
        self, uctx: UnifiedContext, member: discord.Member
    ) -> None:
        await uctx.defer(ephemeral=True)
        author = uctx.author
        if not isinstance(author, discord.Member) or not author.guild_permissions.deafen_members:
            await uctx.send_error("Permission Error", "You need **Deafen Members** permission.")
            return
        try:
            await member.edit(deafen=False, reason="Owner VC Undeafen")
            embed = EmbedBuilder.base(
                title="🔔 Member Undeafened",
                description=f"{member.mention} has been server-undeafened.",
                color=BRAND_COLOR,
            )
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "Cannot undeafen that member.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vcundeafen", help="Remove server-deafen from a member.")
    async def vcundeafen_prefix(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._execute_vcundeafen(UnifiedContext.from_prefix(ctx), member)

    @app_commands.command(name="undeafen", description="Remove server-deafen from a voice member.")
    @app_commands.describe(member="Member to undeafen")
    async def vcundeafen_slash(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await self._execute_vcundeafen(UnifiedContext.from_interaction(interaction), member)

    # ═══════════════════════════════════════════════════════════════════════════
    #  13. VCDEAFENALL
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcdeafenall(self, uctx: UnifiedContext) -> None:
        await uctx.defer(ephemeral=True)
        author = uctx.author
        if not isinstance(author, discord.Member) or not author.guild_permissions.deafen_members:
            await uctx.send_error("Permission Error", "You need **Deafen Members** permission.")
            return
        vc, err = self._resolve_caller_vc(uctx)
        if err:
            await uctx.send_error("Error", err)
            return
        guild = uctx.guild
        deafened = 0
        for m in list(vc.members):  # type: ignore
            if self._is_protected_member(m, guild):  # type: ignore
                continue
            try:
                await m.edit(deafen=True, reason="Mass VC Deafen")
                deafened += 1
            except Exception:
                pass
        embed = EmbedBuilder.base(
            title="🔕 Mass Deafen Complete",
            description=f"Deafened **{deafened}** member(s) in **{vc.name}**.",  # type: ignore
            color=BRAND_COLOR,
        )
        await uctx.reply(embed=embed)

    @commands.command(name="vcdeafenall", help="Server-deafen all members in your voice channel.")
    async def vcdeafenall_prefix(self, ctx: commands.Context) -> None:
        await self._execute_vcdeafenall(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="deafenall", description="Server-deafen all members in your voice channel.")
    async def vcdeafenall_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_vcdeafenall(UnifiedContext.from_interaction(interaction))

    # ═══════════════════════════════════════════════════════════════════════════
    #  14. VCUNDEAFENALL
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcundeafenall(self, uctx: UnifiedContext) -> None:
        await uctx.defer(ephemeral=True)
        author = uctx.author
        if not isinstance(author, discord.Member) or not author.guild_permissions.deafen_members:
            await uctx.send_error("Permission Error", "You need **Deafen Members** permission.")
            return
        vc, err = self._resolve_caller_vc(uctx)
        if err:
            await uctx.send_error("Error", err)
            return
        undeafened = 0
        for m in list(vc.members):  # type: ignore
            try:
                await m.edit(deafen=False, reason="Mass VC Undeafen")
                undeafened += 1
            except Exception:
                pass
        embed = EmbedBuilder.base(
            title="🔔 Mass Undeafen Complete",
            description=f"Undeafened **{undeafened}** member(s) in **{vc.name}**.",  # type: ignore
            color=BRAND_COLOR,
        )
        await uctx.reply(embed=embed)

    @commands.command(name="vcundeafenall", help="Undeafen all members in your voice channel.")
    async def vcundeafenall_prefix(self, ctx: commands.Context) -> None:
        await self._execute_vcundeafenall(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="undeafenall", description="Undeafen all members in your voice channel.")
    async def vcundeafenall_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_vcundeafenall(UnifiedContext.from_interaction(interaction))

    # ═══════════════════════════════════════════════════════════════════════════
    #  15. VCLOCK
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vclock(
        self, uctx: UnifiedContext, channel: Optional[discord.VoiceChannel]
    ) -> None:
        await uctx.defer(ephemeral=True)
        vc, err = self._resolve_caller_vc(uctx, channel)
        if err:
            await uctx.send_error("Error", err)
            return
        guild = uctx.guild
        try:
            await vc.set_permissions(guild.default_role, connect=False, reason="VC Lock")  # type: ignore
            embed = EmbedBuilder.base(
                title="🔒 Voice Channel Locked",
                description=f"**{vc.name}** is now locked — no one can join.",  # type: ignore
                color=BRAND_COLOR,
            )
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "I cannot modify that channel's permissions.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vclock", help="Lock a voice channel (deny @everyone connect).")
    async def vclock_prefix(self, ctx: commands.Context, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vclock(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="lock", description="Lock a voice channel (deny @everyone connect).")
    @app_commands.describe(channel="Voice channel to lock (defaults to yours)")
    async def vclock_slash(self, interaction: discord.Interaction, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vclock(UnifiedContext.from_interaction(interaction), channel)

    # ═══════════════════════════════════════════════════════════════════════════
    #  16. VCUNLOCK
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcunlock(
        self, uctx: UnifiedContext, channel: Optional[discord.VoiceChannel]
    ) -> None:
        await uctx.defer(ephemeral=True)
        vc, err = self._resolve_caller_vc(uctx, channel)
        if err:
            await uctx.send_error("Error", err)
            return
        guild = uctx.guild
        try:
            overwrite = vc.overwrites_for(guild.default_role)  # type: ignore
            overwrite.connect = None
            await vc.set_permissions(  # type: ignore
                guild.default_role,  # type: ignore
                overwrite=overwrite if not overwrite.is_empty() else None,
                reason="VC Unlock",
            )
            embed = EmbedBuilder.base(
                title="🔓 Voice Channel Unlocked",
                description=f"**{vc.name}** is now open for everyone to join.",  # type: ignore
                color=BRAND_COLOR,
            )
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "I cannot modify that channel's permissions.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vcunlock", help="Unlock a voice channel.")
    async def vcunlock_prefix(self, ctx: commands.Context, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcunlock(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="unlock", description="Unlock a voice channel.")
    @app_commands.describe(channel="Voice channel to unlock (defaults to yours)")
    async def vcunlock_slash(self, interaction: discord.Interaction, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcunlock(UnifiedContext.from_interaction(interaction), channel)

    # ═══════════════════════════════════════════════════════════════════════════
    #  17. VCHIDE
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vchide(
        self, uctx: UnifiedContext, channel: Optional[discord.VoiceChannel]
    ) -> None:
        await uctx.defer(ephemeral=True)
        vc, err = self._resolve_caller_vc(uctx, channel)
        if err:
            await uctx.send_error("Error", err)
            return
        guild = uctx.guild
        try:
            await vc.set_permissions(guild.default_role, view_channel=False, reason="VC Hide")  # type: ignore
            embed = EmbedBuilder.base(
                title="👁️ Voice Channel Hidden",
                description=f"**{vc.name}** is now invisible to @everyone.",  # type: ignore
                color=BRAND_COLOR,
            )
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "I cannot modify that channel's permissions.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vchide", help="Hide a voice channel from @everyone.")
    async def vchide_prefix(self, ctx: commands.Context, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vchide(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="hide", description="Hide a voice channel from @everyone.")
    @app_commands.describe(channel="Voice channel to hide (defaults to yours)")
    async def vchide_slash(self, interaction: discord.Interaction, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vchide(UnifiedContext.from_interaction(interaction), channel)

    # ═══════════════════════════════════════════════════════════════════════════
    #  18. VCSHOW
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcshow(
        self, uctx: UnifiedContext, channel: Optional[discord.VoiceChannel]
    ) -> None:
        await uctx.defer(ephemeral=True)
        vc, err = self._resolve_caller_vc(uctx, channel)
        if err:
            await uctx.send_error("Error", err)
            return
        guild = uctx.guild
        try:
            overwrite = vc.overwrites_for(guild.default_role)  # type: ignore
            overwrite.view_channel = None
            await vc.set_permissions(  # type: ignore
                guild.default_role,  # type: ignore
                overwrite=overwrite if not overwrite.is_empty() else None,
                reason="VC Show",
            )
            embed = EmbedBuilder.base(
                title="👁️ Voice Channel Visible",
                description=f"**{vc.name}** is now visible to @everyone.",  # type: ignore
                color=BRAND_COLOR,
            )
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "I cannot modify that channel's permissions.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vcshow", help="Make a hidden voice channel visible.")
    async def vcshow_prefix(self, ctx: commands.Context, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcshow(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="show", description="Make a hidden voice channel visible to @everyone.")
    @app_commands.describe(channel="Voice channel to show (defaults to yours)")
    async def vcshow_slash(self, interaction: discord.Interaction, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcshow(UnifiedContext.from_interaction(interaction), channel)

    # ═══════════════════════════════════════════════════════════════════════════
    #  19. VCLIMIT
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vclimit(
        self, uctx: UnifiedContext, limit: int, channel: Optional[discord.VoiceChannel]
    ) -> None:
        await uctx.defer(ephemeral=True)
        vc, err = self._resolve_caller_vc(uctx, channel)
        if err:
            await uctx.send_error("Error", err)
            return
        if limit < 0 or limit > 99:
            await uctx.send_error("Invalid Limit", "User limit must be between 0 (unlimited) and 99.")
            return
        try:
            await vc.edit(user_limit=limit, reason="VC Limit Change")  # type: ignore
            limit_str = "Unlimited" if limit == 0 else str(limit)
            embed = EmbedBuilder.base(
                title="👥 VC User Limit Updated",
                description=f"**{vc.name}** limit set to **{limit_str}**.",  # type: ignore
                color=BRAND_COLOR,
            )
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "I cannot edit that channel.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vclimit", help="Set the user limit for a voice channel (0 = unlimited).")
    async def vclimit_prefix(self, ctx: commands.Context, limit: int, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vclimit(UnifiedContext.from_prefix(ctx), limit, channel)

    @app_commands.command(name="limit", description="Set the user limit for a voice channel.")
    @app_commands.describe(limit="0 = unlimited, 1-99 for a cap", channel="Target VC (defaults to yours)")
    async def vclimit_slash(self, interaction: discord.Interaction, limit: int, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vclimit(UnifiedContext.from_interaction(interaction), limit, channel)

    # ═══════════════════════════════════════════════════════════════════════════
    #  20. VCBITRATE
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcbitrate(
        self, uctx: UnifiedContext, bitrate: int, channel: Optional[discord.VoiceChannel]
    ) -> None:
        await uctx.defer(ephemeral=True)
        vc, err = self._resolve_caller_vc(uctx, channel)
        if err:
            await uctx.send_error("Error", err)
            return
        if bitrate < 8 or bitrate > 384:
            await uctx.send_error("Invalid Bitrate", "Bitrate must be between **8** and **384** kbps.")
            return
        try:
            await vc.edit(bitrate=bitrate * 1000, reason="VC Bitrate Change")  # type: ignore
            embed = EmbedBuilder.base(
                title="🎵 VC Bitrate Updated",
                description=f"**{vc.name}** bitrate set to **{bitrate} kbps**.",  # type: ignore
                color=BRAND_COLOR,
            )
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "I cannot edit that channel.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", f"Bitrate may exceed your server's boost tier limit. ({e})")

    @commands.command(name="vcbitrate", help="Set voice channel bitrate in kbps (8-384).")
    async def vcbitrate_prefix(self, ctx: commands.Context, bitrate: int, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcbitrate(UnifiedContext.from_prefix(ctx), bitrate, channel)

    @app_commands.command(name="bitrate", description="Set voice channel bitrate in kbps.")
    @app_commands.describe(bitrate="Bitrate in kbps (8-384, server boost tier limits apply)", channel="Target VC (defaults to yours)")
    async def vcbitrate_slash(self, interaction: discord.Interaction, bitrate: int, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcbitrate(UnifiedContext.from_interaction(interaction), bitrate, channel)

    # ═══════════════════════════════════════════════════════════════════════════
    #  21. VCREGION
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcregion(
        self, uctx: UnifiedContext, region: Optional[str], channel: Optional[discord.VoiceChannel]
    ) -> None:
        await uctx.defer(ephemeral=True)
        vc, err = self._resolve_caller_vc(uctx, channel)
        if err:
            await uctx.send_error("Error", err)
            return

        if region is None:
            # Show current region
            current = vc.rtc_region or "Automatic"  # type: ignore
            embed = EmbedBuilder.base(
                title="🌍 Current VC Region",
                description=f"**{vc.name}** is set to region: **{current}**.",  # type: ignore
                color=BRAND_COLOR,
            )
            embed.add_field(
                name="Valid Regions",
                value=", ".join(VALID_REGIONS.keys()),
                inline=False,
            )
            await uctx.reply(embed=embed)
            return

        region_key = region.lower().replace(" ", "-")
        if region_key not in VALID_REGIONS:
            await uctx.send_error(
                "Invalid Region",
                f"`{region}` is not a valid region.\nValid: {', '.join(VALID_REGIONS.keys())}",
            )
            return

        rtc_value = VALID_REGIONS[region_key]
        try:
            await vc.edit(rtc_region=rtc_value, reason="VC Region Change")  # type: ignore
            region_display = rtc_value or "Automatic"
            embed = EmbedBuilder.base(
                title="🌍 VC Region Updated",
                description=f"**{vc.name}** region set to **{region_display}**.",  # type: ignore
                color=BRAND_COLOR,
            )
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "I cannot edit that channel.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vcregion", help="Set or view the RTC region for a voice channel.")
    async def vcregion_prefix(self, ctx: commands.Context, region: Optional[str] = None, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcregion(UnifiedContext.from_prefix(ctx), region, channel)

    @app_commands.command(name="region", description="Set or view the RTC region for a voice channel.")
    @app_commands.describe(region="Region name (or 'automatic'), omit to view current", channel="Target VC (defaults to yours)")
    async def vcregion_slash(self, interaction: discord.Interaction, region: Optional[str] = None, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcregion(UnifiedContext.from_interaction(interaction), region, channel)

    # ═══════════════════════════════════════════════════════════════════════════
    #  22. VCDRAG
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcdrag(
        self,
        uctx: UnifiedContext,
        member: discord.Member,
        channel: Optional[discord.VoiceChannel],
    ) -> None:
        await uctx.defer(ephemeral=True)
        author = uctx.author
        if not isinstance(author, discord.Member):
            await uctx.send_error("Error", "Must be used in a server.")
            return
        if not author.guild_permissions.move_members:
            await uctx.send_error("Permission Error", "You need **Move Members** permission.")
            return

        target_vc, err = self._resolve_caller_vc(uctx, channel)
        if err:
            await uctx.send_error("Error", err)
            return

        try:
            await member.move_to(target_vc, reason=f"VC Drag by {author}")
            embed = EmbedBuilder.base(
                title="🎯 Member Dragged",
                description=f"{member.mention} has been moved to **{target_vc.name}**.",  # type: ignore
                color=BRAND_COLOR,
            )
            await uctx.reply(embed=embed)
        except discord.Forbidden:
            await uctx.send_error("Forbidden", "I cannot move that member.")
        except discord.HTTPException as e:
            await uctx.send_error("API Error", str(e))

    @commands.command(name="vcdrag", help="Move a member into your voice channel.")
    async def vcdrag_prefix(self, ctx: commands.Context, member: discord.Member, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcdrag(UnifiedContext.from_prefix(ctx), member, channel)

    @app_commands.command(name="drag", description="Move a member into your voice channel (or a specified one).")
    @app_commands.describe(member="Member to drag", channel="Destination VC (defaults to yours)")
    async def vcdrag_slash(self, interaction: discord.Interaction, member: discord.Member, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcdrag(UnifiedContext.from_interaction(interaction), member, channel)

    # ═══════════════════════════════════════════════════════════════════════════
    #  23. VCMOVEALL
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcmoveall(
        self, uctx: UnifiedContext, destination: discord.VoiceChannel
    ) -> None:
        await uctx.defer(ephemeral=True)
        author = uctx.author
        if not isinstance(author, discord.Member) or not author.guild_permissions.move_members:
            await uctx.send_error("Permission Error", "You need **Move Members** permission.")
            return
        source_vc, err = self._resolve_caller_vc(uctx)
        if err:
            await uctx.send_error("Error", err)
            return
        moved = 0
        for m in list(source_vc.members):  # type: ignore
            if m.voice and m.voice.channel:
                try:
                    await m.move_to(destination, reason="Mass VC Move")
                    moved += 1
                except Exception:
                    pass
        embed = EmbedBuilder.base(
            title="🔀 Mass VC Move Complete",
            description=f"Moved **{moved}** member(s) from **{source_vc.name}** → **{destination.name}**.",  # type: ignore
            color=BRAND_COLOR,
        )
        await uctx.reply(embed=embed)

    @commands.command(name="vcmoveall", help="Move all members from your VC to a destination channel.")
    async def vcmoveall_prefix(self, ctx: commands.Context, destination: discord.VoiceChannel) -> None:
        await self._execute_vcmoveall(UnifiedContext.from_prefix(ctx), destination)

    @app_commands.command(name="moveall", description="Move all members from your VC to a destination channel.")
    @app_commands.describe(destination="Destination voice channel")
    async def vcmoveall_slash(self, interaction: discord.Interaction, destination: discord.VoiceChannel) -> None:
        await self._execute_vcmoveall(UnifiedContext.from_interaction(interaction), destination)

    # ═══════════════════════════════════════════════════════════════════════════
    #  24. VCINFO
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcinfo(
        self, uctx: UnifiedContext, channel: Optional[discord.VoiceChannel]
    ) -> None:
        await uctx.defer()
        vc, err = self._resolve_caller_vc(uctx, channel)
        if err:
            await uctx.send_error("Error", err)
            return

        guild = uctx.guild
        bans = await self._get_vc_bans(guild.id, vc.id)  # type: ignore

        # Determine lock / hidden status from @everyone overwrite
        everyone_ow = vc.overwrites_for(guild.default_role)  # type: ignore
        is_locked = everyone_ow.connect is False
        is_hidden = everyone_ow.view_channel is False

        # Bitrate in kbps
        bitrate_kbps = vc.bitrate // 1000  # type: ignore
        region_str = vc.rtc_region or "Automatic"  # type: ignore
        limit_str = str(vc.user_limit) if vc.user_limit else "Unlimited"  # type: ignore
        category_str = vc.category.name if vc.category else "None"  # type: ignore
        member_count = len(vc.members)  # type: ignore

        # Build member list (up to 15)
        member_lines = []
        for m in vc.members[:15]:  # type: ignore
            icons = ""
            if m.voice:
                if m.voice.mute or m.voice.self_mute:
                    icons += "🔇"
                if m.voice.deaf or m.voice.self_deaf:
                    icons += "🔕"
            member_lines.append(f"• {m.mention} {icons}")
        member_list = "\n".join(member_lines) or "*No members*"
        if len(vc.members) > 15:  # type: ignore
            member_list += f"\n*...and {len(vc.members) - 15} more*"  # type: ignore

        embed = EmbedBuilder.base(
            title=f"🎙️ Voice Channel Info — {vc.name}",  # type: ignore
            color=BRAND_COLOR,
        )
        embed.add_field(name="📁 Category", value=category_str, inline=True)
        embed.add_field(name="👥 Members", value=f"{member_count}/{limit_str}", inline=True)
        embed.add_field(name="🎵 Bitrate", value=f"{bitrate_kbps} kbps", inline=True)
        embed.add_field(name="🌍 Region", value=region_str, inline=True)
        embed.add_field(name="🔒 Locked", value="Yes" if is_locked else "No", inline=True)
        embed.add_field(name="👁️ Hidden", value="Yes" if is_hidden else "No", inline=True)
        embed.add_field(name="🚫 VC Bans", value=str(len(bans)), inline=True)
        embed.add_field(name="🆔 Channel ID", value=str(vc.id), inline=True)  # type: ignore
        embed.add_field(name="🎙️ Current Members", value=member_list, inline=False)
        await uctx.reply(embed=embed)

    @commands.command(name="vcinfo", help="Show detailed info about a voice channel.")
    async def vcinfo_prefix(self, ctx: commands.Context, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcinfo(UnifiedContext.from_prefix(ctx), channel)

    @app_commands.command(name="info", description="Show detailed info about a voice channel.")
    @app_commands.describe(channel="Voice channel to inspect (defaults to yours)")
    async def vcinfo_slash(self, interaction: discord.Interaction, channel: Optional[discord.VoiceChannel] = None) -> None:
        await self._execute_vcinfo(UnifiedContext.from_interaction(interaction), channel)

    # ═══════════════════════════════════════════════════════════════════════════
    #  25. VCSTATS
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_vcstats(
        self, uctx: UnifiedContext, member: Optional[discord.Member]
    ) -> None:
        await uctx.defer()
        guild = uctx.guild
        if guild is None:
            await uctx.send_error("Error", "Must be used in a server.")
            return

        author = uctx.author
        target = member or (author if isinstance(author, discord.Member) else None)
        if target is None:
            await uctx.send_error("Error", "Could not resolve target member.")
            return

        # Query DB for today's voice session total
        total_seconds: int = 0
        try:
            row = await self.bot.db.fetchone(
                "SELECT SUM(duration_seconds) FROM voice_sessions "
                "WHERE guild_id=? AND user_id=? AND joined_at > datetime('now', '-1 day')",
                (guild.id, target.id),
            )
            if row and row[0]:
                total_seconds = int(row[0])
        except Exception:
            total_seconds = 0

        # Current voice state
        current_channel_str = "Not in a voice channel"
        current_session_str = "N/A"
        if target.voice and target.voice.channel:
            current_channel_str = target.voice.channel.mention

        # Format durations
        def _fmt_duration(seconds: int) -> str:
            if seconds <= 0:
                return "0s"
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            parts = []
            if h:
                parts.append(f"{h}h")
            if m:
                parts.append(f"{m}m")
            if s:
                parts.append(f"{s}s")
            return " ".join(parts)

        embed = EmbedBuilder.base(
            title=f"📊 Voice Stats — {target.display_name}",
            color=BRAND_COLOR,
            thumbnail=target.display_avatar.url,
        )
        embed.add_field(name="🕒 Total VC Time (24h)", value=_fmt_duration(total_seconds), inline=True)
        embed.add_field(name="🎙️ Current Channel", value=current_channel_str, inline=True)
        await uctx.reply(embed=embed)

    @commands.command(name="vcstats", help="View voice channel stats for a member (or yourself).")
    async def vcstats_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await self._execute_vcstats(UnifiedContext.from_prefix(ctx), member)

    @app_commands.command(name="stats", description="View voice channel stats for a member (or yourself).")
    @app_commands.describe(member="Member to check (defaults to yourself)")
    async def vcstats_slash(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        await self._execute_vcstats(UnifiedContext.from_interaction(interaction), member)

    # ── VC Loop Listener & Enforcement ────────────────────────────
    _loop_cooldowns: dict[tuple[int, int], list[float]] = {}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.bot or not member.guild:
            return
        if not getattr(self.bot.config, "ownervc_loop_enabled", True):
            return
        if after.channel is None or before.channel == after.channel:
            return

        if not self.bot.vc_repo:
            return

        try:
            loop_cfg = await self.bot.vc_repo.get_vc_loop(member.guild.id, member.id)
            if not loop_cfg:
                return

            dest_id = loop_cfg.get("channel_id")
            if not dest_id or after.channel.id == dest_id:
                return

            # Check if user opted out
            if await self.bot.vc_repo.is_vc_loop_opted_out(member.guild.id, member.id):
                return

            # Check bounded retry & rate limits governed by OWNERVC_LOOP_COOLDOWN from .env
            import time
            now = time.time()
            key = (member.guild.id, member.id)
            cooldown_window = float(getattr(self.bot.config, "ownervc_loop_cooldown", 30))
            history = [t for t in self._loop_cooldowns.get(key, []) if now - t < cooldown_window]
            if len(history) >= 3:
                return
            if history and (now - history[-1]) < 3.0:
                return

            dest_channel = member.guild.get_channel(dest_id)
            if not isinstance(dest_channel, discord.VoiceChannel):
                return

            if not member.guild.me.guild_permissions.move_members:
                return

            history.append(now)
            self._loop_cooldowns[key] = history

            await member.move_to(dest_channel, reason="KROVEX OwnerVC Loop Automated Return")
        except Exception:
            pass

    @commands.group(name="vcloop", invoke_without_command=True, help="Manage or inspect your VC Loop opt-out status.")
    async def vcloop_group(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        is_opted = await self.bot.vc_repo.is_vc_loop_opted_out(ctx.guild.id, ctx.author.id) if self.bot.vc_repo else False
        msg = (
            "🛡️ **VC Loop Protection:** You are currently **OPTED OUT** from automated VC Loop movement.\n"
            "Use `.vcloop optin` if you want to allow automated room returns."
            if is_opted else
            "ℹ️ **VC Loop Status:** You are currently eligible for OwnerVC room loops.\n"
            "Use `.vcloop optout` at any time to block automated voice movement."
        )
        await ctx.reply(msg)

    @vcloop_group.command(name="optout", help="Opt out of automated VC Loop movements.")
    async def vcloop_optout(self, ctx: commands.Context) -> None:
        if not ctx.guild or not self.bot.vc_repo:
            return
        await self.bot.vc_repo.set_vc_loop_optout(ctx.guild.id, ctx.author.id)
        await ctx.reply("✅ **Opted Out:** You have successfully opted out from all VC Loop automated movements.")

    @vcloop_group.command(name="optin", help="Opt back into automated VC Loop movements.")
    async def vcloop_optin(self, ctx: commands.Context) -> None:
        if not ctx.guild or not self.bot.vc_repo:
            return
        await self.bot.vc_repo.remove_vc_loop_optout(ctx.guild.id, ctx.author.id)
        await ctx.reply("✅ **Opted In:** You are now eligible for OwnerVC room loop automation.")

    @vcloop_group.command(name="stop", help="Stop an active VC Loop for a member (Server Owner / Bot Owner).")
    async def vcloop_stop(self, ctx: commands.Context, member: discord.Member) -> None:
        if not ctx.guild:
            return
        is_owner = (
            ctx.author.id == ctx.guild.owner_id
            or ctx.author.id in self.bot.config.owner_ids
            or str(ctx.author.id) in [str(x) for x in self.bot.config.owner_ids]
        )
        if not is_owner and hasattr(self.bot, "is_bot_owner") and callable(self.bot.is_bot_owner):
            try:
                res = self.bot.is_bot_owner(ctx.author)
                if asyncio.iscoroutine(res):
                    is_owner = await res
                elif isinstance(res, bool):
                    is_owner = res
            except Exception:
                pass
        if not is_owner:
            await ctx.reply("❌ Only the Server Owner or Bot Owner can stop member VC loops.")
            return
        if self.bot.vc_repo:
            removed = await self.bot.vc_repo.remove_vc_loop(ctx.guild.id, member.id)
            if removed:
                await ctx.reply(f"⏹️ **Stopped:** Active VC Loop for {member.mention} has been deactivated.")
            else:
                await ctx.reply(f"ℹ️ No active VC Loop was found for {member.mention}.")


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(OwnerVC(bot))
