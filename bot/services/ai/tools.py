"""KROVEX SOUL Action & Tool Registry.

Provides a controlled, permission-enforced tool execution engine allowing SOUL
to invoke existing KROVEX business logic across Music, Voice, Moderation, Utility,
and Community modules without code duplication.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Dict, List, Optional, Tuple, Union

import discord

from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot
    from bot.core.context import UnifiedContext

logger = get_logger("death_bot.ai.tools")


@dataclass
class ToolResult:
    """Standardized result payload from a SOUL tool execution."""
    success: bool
    message: str
    action_type: str = "general"
    data: Optional[Dict[str, Any]] = None
    requires_confirmation: bool = False
    confirmation_payload: Optional[Dict[str, Any]] = None


@dataclass
class ToolDefinition:
    """Metadata and execution specification for an approved SOUL tool."""
    name: str
    description: str
    category: str  # "music", "voice", "moderation", "server", "utility", "economy"
    required_permissions: List[str] = field(default_factory=list)
    requires_owner: bool = False
    requires_bot_owner: bool = False
    requires_voice: bool = False
    requires_confirmation: bool = False
    confirmation_prompt: str = ""
    executor: Optional[Callable[..., Coroutine[Any, Any, ToolResult]]] = None


class ToolRegistry:
    """Central registry and permission guard for all SOUL executable actions."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot
        self._tools: Dict[str, ToolDefinition] = {}
        self._register_all_tools()

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Lookup a registered tool by its canonical name."""
        return self._tools.get(name.lower())

    def list_tools(self, category: Optional[str] = None) -> List[ToolDefinition]:
        """List registered tools, optionally filtered by category."""
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())

    def register(self, tool: ToolDefinition) -> None:
        """Register a new approved tool."""
        self._tools[tool.name.lower()] = tool

    # ── Permission & Safety Verification ──────────────────────────────────────

    def check_permissions(
        self,
        tool: ToolDefinition,
        member: discord.Member,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        target_member: Optional[discord.Member] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Verify requesting user permissions, bot permissions, and role hierarchy."""
        guild = member.guild
        me = guild.me
        if not me:
            return False, "Bot is not available in this guild."

        # 1. Sovereign Owner Restrictions
        if tool.requires_owner:
            is_server_owner = member.id == guild.owner_id
            is_bot_owner = member.id in self.bot.config.owner_ids
            if not (is_server_owner or is_bot_owner):
                return False, "Only the Server Owner or configured Bot Owner can perform this action."

        # 2. Bot Owner Restrictions
        if tool.requires_bot_owner:
            if member.id not in self.bot.config.owner_ids:
                return False, "This action is restricted to KROVEX Bot Owners."

        # 3. User Voice Channel Requirements
        if tool.requires_voice:
            if not member.voice or not member.voice.channel:
                return False, "You need to be in a voice channel to use this voice or music action."

        # 4. Discord User Permissions
        is_user_admin = getattr(member.guild_permissions, "administrator", False) or (member.id == guild.owner_id)
        if not is_user_admin:
            for perm in tool.required_permissions:
                user_has = getattr(member.guild_permissions, perm, False)
                channel_perms = channel.permissions_for(member)
                channel_has = getattr(channel_perms, perm, False)
                if not (user_has or channel_has):
                    perm_title = perm.replace("_", " ").title()
                    return False, f"You don't have permission to perform that action. (Requires: `{perm_title}`)"

        # 5. Discord Bot Permissions
        is_bot_admin = getattr(me.guild_permissions, "administrator", False)
        if not is_bot_admin:
            for perm in tool.required_permissions:
                bot_has = getattr(me.guild_permissions, perm, False)
                channel_bot_perms = channel.permissions_for(me)
                channel_bot_has = getattr(channel_bot_perms, perm, False)
                if not (bot_has or channel_bot_has):
                    perm_title = perm.replace("_", " ").title()
                    return False, f"I don't have sufficient permissions to perform that action. (Missing: `{perm_title}`)"

        # 6. Role Hierarchy Protection (for Moderation on a target member)
        if target_member:
            if target_member.id == guild.owner_id:
                return False, "The Server Owner cannot be moderated."
            if target_member.id == me.id:
                return False, "I cannot perform moderation actions on myself."
            target_pos = getattr(target_member.top_role, "position", 0)
            member_pos = getattr(member.top_role, "position", 0)
            me_pos = getattr(me.top_role, "position", 0)
            if member.id != guild.owner_id and target_pos >= member_pos:
                return False, f"You cannot moderate {target_member.display_name} due to role hierarchy."
            if target_pos >= me_pos:
                return False, f"I cannot moderate {target_member.display_name} because their role is higher than or equal to mine."

        return True, None

    # ── Tool Registrations ───────────────────────────────────────────────────

    def _register_all_tools(self) -> None:
        """Register the built-in approved tools across all KROVEX subsystems."""

        # ── MUSIC TOOLS ──
        self.register(ToolDefinition(
            name="music_play",
            description="Search for and play a song in the user's voice channel.",
            category="music",
            requires_voice=True,
            executor=self._exec_music_play,
        ))
        self.register(ToolDefinition(
            name="music_pause",
            description="Pause the currently playing track.",
            category="music",
            requires_voice=True,
            executor=self._exec_music_pause,
        ))
        self.register(ToolDefinition(
            name="music_resume",
            description="Resume music playback.",
            category="music",
            requires_voice=True,
            executor=self._exec_music_resume,
        ))
        self.register(ToolDefinition(
            name="music_skip",
            description="Skip the current playing track.",
            category="music",
            requires_voice=True,
            executor=self._exec_music_skip,
        ))
        self.register(ToolDefinition(
            name="music_stop",
            description="Stop music playback and clear queue.",
            category="music",
            requires_voice=True,
            executor=self._exec_music_stop,
        ))
        self.register(ToolDefinition(
            name="music_volume",
            description="Adjust music playback volume (0 to 100).",
            category="music",
            requires_voice=True,
            executor=self._exec_music_volume,
        ))
        self.register(ToolDefinition(
            name="music_nowplaying",
            description="Show information about the currently playing song.",
            category="music",
            executor=self._exec_music_nowplaying,
        ))
        self.register(ToolDefinition(
            name="music_queue",
            description="View the current music queue.",
            category="music",
            executor=self._exec_music_queue,
        ))

        # ── VOICE / OWNERVC TOOLS ──
        self.register(ToolDefinition(
            name="voice_lock",
            description="Lock the user's active voice channel.",
            category="voice",
            requires_voice=True,
            executor=self._exec_voice_lock,
        ))
        self.register(ToolDefinition(
            name="voice_unlock",
            description="Unlock the user's active voice channel.",
            category="voice",
            requires_voice=True,
            executor=self._exec_voice_unlock,
        ))
        self.register(ToolDefinition(
            name="voice_hide",
            description="Hide the user's active voice channel.",
            category="voice",
            requires_voice=True,
            executor=self._exec_voice_hide,
        ))
        self.register(ToolDefinition(
            name="voice_show",
            description="Make the user's active voice channel visible.",
            category="voice",
            requires_voice=True,
            executor=self._exec_voice_show,
        ))
        self.register(ToolDefinition(
            name="voice_limit",
            description="Set member capacity limit for active voice channel.",
            category="voice",
            requires_voice=True,
            executor=self._exec_voice_limit,
        ))
        self.register(ToolDefinition(
            name="voice_mute",
            description="Server mute a member in the voice channel.",
            category="voice",
            required_permissions=["mute_members"],
            executor=self._exec_voice_mute,
        ))
        self.register(ToolDefinition(
            name="voice_unmute",
            description="Server unmute a member in the voice channel.",
            category="voice",
            required_permissions=["mute_members"],
            executor=self._exec_voice_unmute,
        ))
        self.register(ToolDefinition(
            name="voice_deafen",
            description="Server deafen a member in the voice channel.",
            category="voice",
            required_permissions=["deafen_members"],
            executor=self._exec_voice_deafen,
        ))
        self.register(ToolDefinition(
            name="voice_undeafen",
            description="Server undeafen a member in the voice channel.",
            category="voice",
            required_permissions=["deafen_members"],
            executor=self._exec_voice_undeafen,
        ))
        self.register(ToolDefinition(
            name="voice_kick",
            description="Disconnect/kick a member from the voice channel.",
            category="voice",
            required_permissions=["move_members"],
            executor=self._exec_voice_kick,
        ))
        self.register(ToolDefinition(
            name="voice_claim",
            description="Claim ownership of an orphaned voice channel.",
            category="voice",
            requires_voice=True,
            executor=self._exec_voice_claim,
        ))

        # ── MODERATION TOOLS ──
        self.register(ToolDefinition(
            name="mod_kick",
            description="Kick a member from the server.",
            category="moderation",
            required_permissions=["kick_members"],
            requires_confirmation=True,
            confirmation_prompt="Are you sure you want to kick **{target}** from the server?",
            executor=self._exec_mod_kick,
        ))
        self.register(ToolDefinition(
            name="mod_ban",
            description="Ban a member from the server.",
            category="moderation",
            required_permissions=["ban_members"],
            requires_confirmation=True,
            confirmation_prompt="Are you sure you want to ban **{target}** from the server?",
            executor=self._exec_mod_ban,
        ))
        self.register(ToolDefinition(
            name="mod_unban",
            description="Unban a user by ID or tag.",
            category="moderation",
            required_permissions=["ban_members"],
            executor=self._exec_mod_unban,
        ))
        self.register(ToolDefinition(
            name="mod_timeout",
            description="Timeout a member for a duration (e.g. 10m, 1h, 1d).",
            category="moderation",
            required_permissions=["moderate_members"],
            executor=self._exec_mod_timeout,
        ))
        self.register(ToolDefinition(
            name="mod_untimeout",
            description="Remove timeout from a member.",
            category="moderation",
            required_permissions=["moderate_members"],
            executor=self._exec_mod_untimeout,
        ))
        self.register(ToolDefinition(
            name="mod_warn",
            description="Issue a formal warning to a member.",
            category="moderation",
            required_permissions=["manage_messages"],
            executor=self._exec_mod_warn,
        ))
        self.register(ToolDefinition(
            name="mod_warnings",
            description="List warnings for a member.",
            category="moderation",
            required_permissions=["manage_messages"],
            executor=self._exec_mod_warnings,
        ))
        self.register(ToolDefinition(
            name="mod_clearwarns",
            description="Clear all warnings for a member.",
            category="moderation",
            required_permissions=["administrator"],
            requires_confirmation=True,
            confirmation_prompt="Are you sure you want to clear all warnings for **{target}**?",
            executor=self._exec_mod_clearwarns,
        ))
        self.register(ToolDefinition(
            name="mod_purge",
            description="Purge a specified number of recent messages.",
            category="moderation",
            required_permissions=["manage_messages"],
            requires_confirmation=True,
            confirmation_prompt="Are you sure you want to purge **{count}** messages in this channel?",
            executor=self._exec_mod_purge,
        ))
        self.register(ToolDefinition(
            name="mod_lock",
            description="Lock down the current text channel.",
            category="moderation",
            required_permissions=["manage_channels"],
            executor=self._exec_mod_lock,
        ))
        self.register(ToolDefinition(
            name="mod_unlock",
            description="Unlock the current text channel.",
            category="moderation",
            required_permissions=["manage_channels"],
            executor=self._exec_mod_unlock,
        ))
        self.register(ToolDefinition(
            name="mod_slowmode",
            description="Set channel slowmode in seconds.",
            category="moderation",
            required_permissions=["manage_channels"],
            executor=self._exec_mod_slowmode,
        ))

        # ── SERVER & UTILITY TOOLS ──
        self.register(ToolDefinition(
            name="util_serverinfo",
            description="Show server statistics and metadata.",
            category="utility",
            executor=self._exec_util_serverinfo,
        ))
        self.register(ToolDefinition(
            name="util_membercount",
            description="Show server member count breakdown.",
            category="utility",
            executor=self._exec_util_membercount,
        ))
        self.register(ToolDefinition(
            name="util_userinfo",
            description="Show detailed user profile and permissions.",
            category="utility",
            executor=self._exec_util_userinfo,
        ))
        self.register(ToolDefinition(
            name="util_avatar",
            description="Display a user's avatar image.",
            category="utility",
            executor=self._exec_util_avatar,
        ))
        self.register(ToolDefinition(
            name="util_ping",
            description="Check bot latency and gateway connection.",
            category="utility",
            executor=self._exec_util_ping,
        ))
        self.register(ToolDefinition(
            name="util_uptime",
            description="Show KROVEX uptime and runtime health.",
            category="utility",
            executor=self._exec_util_uptime,
        ))

        # ── ECONOMY & LEVELING TOOLS ──
        self.register(ToolDefinition(
            name="eco_balance",
            description="Check a user's wallet and bank balance.",
            category="economy",
            executor=self._exec_eco_balance,
        ))
        self.register(ToolDefinition(
            name="eco_daily",
            description="Claim daily economy coin bonus.",
            category="economy",
            executor=self._exec_eco_daily,
        ))
        self.register(ToolDefinition(
            name="level_rank",
            description="Check a user's server XP level and rank.",
            category="leveling",
            executor=self._exec_level_rank,
        ))
        self.register(ToolDefinition(
            name="level_leaderboard",
            description="Show the top server XP leaderboard.",
            category="leveling",
            executor=self._exec_level_leaderboard,
        ))

    # ── Executor Implementations Calling Existing Cog Business Logic ─────────

    async def _exec_music_play(self, ctx: UnifiedContext, query: str = "") -> ToolResult:
        music_cog = self.bot.get_cog("Music")
        if not music_cog:
            return ToolResult(False, "Music subsystem is currently unavailable.")
        if not query:
            return ToolResult(False, "Which song would you like to play?")
        try:
            await music_cog._execute_play(ctx, query=query)
            return ToolResult(True, f"Done! 🎵 Now searching and playing **{query}**.", action_type="music_play")
        except Exception as e:
            logger.error("SOUL music_play error: %s", e)
            return ToolResult(False, f"I couldn't start playback: {e}")

    async def _exec_music_pause(self, ctx: UnifiedContext) -> ToolResult:
        music_cog = self.bot.get_cog("Music")
        if not music_cog:
            return ToolResult(False, "Music subsystem is currently unavailable.")
        try:
            await music_cog._execute_pause(ctx)
            return ToolResult(True, "Done! ⏸️ Music playback paused.", action_type="music_pause")
        except Exception as e:
            return ToolResult(False, f"Could not pause playback: {e}")

    async def _exec_music_resume(self, ctx: UnifiedContext) -> ToolResult:
        music_cog = self.bot.get_cog("Music")
        if not music_cog:
            return ToolResult(False, "Music subsystem is currently unavailable.")
        try:
            await music_cog._execute_resume(ctx)
            return ToolResult(True, "Done! ▶️ Music playback resumed.", action_type="music_resume")
        except Exception as e:
            return ToolResult(False, f"Could not resume playback: {e}")

    async def _exec_music_skip(self, ctx: UnifiedContext) -> ToolResult:
        music_cog = self.bot.get_cog("Music")
        if not music_cog:
            return ToolResult(False, "Music subsystem is currently unavailable.")
        try:
            await music_cog._execute_skip(ctx)
            return ToolResult(True, "Done! ⏭️ Skipped current track.", action_type="music_skip")
        except Exception as e:
            return ToolResult(False, f"Could not skip track: {e}")

    async def _exec_music_stop(self, ctx: UnifiedContext) -> ToolResult:
        music_cog = self.bot.get_cog("Music")
        if not music_cog:
            return ToolResult(False, "Music subsystem is currently unavailable.")
        try:
            await music_cog._execute_stop(ctx)
            return ToolResult(True, "Done! ⏹️ Stopped music playback and cleared the queue.", action_type="music_stop")
        except Exception as e:
            return ToolResult(False, f"Could not stop playback: {e}")

    async def _exec_music_volume(self, ctx: UnifiedContext, level: int = 100) -> ToolResult:
        music_cog = self.bot.get_cog("Music")
        if not music_cog:
            return ToolResult(False, "Music subsystem is currently unavailable.")
        level = max(0, min(100, level))
        try:
            await music_cog._execute_volume(ctx, volume=level)
            return ToolResult(True, f"Done! 🔊 Volume set to **{level}%**.", action_type="music_volume")
        except Exception as e:
            return ToolResult(False, f"Could not change volume: {e}")

    async def _exec_music_nowplaying(self, ctx: UnifiedContext) -> ToolResult:
        music_cog = self.bot.get_cog("Music")
        if not music_cog:
            return ToolResult(False, "Music subsystem is currently unavailable.")
        try:
            await music_cog._execute_nowplaying(ctx)
            return ToolResult(True, "Here is the currently playing song information.", action_type="music_nowplaying")
        except Exception as e:
            return ToolResult(False, f"Could not get now playing info: {e}")

    async def _exec_music_queue(self, ctx: UnifiedContext) -> ToolResult:
        music_cog = self.bot.get_cog("Music")
        if not music_cog:
            return ToolResult(False, "Music subsystem is currently unavailable.")
        try:
            await music_cog._execute_queue(ctx, page=1)
            return ToolResult(True, "Here is the current music queue.", action_type="music_queue")
        except Exception as e:
            return ToolResult(False, f"Could not retrieve queue: {e}")

    # ── Voice / OwnerVC Executors ──

    async def _exec_voice_lock(self, ctx: UnifiedContext) -> ToolResult:
        ownervc_cog = self.bot.get_cog("OwnerVC")
        if not ownervc_cog or not ctx.author.voice or not ctx.author.voice.channel:
            return ToolResult(False, "You must be in a voice channel to lock it.")
        try:
            channel = ctx.author.voice.channel
            await ownervc_cog._execute_vclock(ctx, channel=channel)
            return ToolResult(True, f"Done! 🔒 **{channel.name}** is now locked.", action_type="voice_lock")
        except Exception as e:
            return ToolResult(False, f"Could not lock voice channel: {e}")

    async def _exec_voice_unlock(self, ctx: UnifiedContext) -> ToolResult:
        ownervc_cog = self.bot.get_cog("OwnerVC")
        if not ownervc_cog or not ctx.author.voice or not ctx.author.voice.channel:
            return ToolResult(False, "You must be in a voice channel to unlock it.")
        try:
            channel = ctx.author.voice.channel
            await ownervc_cog._execute_vcunlock(ctx, channel=channel)
            return ToolResult(True, f"Done! 🔓 **{channel.name}** is now open.", action_type="voice_unlock")
        except Exception as e:
            return ToolResult(False, f"Could not unlock voice channel: {e}")

    async def _exec_voice_hide(self, ctx: UnifiedContext) -> ToolResult:
        ownervc_cog = self.bot.get_cog("OwnerVC")
        if not ownervc_cog or not ctx.author.voice or not ctx.author.voice.channel:
            return ToolResult(False, "You must be in a voice channel to hide it.")
        try:
            channel = ctx.author.voice.channel
            await ownervc_cog._execute_vchide(ctx, channel=channel)
            return ToolResult(True, f"Done! 👻 **{channel.name}** is now hidden.", action_type="voice_hide")
        except Exception as e:
            return ToolResult(False, f"Could not hide voice channel: {e}")

    async def _exec_voice_show(self, ctx: UnifiedContext) -> ToolResult:
        ownervc_cog = self.bot.get_cog("OwnerVC")
        if not ownervc_cog or not ctx.author.voice or not ctx.author.voice.channel:
            return ToolResult(False, "You must be in a voice channel to make it visible.")
        try:
            channel = ctx.author.voice.channel
            await ownervc_cog._execute_vcshow(ctx, channel=channel)
            return ToolResult(True, f"Done! ✨ **{channel.name}** is now visible.", action_type="voice_show")
        except Exception as e:
            return ToolResult(False, f"Could not show voice channel: {e}")

    async def _exec_voice_limit(self, ctx: UnifiedContext, limit: int = 0) -> ToolResult:
        ownervc_cog = self.bot.get_cog("OwnerVC")
        if not ownervc_cog or not ctx.author.voice or not ctx.author.voice.channel:
            return ToolResult(False, "You must be in a voice channel to set capacity.")
        try:
            channel = ctx.author.voice.channel
            await ownervc_cog._execute_vclimit(ctx, limit=limit, channel=channel)
            limit_str = f"limit of {limit}" if limit > 0 else "unlimited capacity"
            return ToolResult(True, f"Done! 👥 **{channel.name}** capacity set to {limit_str}.", action_type="voice_limit")
        except Exception as e:
            return ToolResult(False, f"Could not set channel limit: {e}")

    async def _exec_voice_mute(self, ctx: UnifiedContext, target: discord.Member = None) -> ToolResult:
        ownervc_cog = self.bot.get_cog("OwnerVC")
        if not ownervc_cog or not target:
            return ToolResult(False, "Please specify which member to voice mute.")
        try:
            await ownervc_cog._execute_vcmute(ctx, member=target)
            return ToolResult(True, f"Done! 🔇 Muted **{target.display_name}** in voice.", action_type="voice_mute")
        except Exception as e:
            return ToolResult(False, f"Could not voice mute member: {e}")

    async def _exec_voice_unmute(self, ctx: UnifiedContext, target: discord.Member = None) -> ToolResult:
        ownervc_cog = self.bot.get_cog("OwnerVC")
        if not ownervc_cog or not target:
            return ToolResult(False, "Please specify which member to voice unmute.")
        try:
            await ownervc_cog._execute_vcunmute(ctx, member=target)
            return ToolResult(True, f"Done! 🔊 Unmuted **{target.display_name}** in voice.", action_type="voice_unmute")
        except Exception as e:
            return ToolResult(False, f"Could not voice unmute member: {e}")

    async def _exec_voice_deafen(self, ctx: UnifiedContext, target: discord.Member = None) -> ToolResult:
        ownervc_cog = self.bot.get_cog("OwnerVC")
        if not ownervc_cog or not target:
            return ToolResult(False, "Please specify which member to voice deafen.")
        try:
            await ownervc_cog._execute_vcdeafen(ctx, member=target)
            return ToolResult(True, f"Done! 🔕 Deafened **{target.display_name}** in voice.", action_type="voice_deafen")
        except Exception as e:
            return ToolResult(False, f"Could not voice deafen member: {e}")

    async def _exec_voice_undeafen(self, ctx: UnifiedContext, target: discord.Member = None) -> ToolResult:
        ownervc_cog = self.bot.get_cog("OwnerVC")
        if not ownervc_cog or not target:
            return ToolResult(False, "Please specify which member to voice undeafen.")
        try:
            await ownervc_cog._execute_vcundeafen(ctx, member=target)
            return ToolResult(True, f"Done! 🔔 Undeafened **{target.display_name}** in voice.", action_type="voice_undeafen")
        except Exception as e:
            return ToolResult(False, f"Could not voice undeafen member: {e}")

    async def _exec_voice_kick(self, ctx: UnifiedContext, target: discord.Member = None) -> ToolResult:
        ownervc_cog = self.bot.get_cog("OwnerVC")
        if not ownervc_cog or not target:
            return ToolResult(False, "Please specify which member to disconnect from voice.")
        try:
            await ownervc_cog._execute_vckick(ctx, member=target, reason="Disconnected via SOUL Assistant")
            return ToolResult(True, f"Done! 👢 Disconnected **{target.display_name}** from voice.", action_type="voice_kick")
        except Exception as e:
            return ToolResult(False, f"Could not disconnect member: {e}")

    async def _exec_voice_claim(self, ctx: UnifiedContext) -> ToolResult:
        voice_cog = self.bot.get_cog("Voice")
        if not voice_cog or not ctx.author.voice or not ctx.author.voice.channel:
            return ToolResult(False, "You must be in a voice channel to claim it.")
        try:
            await voice_cog._execute_vcclaim(ctx, channel=ctx.author.voice.channel)
            return ToolResult(True, f"Done! 👑 You are now the owner of **{ctx.author.voice.channel.name}**.", action_type="voice_claim")
        except Exception as e:
            return ToolResult(False, f"Could not claim voice channel: {e}")

    # ── Moderation Executors ──

    async def _exec_mod_kick(self, ctx: UnifiedContext, target: discord.Member = None, reason: str = "Kicked via SOUL Assistant") -> ToolResult:
        mod_cog = self.bot.get_cog("Moderation")
        if not mod_cog or not target:
            return ToolResult(False, "Please specify which member to kick.")
        try:
            await mod_cog._execute_kick(ctx, member=target, reason=reason)
            return ToolResult(True, f"Done! 👢 Kicked **{target.display_name}** from the server.", action_type="mod_kick")
        except Exception as e:
            return ToolResult(False, f"Could not kick member: {e}")

    async def _exec_mod_ban(self, ctx: UnifiedContext, target: discord.Member = None, reason: str = "Banned via SOUL Assistant") -> ToolResult:
        mod_cog = self.bot.get_cog("Moderation")
        if not mod_cog or not target:
            return ToolResult(False, "Please specify which member to ban.")
        try:
            await mod_cog._execute_ban(ctx, member=target, reason=reason, delete_message_days=0)
            return ToolResult(True, f"Done! 🔨 Banned **{target.display_name}** from the server.", action_type="mod_ban")
        except Exception as e:
            return ToolResult(False, f"Could not ban member: {e}")

    async def _exec_mod_unban(self, ctx: UnifiedContext, user_id: int = 0, reason: str = "Unbanned via SOUL Assistant") -> ToolResult:
        mod_cog = self.bot.get_cog("Moderation")
        if not mod_cog or not user_id:
            return ToolResult(False, "Please provide the User ID to unban.")
        try:
            await mod_cog._execute_unban(ctx, user_id=user_id, reason=reason)
            return ToolResult(True, f"Done! 🔓 Unbanned user ID `{user_id}`.", action_type="mod_unban")
        except Exception as e:
            return ToolResult(False, f"Could not unban user: {e}")

    async def _exec_mod_timeout(self, ctx: UnifiedContext, target: discord.Member = None, duration: str = "10m", reason: str = "Timed out via SOUL Assistant") -> ToolResult:
        mod_cog = self.bot.get_cog("Moderation")
        if not mod_cog or not target:
            return ToolResult(False, "Please specify which member to timeout.")
        try:
            await mod_cog._execute_timeout(ctx, member=target, duration_str=duration, reason=reason)
            return ToolResult(True, f"Done! ⏳ Timed out **{target.display_name}** for {duration}.", action_type="mod_timeout")
        except Exception as e:
            return ToolResult(False, f"Could not timeout member: {e}")

    async def _exec_mod_untimeout(self, ctx: UnifiedContext, target: discord.Member = None, reason: str = "Timeout removed via SOUL Assistant") -> ToolResult:
        mod_cog = self.bot.get_cog("Moderation")
        if not mod_cog or not target:
            return ToolResult(False, "Please specify which member to remove timeout from.")
        try:
            await mod_cog._execute_untimeout(ctx, member=target, reason=reason)
            return ToolResult(True, f"Done! 🔓 Removed timeout for **{target.display_name}**.", action_type="mod_untimeout")
        except Exception as e:
            return ToolResult(False, f"Could not remove timeout: {e}")

    async def _exec_mod_warn(self, ctx: UnifiedContext, target: discord.Member = None, reason: str = "Warned via SOUL Assistant") -> ToolResult:
        mod_cog = self.bot.get_cog("Moderation")
        if not mod_cog or not target:
            return ToolResult(False, "Please specify which member to warn.")
        try:
            await mod_cog._execute_warn(ctx, member=target, reason=reason)
            return ToolResult(True, f"Done! ⚠️ Issued warning to **{target.display_name}**.", action_type="mod_warn")
        except Exception as e:
            return ToolResult(False, f"Could not warn member: {e}")

    async def _exec_mod_warnings(self, ctx: UnifiedContext, target: discord.Member = None) -> ToolResult:
        mod_cog = self.bot.get_cog("Moderation")
        if not mod_cog or not target:
            return ToolResult(False, "Please specify which member's warnings to check.")
        try:
            await mod_cog._execute_warnings(ctx, member=target)
            return ToolResult(True, f"Retrieved warnings for **{target.display_name}**.", action_type="mod_warnings")
        except Exception as e:
            return ToolResult(False, f"Could not retrieve warnings: {e}")

    async def _exec_mod_clearwarns(self, ctx: UnifiedContext, target: discord.Member = None) -> ToolResult:
        mod_cog = self.bot.get_cog("Moderation")
        if not mod_cog or not target:
            return ToolResult(False, "Please specify which member's warnings to clear.")
        try:
            await mod_cog._execute_clearwarns(ctx, member=target)
            return ToolResult(True, f"Done! 🧹 Cleared all warnings for **{target.display_name}**.", action_type="mod_clearwarns")
        except Exception as e:
            return ToolResult(False, f"Could not clear warnings: {e}")

    async def _exec_mod_purge(self, ctx: UnifiedContext, count: int = 10, target: Optional[discord.Member] = None) -> ToolResult:
        mod_cog = self.bot.get_cog("Moderation")
        if not mod_cog:
            return ToolResult(False, "Moderation subsystem is currently unavailable.")
        count = max(1, min(100, count))
        try:
            await mod_cog._execute_purge(ctx, limit=count, target_user=target)
            return ToolResult(True, f"Done! 🧹 Purged **{count}** messages.", action_type="mod_purge")
        except Exception as e:
            return ToolResult(False, f"Could not purge messages: {e}")

    async def _exec_mod_lock(self, ctx: UnifiedContext, reason: str = "Channel locked via SOUL Assistant") -> ToolResult:
        mod_cog = self.bot.get_cog("Moderation")
        if not mod_cog:
            return ToolResult(False, "Moderation subsystem is currently unavailable.")
        try:
            await mod_cog._execute_lock(ctx, channel=ctx.channel, reason=reason)
            return ToolResult(True, f"Done! 🔒 **#{ctx.channel.name}** is now locked.", action_type="mod_lock")
        except Exception as e:
            return ToolResult(False, f"Could not lock channel: {e}")

    async def _exec_mod_unlock(self, ctx: UnifiedContext, reason: str = "Channel unlocked via SOUL Assistant") -> ToolResult:
        mod_cog = self.bot.get_cog("Moderation")
        if not mod_cog:
            return ToolResult(False, "Moderation subsystem is currently unavailable.")
        try:
            await mod_cog._execute_unlock(ctx, channel=ctx.channel, reason=reason)
            return ToolResult(True, f"Done! 🔓 **#{ctx.channel.name}** is now unlocked.", action_type="mod_unlock")
        except Exception as e:
            return ToolResult(False, f"Could not unlock channel: {e}")

    async def _exec_mod_slowmode(self, ctx: UnifiedContext, seconds: int = 0) -> ToolResult:
        mod_cog = self.bot.get_cog("Moderation")
        if not mod_cog:
            return ToolResult(False, "Moderation subsystem is currently unavailable.")
        try:
            await mod_cog._execute_slowmode(ctx, seconds=seconds, channel=ctx.channel)
            slow_str = f"{seconds} seconds" if seconds > 0 else "disabled"
            return ToolResult(True, f"Done! ⏱️ Slowmode set to **{slow_str}**.", action_type="mod_slowmode")
        except Exception as e:
            return ToolResult(False, f"Could not set slowmode: {e}")

    # ── Utility & Economy Executors ──

    async def _exec_util_serverinfo(self, ctx: UnifiedContext) -> ToolResult:
        util_cog = self.bot.get_cog("Utility")
        if not util_cog:
            return ToolResult(False, "Utility subsystem is unavailable.")
        try:
            await util_cog._execute_serverinfo(ctx)
            return ToolResult(True, "Here are the server details.", action_type="util_serverinfo")
        except Exception as e:
            return ToolResult(False, f"Could not get server info: {e}")

    async def _exec_util_membercount(self, ctx: UnifiedContext) -> ToolResult:
        util_cog = self.bot.get_cog("Utility")
        if not util_cog:
            return ToolResult(False, "Utility subsystem is unavailable.")
        try:
            await util_cog._execute_membercount(ctx)
            return ToolResult(True, "Here is the server member count.", action_type="util_membercount")
        except Exception as e:
            return ToolResult(False, f"Could not get member count: {e}")

    async def _exec_util_userinfo(self, ctx: UnifiedContext, target: Optional[discord.Member] = None) -> ToolResult:
        util_cog = self.bot.get_cog("Utility")
        if not util_cog:
            return ToolResult(False, "Utility subsystem is unavailable.")
        member = target or ctx.author
        try:
            await util_cog._execute_userinfo(ctx, member=member)
            return ToolResult(True, f"Here is the user profile for **{member.display_name}**.", action_type="util_userinfo")
        except Exception as e:
            return ToolResult(False, f"Could not get user info: {e}")

    async def _exec_util_avatar(self, ctx: UnifiedContext, target: Optional[discord.Member] = None) -> ToolResult:
        util_cog = self.bot.get_cog("Utility")
        if not util_cog:
            return ToolResult(False, "Utility subsystem is unavailable.")
        member = target or ctx.author
        try:
            await util_cog._execute_avatar(ctx, member=member)
            return ToolResult(True, f"Here is the avatar for **{member.display_name}**.", action_type="util_avatar")
        except Exception as e:
            return ToolResult(False, f"Could not get avatar: {e}")

    async def _exec_util_ping(self, ctx: UnifiedContext) -> ToolResult:
        util_cog = self.bot.get_cog("Utility")
        if not util_cog:
            return ToolResult(False, "Utility subsystem is unavailable.")
        try:
            await util_cog._execute_ping(ctx)
            return ToolResult(True, "Latency and heartbeat status retrieved.", action_type="util_ping")
        except Exception as e:
            return ToolResult(False, f"Could not check latency: {e}")

    async def _exec_util_uptime(self, ctx: UnifiedContext) -> ToolResult:
        util_cog = self.bot.get_cog("Utility")
        if not util_cog:
            return ToolResult(False, "Utility subsystem is unavailable.")
        try:
            await util_cog._execute_uptime(ctx)
            return ToolResult(True, "Bot uptime statistics retrieved.", action_type="util_uptime")
        except Exception as e:
            return ToolResult(False, f"Could not check uptime: {e}")

    async def _exec_eco_balance(self, ctx: UnifiedContext, target: Optional[discord.Member] = None) -> ToolResult:
        eco_cog = self.bot.get_cog("EconomyCog")
        if not eco_cog:
            return ToolResult(False, "Economy subsystem is unavailable.")
        member = target or ctx.author
        try:
            await eco_cog._execute_balance(ctx, member=member)
            return ToolResult(True, f"Here is the balance for **{member.display_name}**.", action_type="eco_balance")
        except Exception as e:
            return ToolResult(False, f"Could not check balance: {e}")

    async def _exec_eco_daily(self, ctx: UnifiedContext) -> ToolResult:
        eco_cog = self.bot.get_cog("EconomyCog")
        if not eco_cog:
            return ToolResult(False, "Economy subsystem is unavailable.")
        try:
            await eco_cog._execute_daily(ctx)
            return ToolResult(True, "Daily reward processed.", action_type="eco_daily")
        except Exception as e:
            return ToolResult(False, f"Could not claim daily reward: {e}")

    async def _exec_level_rank(self, ctx: UnifiedContext, target: Optional[discord.Member] = None) -> ToolResult:
        lvl_cog = self.bot.get_cog("LevelingCog")
        if not lvl_cog:
            return ToolResult(False, "Leveling subsystem is unavailable.")
        member = target or ctx.author
        try:
            await lvl_cog._execute_rank(ctx, member=member)
            return ToolResult(True, f"Here is the rank card for **{member.display_name}**.", action_type="level_rank")
        except Exception as e:
            return ToolResult(False, f"Could not get rank: {e}")

    async def _exec_level_leaderboard(self, ctx: UnifiedContext) -> ToolResult:
        lvl_cog = self.bot.get_cog("LevelingCog")
        if not lvl_cog:
            return ToolResult(False, "Leveling subsystem is unavailable.")
        try:
            await lvl_cog._execute_leaderboard(ctx, page=1)
            return ToolResult(True, "Here is the server level leaderboard.", action_type="level_leaderboard")
        except Exception as e:
            return ToolResult(False, f"Could not retrieve leaderboard: {e}")
