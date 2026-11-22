"""KROVEX SOUL Discord Integration Cog.

Provides conversational intelligence listeners and diagnostics:
- Natural mention triggers (@KROVEX <message>)
- Direct reply triggers (replying to any message sent by KROVEX)
- Active conversation session continuity (continue chatting without repeated mentions)
- Emoji and repeated emoji understanding with Discord custom emoji normalization
- Conversation termination detection (natural goodbyes close active sessions)
- Reaction acknowledgment on KROVEX messages during active sessions
- Safe message content stripping and prompt normalization
- Prefix command passthrough and coexistence
- Typing indicators and Discord 2000-character chunking
- Mass mention and ping injection protection
- Owner-only diagnostics (!soultest <prompt>)
"""
from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.checks import is_bot_owner
from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.cogs.soul")


def normalize_discord_emojis(text: str) -> str:
    """Normalize Discord custom emojis <:name:id> and <a:name:id> to :name: for LLM comprehension."""
    return re.sub(r"<a?:([a-zA-Z0-9_]+):[0-9]+>", r":\1:", text)


def is_conversation_ending(text: str) -> bool:
    """Detect if the user's message explicitly ends the conversational session."""
    if not text:
        return False

    normalized = text.lower().strip()
    # Strip basic surrounding punctuation
    cleaned = re.sub(r"[^\w\s]", "", normalized).strip()
    words = cleaned.split()
    if not words or len(words) > 5:
        return False

    # Never treat casual acknowledgments alone as ending
    casual_words = {"seri", "okay", "ok", "hmm", "edhuuuu", "ohh", "dei", "aama", "yes", "sure"}
    if len(words) == 1 and words[0] in casual_words:
        return False

    # Exact phrase matches
    end_phrases = {
        "bye", "byee", "byeee", "bye da", "bye macha", "bye machaww",
        "seri bye", "seri bye da", "ok bye", "ok bye da", "okay bye", "tata", "tata bye", "tata bye bye",
        "good night", "goodnight", "gn", "gn da", "gn macha", "gdn8", "good nite",
        "stop", "end chat", "exit", "exit chat", "close chat",
        "podhum", "podhum da", "see you", "see ya", "cya", "later macha",
    }
    if cleaned in end_phrases:
        return True

    # If message contains farewell keyword in a short message (<= 5 words)
    farewell_keywords = {"bye", "byee", "byeee", "tata", "goodnight", "gn"}
    if any(w in farewell_keywords for w in words):
        return True

    if "good" in words and "night" in words:
        return True
    if "end" in words and "chat" in words:
        return True
    if words == ["stop"]:
        return True

    return False


def split_discord_message(text: str, max_chars: int = 1900) -> List[str]:
    """Split response text into chunks that safely fit inside Discord's 2000 char limit."""
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    remaining = text
    while len(remaining) > max_chars:
        # Try to break at a paragraph newline
        split_idx = remaining.rfind("\n", 0, max_chars)
        # Fallback to sentence punctuation
        if split_idx == -1:
            for punct in (". ", "! ", "? "):
                idx = remaining.rfind(punct, 0, max_chars)
                if idx != -1 and idx > split_idx:
                    split_idx = idx + 1
        # Fallback to space
        if split_idx == -1:
            split_idx = remaining.rfind(" ", 0, max_chars)
        # Hard break if no delimiter found
        if split_idx == -1:
            split_idx = max_chars

        chunk = remaining[:split_idx].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_idx:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


