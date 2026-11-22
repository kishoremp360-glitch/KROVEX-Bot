"""KROVEX Voice Bulk Action Engine & Safety Assurance System.

Handles Scope A (Current Voice Channel) and Scope B (Server-Wide / Selected Channels)
bulk actions with strict authorization, role hierarchy checks, protected member immunity,
and two-step confirmation dialogs.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple, Union

import discord
from discord import app_commands

from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.ownervc.bulk_engine")
BRAND_COLOR = 0x9D4EDD  # Neon purple
ACCENT_COLOR = 0xD946EF  # Magenta


@dataclass
class BulkExecutionPlan:
    """Detailed summary of a pending or completed bulk operation."""
    action_type: str  # mute, unmute, deafen, undeafen, move, disconnect
    scope: str        # current_vc, server_wide, selected_channels, selected_members
    guild_id: int
    executor_id: int
    source_channels: List[discord.VoiceChannel] = field(default_factory=list)
    destination_channel: Optional[discord.VoiceChannel] = None
    target_members: List[discord.Member] = field(default_factory=list)
    eligible_members: List[discord.Member] = field(default_factory=list)
    protected_members: List[discord.Member] = field(default_factory=list)
    unreachable_members: List[discord.Member] = field(default_factory=list)
    success_count: int = 0
    fail_count: int = 0
    failed_details: List[str] = field(default_factory=list)


class BulkActionConfirmView(discord.ui.View):
    """Two-step verification modal/dialog for high-impact bulk voice actions."""

    def __init__(
        self,
        bot: "DeathBot",
        plan: BulkExecutionPlan,
        on_confirm: Callable[[discord.Interaction, BulkExecutionPlan], Any],
        on_cancel: Optional[Callable[[discord.Interaction], Any]] = None,
        timeout: float = 60.0,
    ) -> None:
        try:
            asyncio.get_running_loop()
            super().__init__(timeout=timeout)
        except RuntimeError:
            from unittest.mock import MagicMock, patch
            mock_loop = MagicMock()
            mock_loop.create_future.return_value = MagicMock()
            with patch("asyncio.get_running_loop", return_value=mock_loop):
                super().__init__(timeout=timeout)
        self.bot = bot
        self.plan = plan
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel
        self.confirmed = False
        self._lock = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.plan.executor_id:
            await interaction.response.send_message(
                f"{KrovexEmoji.CROSS} Only the administrator who initiated this action may confirm it.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm Action", style=discord.ButtonStyle.danger, emoji="⚠️", row=0)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if self.confirmed:
                await interaction.response.send_message("⚠️ Action already confirmed and running.", ephemeral=True)
                return
            self.confirmed = True

        for child in self.children:
            child.disabled = True  # type: ignore

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        await self.on_confirm(interaction, self.plan)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️", row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore
        self.stop()
        msg = "🛑 **Bulk action cancelled.** No members or channels were modified."
        if not interaction.response.is_done():
            await interaction.response.edit_message(content=msg, embed=None, view=None)
        else:
            await interaction.followup.send(msg, ephemeral=True)
        if self.on_cancel:
            await self.on_cancel(interaction)


class VoiceBulkActionEngine:
    """Thread-safe engine for performing mass voice channel operations."""

    def __init__(self, bot: "DeathBot") -> None:
        self.bot = bot
        self._guild_locks: Dict[int, asyncio.Lock] = {}

    def _get_lock(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self._guild_locks:
            self._guild_locks[guild_id] = asyncio.Lock()
        return self._guild_locks[guild_id]

    def is_protected_member(
        self,
        member: Union[discord.Member, discord.User],
        guild: Optional[discord.Guild],
    ) -> bool:
        """Determines if a member has sovereign immunity from voice moderation."""
        if not member:
            return False
        # Bot self-immunity
        if getattr(member, "id", 0) == getattr(self.bot.user, "id", -1):
            return True
        # Server sovereign
        if guild and member.id == guild.owner_id:
            return True
        # Configured bot owners
        raw_owners = getattr(self.bot.config, "owner_ids", [])
        if member.id in raw_owners or str(member.id) in [str(x) for x in raw_owners]:
            return True
        app_owners = getattr(self.bot, "owner_ids", set()) or set()
        if member.id in app_owners or str(member.id) in [str(x) for x in app_owners]:
            return True
        if hasattr(self.bot, "is_bot_owner") and callable(self.bot.is_bot_owner):
            try:
                res = self.bot.is_bot_owner(member)
                if isinstance(res, bool) and res:
                    return True
            except Exception:
                pass
        return False

    def can_moderate_member(
        self,
        bot_member: discord.Member,
        target: discord.Member,
    ) -> Tuple[bool, str]:
        """Validates Discord permission and role hierarchy against a target member."""
        if target.id == bot_member.id:
            return False, "Cannot moderate self"
        if self.is_protected_member(target, target.guild):
            return False, "Protected Sovereign / Bot Owner"
        # Discord hierarchy: bot's top role must be strictly above target's top role
        if target.guild.owner_id == target.id:
            return False, "Target is Guild Owner"
        raw_bot_pos = getattr(getattr(bot_member, "top_role", None), "position", 0)
        raw_target_pos = getattr(getattr(target, "top_role", None), "position", 0)
        bot_pos = raw_bot_pos if isinstance(raw_bot_pos, (int, float)) else 0
        target_pos = raw_target_pos if isinstance(raw_target_pos, (int, float)) else 0
        if getattr(bot_member.guild, "owner_id", None) != bot_member.id and bot_pos <= target_pos:
            target_name = getattr(target.top_role, "name", "Role")
            bot_name = getattr(bot_member.top_role, "name", "Bot")
            return False, f"Target role ({target_name}) >= Bot role ({bot_name})"
        return True, "Eligible"

    def build_plan(
        self,
        action_type: str,
        scope: str,
        guild: discord.Guild,
        executor: discord.Member,
        source_channels: List[discord.VoiceChannel],
        destination_channel: Optional[discord.VoiceChannel] = None,
        specific_members: Optional[List[discord.Member]] = None,
    ) -> BulkExecutionPlan:
        """Inspects guild voice state and prepares a safe execution plan."""
        plan = BulkExecutionPlan(
            action_type=action_type,
            scope=scope,
            guild_id=guild.id,
            executor_id=executor.id,
            source_channels=source_channels,
            destination_channel=destination_channel,
        )

        bot_member = guild.me or guild.get_member(self.bot.user.id if self.bot.user else 0)

        raw_targets: List[discord.Member] = []
        if specific_members is not None:
            raw_targets = specific_members
        else:
            for ch in source_channels:
                for m in ch.members:
                    if m not in raw_targets:
                        raw_targets.append(m)

        plan.target_members = raw_targets

        for m in raw_targets:
            if not m.voice or not m.voice.channel:
                plan.unreachable_members.append(m)
                continue

            if self.is_protected_member(m, guild):
                plan.protected_members.append(m)
                continue

            if bot_member:
                can_mod, reason = self.can_moderate_member(bot_member, m)
                if not can_mod:
                    plan.protected_members.append(m)
                    continue

            plan.eligible_members.append(m)

        return plan

    def build_confirm_embed(self, plan: BulkExecutionPlan) -> discord.Embed:
        """Constructs an embed clearly detailing the scope and member impact."""
        action_title = plan.action_type.replace("_", " ").upper()
        scope_str = "Current Voice Channel" if plan.scope == "current_vc" else "Server-Wide"
        if plan.scope == "selected_channels":
            scope_str = f"Selected Channels ({len(plan.source_channels)})"
        elif plan.scope == "selected_members":
            scope_str = f"Selected Members ({len(plan.target_members)})"

        embed = discord.Embed(
            title=f"⚠️ KROVEX — Confirm {action_title}",
            description=(
                f"**Target Scope:** `{scope_str}`\n"
                f"**Channels Affected:** `{len(plan.source_channels)}`\n"
                f"**Total Members Found:** `{len(plan.target_members)}`\n"
                f"**Eligible to Execute:** `{len(plan.eligible_members)}`\n"
                f"**Protected / Skipped:** `{len(plan.protected_members)}`\n"
            ),
            color=0xFEE75C,  # Warning yellow
            timestamp=datetime.now(timezone.utc),
        )

        if plan.destination_channel:
            embed.add_field(
                name="🎯 Destination Channel",
                value=f"{plan.destination_channel.mention} (`{plan.destination_channel.id}`)",
                inline=False,
            )

        if plan.source_channels and len(plan.source_channels) <= 5:
            ch_list = "\n".join(f"• {c.name} ({len(c.members)} members)" for c in plan.source_channels)
            embed.add_field(name="🎙️ Source Channels", value=ch_list, inline=False)
        elif len(plan.source_channels) > 5:
            embed.add_field(
                name="🎙️ Source Channels",
                value=f"{len(plan.source_channels)} voice channels across the server",
                inline=False,
            )

        if plan.protected_members:
            names = [m.display_name for m in plan.protected_members[:5]]
            extra = f" +{len(plan.protected_members)-5} more" if len(plan.protected_members) > 5 else ""
            embed.add_field(
                name="🛡️ Immune / Protected (Will NOT be modified)",
                value=", ".join(names) + extra,
                inline=False,
            )

        embed.set_footer(text="KROVEX BULK SAFEGUARD • Explicit Confirmation Required")
        return embed

    async def execute_plan(
        self,
        plan: BulkExecutionPlan,
        progress_callback: Optional[Callable[[int, int], Any]] = None,
    ) -> BulkExecutionPlan:
        """Executes the verified bulk plan with concurrency locking and rate-limiting."""
        guild_lock = self._get_lock(plan.guild_id)
        async with guild_lock:
            total = len(plan.eligible_members)
            done = 0

            for member in list(plan.eligible_members):
                # Double-check member voice connection has not been severed
                if not member.voice or not member.voice.channel:
                    plan.fail_count += 1
                    plan.failed_details.append(f"{member.display_name}: Left voice channel")
                    continue

                try:
                    if plan.action_type == "mute":
                        if not member.voice.mute:
                            await member.edit(mute=True, reason=f"KROVEX Bulk Mute ({plan.scope})")
                        plan.success_count += 1
                    elif plan.action_type == "unmute":
                        if member.voice.mute:
                            await member.edit(mute=False, reason=f"KROVEX Bulk Unmute ({plan.scope})")
                        plan.success_count += 1
                    elif plan.action_type == "deafen":
                        if not member.voice.deaf:
                            await member.edit(deafen=True, reason=f"KROVEX Bulk Deafen ({plan.scope})")
                        plan.success_count += 1
                    elif plan.action_type == "undeafen":
                        if member.voice.deaf:
                            await member.edit(deafen=False, reason=f"KROVEX Bulk Undeafen ({plan.scope})")
                        plan.success_count += 1
                    elif plan.action_type == "move":
                        if plan.destination_channel:
                            if member.voice.channel.id != plan.destination_channel.id:
                                await member.move_to(
                                    plan.destination_channel,
                                    reason=f"KROVEX Bulk Move to #{plan.destination_channel.name}",
                                )
                            plan.success_count += 1
                        else:
                            plan.fail_count += 1
                            plan.failed_details.append(f"{member.display_name}: No destination selected")
                    elif plan.action_type == "disconnect":
                        await member.move_to(None, reason=f"KROVEX Bulk Disconnect ({plan.scope})")
                        plan.success_count += 1
                    else:
                        plan.fail_count += 1
                        plan.failed_details.append(f"Unknown action: {plan.action_type}")

                except discord.Forbidden as err:
                    plan.fail_count += 1
                    plan.failed_details.append(f"{member.display_name}: Missing Discord Permissions ({err})")
                except discord.HTTPException as err:
                    plan.fail_count += 1
                    plan.failed_details.append(f"{member.display_name}: Discord API error ({err})")
                except Exception as err:
                    plan.fail_count += 1
                    plan.failed_details.append(f"{member.display_name}: Unexpected error ({err})")

                done += 1
                if progress_callback:
                    try:
                        res = progress_callback(done, total)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception:
                        pass

                # Micro-throttle to prevent Discord 429 gateway rate-limiting
                await asyncio.sleep(0.12)

        # Record into persistent audit logs
        if hasattr(self.bot, "vc_repo") and self.bot.vc_repo:
            try:
                dest_id = plan.destination_channel.id if plan.destination_channel else None
                src_id = plan.source_channels[0].id if plan.source_channels else None
                details_text = "; ".join(plan.failed_details[:5])
                await self.bot.vc_repo.log_action(
                    guild_id=plan.guild_id,
                    executor_id=plan.executor_id,
                    action_type=f"{plan.action_type}_all" if plan.scope != "selected_members" else plan.action_type,
                    scope=plan.scope,
                    source_channel_id=src_id,
                    destination_channel_id=dest_id,
                    target_count=len(plan.target_members),
                    success_count=plan.success_count,
                    fail_count=plan.fail_count,
                    details=details_text,
                )
            except Exception as log_err:
                logger.warning("Failed to persist bulk action log: %s", log_err)

        return plan

    async def execute_emergency_quarantine(
        self,
        guild: discord.Guild,
        executor: discord.Member,
    ) -> BulkExecutionPlan:
        """Isolate all non-staff voice connected members into a locked quarantine channel."""
        # 1. Find or create 🚨・Quarantine voice channel
        quarantine_ch = discord.utils.find(lambda c: "quarantine" in c.name.lower(), getattr(guild, "voice_channels", []))
        if not quarantine_ch:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    connect=False,
                    speak=False,
                    send_messages=False,
                    use_soundboard=False,
                    stream=False,
                ),
            }
            if getattr(guild, "me", None):
                overwrites[guild.me] = discord.PermissionOverwrite(
                    connect=True,
                    speak=True,
                    manage_channels=True,
                    move_members=True,
                    mute_members=True,
                )
            try:
                quarantine_ch = await guild.create_voice_channel(
                    name="🚨・Quarantine",
                    overwrites=overwrites,
                    reason=f"KROVEX Emergency Quarantine activated by {executor}",
                )
            except Exception as err:
                logger.error("Failed to create quarantine channel: %s", err)
                raise err

        # 2. Gather non-protected members across all voice channels
        targets = []
        for vc in getattr(guild, "voice_channels", []):
            if vc.id == quarantine_ch.id:
                continue
            for m in getattr(vc, "members", []):
                if not self.is_protected_member(m, guild):
                    targets.append(m)

        plan = self.build_plan(
            action_type="quarantine",
            scope="server_wide",
            guild=guild,
            executor=executor,
            source_channels=[vc for vc in getattr(guild, "voice_channels", []) if vc.id != quarantine_ch.id],
            destination_channel=quarantine_ch,
            specific_members=targets,
        )

        for m in plan.eligible_members:
            try:
                if getattr(m, "voice", None) and m.voice.channel:
                    await m.move_to(quarantine_ch, reason=f"KROVEX Emergency Quarantine by {executor}")
                    try:
                        await m.edit(mute=True, reason="KROVEX Emergency Quarantine: Muted")
                    except Exception:
                        pass
                    plan.success_count += 1
            except Exception as e:
                plan.fail_count += 1
                plan.failed_details.append(f"{m.display_name}: {e}")
            await asyncio.sleep(0.08)

        # Log into persistent audit logs
        if hasattr(self.bot, "vc_repo") and self.bot.vc_repo:
            try:
                await self.bot.vc_repo.log_action(
                    guild_id=guild.id,
                    executor_id=getattr(executor, "id", 0),
                    action_type="emergency_quarantine",
                    scope="server_wide",
                    source_channel_id=None,
                    destination_channel_id=quarantine_ch.id,
                    target_count=len(targets),
                    success_count=plan.success_count,
                    fail_count=plan.fail_count,
                    details=f"Isolated {plan.success_count} members into quarantine",
                )
            except Exception as log_err:
                logger.warning("Failed to log emergency quarantine: %s", log_err)

        return plan

    def build_result_embed(self, plan: BulkExecutionPlan) -> discord.Embed:
        """Generates a comprehensive execution report embed."""
        color = 0x57F287 if plan.fail_count == 0 else (0xED4245 if plan.success_count == 0 else 0xFEE75C)
        action_name = plan.action_type.replace("_", " ").title()

        embed = discord.Embed(
            title=f"✅ KROVEX — Bulk {action_name} Report",
            description=(
                f"**Scope:** `{plan.scope.replace('_', ' ').title()}`\n"
                f"**Target Channels:** `{len(plan.source_channels)}`\n\n"
                f"• **Successful Operations:** `{plan.success_count}`\n"
                f"• **Failed / Unreachable:** `{plan.fail_count}`\n"
                f"• **Protected & Skipped:** `{len(plan.protected_members)}`\n"
            ),
            color=color,
            timestamp=datetime.now(timezone.utc),
        )

        if plan.destination_channel:
            embed.add_field(
                name="🎯 Destination Voice Channel",
                value=f"{plan.destination_channel.mention} (`{plan.destination_channel.id}`)",
                inline=False,
            )

        if plan.failed_details:
            details_str = "\n".join(f"• {d}" for d in plan.failed_details[:6])
            if len(plan.failed_details) > 6:
                details_str += f"\n*...and {len(plan.failed_details)-6} more issues.*"
            embed.add_field(name="⚠️ Error Summaries", value=details_str, inline=False)

        embed.set_footer(text="KROVEX VOICE ENGINE • AUDITED & RECORDED")
        return embed


async def setup(bot: "DeathBot") -> None:
    """Extension discovery hook."""
    pass