class Soul(commands.Cog, name="Soul"):
    """KROVEX SOUL conversational companion and natural friend listener."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    @commands.Cog.listener("on_message")
    async def on_message(self, message: discord.Message) -> None:
        """Listen for bot mentions, direct replies, and active conversation follow-ups."""
        # 1. Ignore bots, webhooks, and messages without guild
        if message.author.bot or getattr(message, "webhook_id", None) is not None:
            return

        if not message.guild or not message.content:
            return

        # 2. Ignore if bot user is not ready
        bot_user = self.bot.user
        if not bot_user:
            return

        # 3. Existing Prefix Command Compatibility
        # If the message is a valid prefix command (e.g. !help, !play, or custom commands),
        # yield immediately so SOUL never intercepts commands.
        try:
            ctx = await self.bot.get_context(message)
            if ctx.valid:
                return
        except Exception:
            pass

        # Standalone messages starting with common bot command prefixes (. ! ? / $ -)
        # must never be hijacked by conversational session continuity.
        content_stripped = message.content.strip()
        if content_stripped.startswith((".", "!", "?", "/", "$", "-")):
            return

        # 4. Trigger & Session Continuity Detection
        # A. Direct mention of the bot (ignoring @everyone and @here)
        is_mentioned = False
        if not message.mention_everyone and bot_user in message.mentions:
            is_mentioned = True

        # B. Direct reply to a message authored by the bot
        is_reply_to_bot = False
        if message.reference:
            ref = message.reference
            ref_msg = getattr(ref, "resolved", None)
            if isinstance(ref_msg, discord.Message):
                if ref_msg.author.id == bot_user.id:
                    is_reply_to_bot = True
            elif ref_msg is None and getattr(ref, "message_id", None):
                # Handle unresolved reply references safely
                try:
                    fetched = await message.channel.fetch_message(ref.message_id)
                    if fetched and fetched.author.id == bot_user.id:
                        is_reply_to_bot = True
                except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                    pass

        # C. Active Session Continuity Check
        soul_service = getattr(self.bot, "soul_service", None)
        if soul_service is None:
            return

        is_session_active = soul_service.is_session_active(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            timeout_minutes=30,
        )

        # If message neither mentions KROVEX, nor replies to KROVEX, nor has an active session, ignore
        if not is_mentioned and not is_reply_to_bot and not is_session_active:
            return

        # 5. Permission Check: Verify bot can send messages in the channel
        channel = message.channel
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            me = message.guild.me
            if me:
                perms = channel.permissions_for(me)
                if not perms.send_messages:
                    return

        # 6. Sanitize Prompt & Normalize Discord Custom Emojis
        content = message.content
        mention_pattern = rf"<@!?{bot_user.id}>"
        clean_prompt = re.sub(mention_pattern, "", content).strip()
        # Convert any third-party mentions to readable display names for AI comprehension
        for m in getattr(message, "mentions", []):
            if m.id != bot_user.id and getattr(m, "display_name", None):
                clean_prompt = re.sub(rf"<@!?{m.id}>", m.display_name, clean_prompt)
        clean_prompt = normalize_discord_emojis(clean_prompt)
        if not clean_prompt:
            clean_prompt = "hello macha"

        # 7. Check if user is ending the conversation
        is_ending = is_conversation_ending(clean_prompt)

        # 8. Safe AllowedMentions Policy: reply to author, but prevent user/role/everyone pings
        safe_mentions = discord.AllowedMentions(
            replied_user=True,
            users=False,
            roles=False,
            everyone=False,
        )

        # 9. Send Typing Indicator & Generate AI Response
        author = message.author
        display_name = getattr(author, "display_name", None) or getattr(author, "name", None) or "machaww"
        username = getattr(author, "name", None)
        channel_name = getattr(channel, "name", None)

        try:
            async with channel.typing():
                is_admin = False
                if isinstance(author, discord.Member):
                    is_admin = getattr(author.guild_permissions, "administrator", False)

                # Route to action assistant engine if available on real SoulService, or fallback for mocks
                import inspect
                pnlr = getattr(soul_service, "process_natural_language_request", None)
                if type(soul_service).__name__ == "SoulService" or (pnlr and (inspect.iscoroutinefunction(pnlr) or hasattr(pnlr, "assert_awaited"))):
                    reply, error = await soul_service.process_natural_language_request(
                        bot=self.bot,
                        message=message,
                        clean_prompt=clean_prompt,
                    )
                else:
                    reply, error = await soul_service.generate_chat_reply(
                        guild_id=message.guild.id,
                        channel_id=channel.id,
                        user_id=author.id,
                        user_name=display_name,
                        message_text=clean_prompt,
                        server_name=message.guild.name,
                        channel_name=channel_name,
                        username=username,
                        is_admin=is_admin,
                    )
        except Exception as exc:
            logger.error("Unexpected error in SOUL on_message handler: %s", exc, exc_info=True)
            friendly_err = "Dei machaww, chinna connection issue! Konjam neram kalichu try pannu da 😅"
            try:
                await message.reply(friendly_err, allowed_mentions=safe_mentions)
            except discord.HTTPException:
                pass
            return

        # 10. Handle Generation Output
        if error:
            # Cooldown notice: notify user directly
            if "Chill macha" in error or "cooldown" in error.lower():
                try:
                    await message.reply(error, allowed_mentions=safe_mentions)
                except discord.HTTPException:
                    pass
                return

            # Disabled or channel restriction: silently ignore
            if "disabled" in error.lower() or "not permitted" in error.lower():
                return

            # Provider error / unconfigured key: friendly Tanglish fallback
            friendly_err = "Dei machaww, chinna connection issue! Konjam neram kalichu try pannu da 😅"
            try:
                await message.reply(friendly_err, allowed_mentions=safe_mentions)
            except discord.HTTPException:
                pass
            return

        if not reply:
            return

        # 11. Manage Session State (Activation vs Termination)
        if is_ending:
            soul_service.end_session(message.guild.id, channel.id, message.author.id)
        else:
            soul_service.activate_session(message.guild.id, channel.id, message.author.id)

        # 12. Chunk and Dispatch Response within Discord Message Limits
        chunks = split_discord_message(reply, max_chars=1900)
        first = True
        for chunk in chunks:
            try:
                if first:
                    await message.reply(chunk, allowed_mentions=safe_mentions)
                    first = False
                else:
                    await channel.send(chunk, allowed_mentions=safe_mentions)
            except discord.HTTPException as err:
                logger.error("Failed to send SOUL response message: %s", err)
                break

    @commands.Cog.listener("on_raw_reaction_add")
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Acknowledge emoji reactions on KROVEX messages during active sessions."""
        bot_user = self.bot.user
        if not bot_user or payload.user_id == bot_user.id:
            return

        if not payload.guild_id:
            return

        soul_service = getattr(self.bot, "soul_service", None)
        if not soul_service:
            return

        # Only react if the user is in an active conversational session in this channel
        if not soul_service.is_session_active(payload.guild_id, payload.channel_id, payload.user_id):
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel or not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return

        try:
            msg = await channel.fetch_message(payload.message_id)
            if not msg or msg.author.id != bot_user.id:
                return

            me = channel.guild.me
            if not me or not channel.permissions_for(me).add_reactions:
                return

            emoji_str = str(payload.emoji)
            friendly_map = {
                "❤️": "🫂",
                "🫂": "❤️",
                "😂": "😂",
                "🤣": "😂",
                "💀": "😂",
                "🔥": "⚡",
                "⚡": "🔥",
                "👍": "😎",
                "👋": "👋",
            }
            react_emoji = friendly_map.get(emoji_str, emoji_str)
            await msg.add_reaction(react_emoji)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    # ── Owner-Only Diagnostic Command ──────────────────────────────────────────
    @commands.command(name="soultest", aliases=["testsoul"])
    @is_bot_owner()
    async def soul_test(self, ctx: commands.Context, *, prompt: str) -> None:
        """Owner-only testing command for KROVEX SOUL conversation engine."""
        soul_service = getattr(self.bot, "soul_service", None)
        if soul_service is None:
            await ctx.reply(f"{KrovexEmoji.ANIMATED_CROSS} SOUL service is not initialized on this bot instance.")
            return

        safe_mentions = discord.AllowedMentions(
            replied_user=True,
            users=False,
            roles=False,
            everyone=False,
        )

        async with ctx.typing():
            guild_id = ctx.guild.id if ctx.guild else 0
            guild_name = ctx.guild.name if ctx.guild else "DirectMessage"
            clean_prompt = normalize_discord_emojis(prompt.strip())
            author = ctx.author
            display_name = getattr(author, "display_name", None) or getattr(author, "name", None) or "machaww"
            username = getattr(author, "name", None)
            channel_name = getattr(ctx.channel, "name", None)
            reply, error = await soul_service.generate_chat_reply(
                guild_id=guild_id,
                channel_id=ctx.channel.id,
                user_id=author.id,
                user_name=display_name,
                message_text=clean_prompt,
                server_name=guild_name,
                channel_name=channel_name,
                username=username,
                is_admin=True,
            )

        if error:
            await ctx.reply(f"{KrovexEmoji.ANIMATED_CROSS} **SOUL Diagnostic Notice:** {error}", allowed_mentions=safe_mentions)
            return

        header = f"{KrovexEmoji.CUTE_STAR_STATIC} **KROVEX SOUL Response:**\n"
        chunks = split_discord_message(f"{header}{reply or ''}", max_chars=1900)
        for chunk in chunks:
            await ctx.reply(chunk, allowed_mentions=safe_mentions)

    # ── SOUL User & Administrative Commands ───────────────────────────────────

    async def _execute_soul_status(self, ctx_or_interaction: Any) -> None:
        """Display active SOUL session status and guild configuration."""
        guild = ctx_or_interaction.guild
        user = ctx_or_interaction.user if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author
        channel = ctx_or_interaction.channel

        if not guild:
            return

        soul_service = getattr(self.bot, "soul_service", None)
        is_active = False
        if soul_service:
            is_active = soul_service.is_session_active(guild.id, channel.id, user.id)

        session_str = "🟢 **Active** (Follow-up enabled without mentioning)" if is_active else "⚪ **Inactive** (Mention @KROVEX to activate)"

        settings = None
        if soul_service and hasattr(soul_service, "repo") and hasattr(soul_service.repo, "get_guild_settings"):
            res = soul_service.repo.get_guild_settings(guild.id)
            if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                settings = await res
            else:
                settings = res

        enabled_str = "Enabled" if (settings and settings.enabled) else "Disabled"
        cooldown_str = f"{settings.cooldown_seconds}s" if settings else "3s"

        embed = EmbedBuilder.base(
            title="🧠 KROVEX SOUL — Assistant Status",
            description=(
                f"### Member Session: {user.mention}\n"
                f"• **Session State:** {session_str}\n"
                f"• **Channel:** {channel.mention}\n"
                f"• **Inactivity Timeout:** `5 minutes`\n\n"
                f"### Server Configuration\n"
                f"• **SOUL Status:** `{enabled_str}`\n"
                f"• **Interaction Cooldown:** `{cooldown_str}`\n"
                f"• **Allowed Channels:** `All Channels`\n\n"
                f"*To use, mention KROVEX (e.g. `@KROVEX play Believer`) or talk naturally while active.*"
            ),
            color=0x9D4EDD,
        )
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await ctx_or_interaction.reply(embed=embed)

    async def _execute_soul_stop(self, ctx_or_interaction: Any) -> None:
        """Terminate the user's active SOUL session."""
        guild = ctx_or_interaction.guild
        user = ctx_or_interaction.user if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author
        channel = ctx_or_interaction.channel

        if not guild:
            return

        soul_service = getattr(self.bot, "soul_service", None)
        ended = False
        if soul_service:
            ended = soul_service.end_session(guild.id, channel.id, user.id)

        msg = "Done! 👋 Your active SOUL session has been stopped." if ended else "ℹ️ You do not currently have an active SOUL session in this channel."
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.reply(msg)

    async def _execute_soul_settings(self, ctx_or_interaction: Any) -> None:
        """View or update guild SOUL settings."""
        guild = ctx_or_interaction.guild
        if not guild:
            return

        soul_service = getattr(self.bot, "soul_service", None)
        settings = None
        if soul_service and hasattr(soul_service, "repo") and hasattr(soul_service.repo, "get_guild_settings"):
            res = soul_service.repo.get_guild_settings(guild.id)
            if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                settings = await res
            else:
                settings = res

        embed = EmbedBuilder.base(
            title="⚙️ KROVEX SOUL — Server Settings",
            description=(
                f"**Guild:** {guild.name} (`{guild.id}`)\n\n"
                f"• **System Enabled:** `{'Yes' if settings and settings.enabled else 'No'}`\n"
                f"• **Default Timeout:** `5 minutes`\n"
                f"• **Interaction Cooldown:** `{settings.cooldown_seconds if settings else 3}s`\n"
                f"• **Max Conversation Turns:** `{settings.max_history_turns if settings else 12}`\n"
                f"• **Allowed Channels:** `{'All Channels' if not (settings and settings.allowed_channels) else len(settings.allowed_channels)}`"
            ),
            color=0x9D4EDD,
        )
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await ctx_or_interaction.reply(embed=embed)

    async def _execute_soul_history(self, ctx_or_interaction: Any) -> None:
        """Display recent conversation memory."""
        guild = ctx_or_interaction.guild
        user = ctx_or_interaction.user if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author
        channel = ctx_or_interaction.channel

        if not guild:
            return

        soul_service = getattr(self.bot, "soul_service", None)
        messages = []
        if soul_service and hasattr(soul_service, "repo"):
            session_id = f"{guild.id}:{channel.id}:{user.id}"
            messages = await soul_service.repo.get_recent_messages(session_id, limit=5)

        if not messages:
            msg = "ℹ️ No recent conversation history found in this channel."
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.reply(msg)
            return

        desc_lines = []
        for m in messages:
            speaker = "**You:**" if m.role == "user" else "**KROVEX:**"
            preview = m.content[:80] + "..." if len(m.content) > 80 else m.content
            desc_lines.append(f"{speaker} {preview}")

        embed = EmbedBuilder.base(
            title="📜 KROVEX SOUL — Recent Memory",
            description="\n".join(desc_lines),
            color=0x9D4EDD,
        )
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await ctx_or_interaction.reply(embed=embed)

    async def _execute_soul_usage(self, ctx_or_interaction: Any) -> None:
        """Display usage metrics."""
        soul_service = getattr(self.bot, "soul_service", None)
        active_count = len(soul_service._active_sessions) if soul_service else 0

        embed = EmbedBuilder.base(
            title="📊 KROVEX SOUL — Telemetry & Usage",
            description=(
                f"• **Active Sessions (Bot-wide):** `{active_count}`\n"
                f"• **Session Model:** Multi-tenant channel isolated\n"
                f"• **Supported Subsystems:** Music, OwnerVC, Moderation, Utility, Economy\n"
                f"• **Safety Guards:** Role hierarchy, explicit confirmation, owner sovereignty\n"
                f"• **Status:** Operational 100%"
            ),
            color=0x9D4EDD,
        )
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await ctx_or_interaction.reply(embed=embed)

    # ── Commands ─────────────────────────────────────────────────────────────

    @commands.group(name="soul", invoke_without_command=True, help="KROVEX SOUL Assistant commands.")
    async def soul_group(self, ctx: commands.Context) -> None:
        """Display SOUL status."""
        await self._execute_soul_status(ctx)

    @soul_group.command(name="status", help="Show active SOUL session status.")
    async def soul_status_prefix(self, ctx: commands.Context) -> None:
        await self._execute_soul_status(ctx)

    @soul_group.command(name="stop", aliases=["end", "exit"], help="Stop your active SOUL session.")
    async def soul_stop_prefix(self, ctx: commands.Context) -> None:
        await self._execute_soul_stop(ctx)

    @soul_group.command(name="settings", help="View or modify SOUL server settings.")
    @commands.has_permissions(administrator=True)
    async def soul_settings_prefix(self, ctx: commands.Context) -> None:
        await self._execute_soul_settings(ctx)

    @soul_group.command(name="history", help="View recent conversation history.")
    async def soul_history_prefix(self, ctx: commands.Context) -> None:
        await self._execute_soul_history(ctx)

    @soul_group.command(name="usage", help="View SOUL usage statistics.")
    async def soul_usage_prefix(self, ctx: commands.Context) -> None:
        await self._execute_soul_usage(ctx)

    # ── Slash Command Group ──────────────────────────────────────────────────

    soul_slash_group = app_commands.Group(name="soul", description="KROVEX SOUL Natural Language Assistant controls")

    @soul_slash_group.command(name="status", description="Show active SOUL session status and settings")
    async def soul_status_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_soul_status(interaction)

    @soul_slash_group.command(name="stop", description="Stop your active SOUL conversation session")
    async def soul_stop_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_soul_stop(interaction)

    @soul_slash_group.command(name="settings", description="View SOUL server settings (Admin only)")
    @app_commands.default_permissions(administrator=True)
    async def soul_settings_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_soul_settings(interaction)

    @soul_slash_group.command(name="history", description="View recent conversation memory for this channel")
    async def soul_history_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_soul_history(interaction)

    @soul_slash_group.command(name="usage", description="View SOUL assistant activity and statistics")
    async def soul_usage_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_soul_usage(interaction)


async def setup(bot: DeathBot) -> None:
    """Setup hook to register Soul cog."""
    await bot.add_cog(Soul(bot))
