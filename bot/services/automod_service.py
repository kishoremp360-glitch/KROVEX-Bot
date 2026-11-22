"""AutoMod service: on_message event listener and rule enforcement pipeline."""
from __future__ import annotations
import json
import re
import asyncio
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple
import discord
from discord.ext import commands
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

logger = get_logger("death_bot.automod")

# Common Discord invite pattern
INVITE_PATTERN = re.compile(r"discord(?:\.gg|app\.com/invite|\.com/invite)/[\w-]+", re.IGNORECASE)
# External URL pattern
URL_PATTERN = re.compile(r"https?://[\w\-\.]+\.[a-zA-Z]{2,}(?:/[^\s]*)?", re.IGNORECASE)


class AutoModService(commands.Cog):
    """Monitors messages and enforces automod rules."""

    def __init__(self, bot: "DeathBot") -> None:
        self.bot = bot
        # Flood tracking: guild_id -> user_id -> list of message timestamps
        self._flood_tracker: Dict[int, Dict[int, List[datetime]]] = defaultdict(lambda: defaultdict(list))

    async def _get_settings(self, guild_id: int) -> dict:
        row = await self.bot.db.fetchone(
            "SELECT * FROM automod_settings WHERE guild_id=?", (guild_id,)
        )
        if not row:
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO automod_settings (guild_id) VALUES (?)", (guild_id,)
            )
            row = await self.bot.db.fetchone(
                "SELECT * FROM automod_settings WHERE guild_id=?", (guild_id,)
            )
        return row or {}

    async def _log_violation(self, guild_id: int, user_id: int, rule_type: str,
                              matched: str, action: str, channel_id: int) -> None:
        await self.bot.db.execute(
            "INSERT INTO automod_violations (guild_id, user_id, rule_type, matched_content, action_taken, channel_id) VALUES (?,?,?,?,?,?)",
            (guild_id, user_id, rule_type, matched[:500], action, channel_id)
        )

    def _is_exempt(self, member: discord.Member, channel: discord.TextChannel,
                    exempt_roles: List[int], exempt_channels: List[int]) -> bool:
        if getattr(getattr(member, "guild", None), "owner_id", None) == member.id:
            return True
        raw_owners = getattr(getattr(self.bot, "config", None), "owner_ids", []) or []
        bot_owners = getattr(self.bot, "owner_ids", None) or []
        if member.id in raw_owners or str(member.id) in [str(x) for x in raw_owners] or member.id in bot_owners:
            return True
        if member.guild_permissions.administrator:
            return True
        if channel.id in exempt_channels:
            return True
        for role in getattr(member, "roles", []):
            if role.id in exempt_roles:
                return True
        return False

    async def _apply_action(self, message: discord.Message, action: str,
                             duration_seconds: int = 300, reason: str = "AutoMod") -> None:
        try:
            await message.delete()
        except Exception:
            pass

        # Check rolling 24h violation count for automated punishment ladder escalation
        recent_count = 0
        try:
            if hasattr(self.bot, "db") and self.bot.db:
                row = await self.bot.db.fetchone(
                    "SELECT COUNT(*) as cnt FROM automod_violations WHERE guild_id=? AND user_id=? AND timestamp > datetime('now', '-24 hours')",
                    (message.guild.id, message.author.id)
                )
                if row:
                    recent_count = row.get("cnt") or 0
        except Exception:
            pass

        # Automated Punishment Escalation Ladder:
        # 5+ infractions -> 1-hour timeout
        # 3-4 infractions -> 10-minute timeout
        # <3 infractions -> base action
        escalated_reason = None
        if recent_count >= 4:
            action = "timeout"
            duration_seconds = 3600
            escalated_reason = f"Automated Punishment Ladder (Infraction #{recent_count + 1} in 24h): {reason}"
        elif recent_count >= 2 and action != "timeout":
            action = "timeout"
            duration_seconds = 600
            escalated_reason = f"Automated Punishment Ladder (Infraction #{recent_count + 1} in 24h): {reason}"

        active_reason = escalated_reason or reason

        if action == "warn":
            try:
                await message.channel.send(
                    f"⚠️ {message.author.mention} your message was removed: **{active_reason}**",
                    delete_after=8
                )
            except Exception:
                pass
        elif action == "timeout":
            try:
                until = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
                await message.author.timeout(until, reason=f"AutoMod: {active_reason}")
                await message.channel.send(
                    f"🛑 {message.author.mention} has been placed in timeout for {max(1, duration_seconds // 60)}m: **{active_reason}**",
                    delete_after=10
                )
            except Exception:
                pass
        elif action == "dm":
            try:
                content = f"Your message in **{message.guild.name}** was removed: **{active_reason}**"
                queue_service = getattr(self.bot, "dm_queue_service", None)
                if queue_service:
                    await queue_service.enqueue(
                        recipient_id=message.author.id,
                        guild_id=message.guild.id,
                        message_type="automod",
                        content=content,
                        idempotency_key=f"automod:{message.guild.id}:{message.id}:{message.author.id}",
                    )
                else:
                    await message.author.send(content)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        if not isinstance(message.author, discord.Member):
            return

        guild_id = message.guild.id
        settings = await self._get_settings(guild_id)
        if not settings.get("enabled"):
            return

        try:
            exempt_roles = json.loads(settings.get("exempt_roles", "[]") or "[]")
            exempt_channels = json.loads(settings.get("exempt_channels", "[]") or "[]")
        except Exception:
            exempt_roles, exempt_channels = [], []

        if self._is_exempt(message.author, message.channel, exempt_roles, exempt_channels):
            return

        content = message.content
        channel_id = message.channel.id
        user_id = message.author.id

        # 1. Bad words filter
        if settings.get("bad_words_enabled"):
            try:
                bad_words = json.loads(settings.get("bad_words_list", "[]") or "[]")
                content_lower = content.lower()
                for word in bad_words:
                    if word.lower() in content_lower:
                        await self._apply_action(message, "warn", reason="Bad word filter")
                        await self._log_violation(guild_id, user_id, "bad_word", word, "warn+delete", channel_id)
                        return
            except Exception:
                pass

        # 2. Custom rules (regex/word/domain)
        custom_rules = await self.bot.db.fetchall(
            "SELECT * FROM automod_rules WHERE guild_id=? AND enabled=1", (guild_id,)
        )
        for rule in custom_rules:
            matched = False
            match_text = ""
            try:
                if rule["rule_type"] == "regex":
                    m = re.search(rule["pattern"], content, re.IGNORECASE)
                    if m:
                        matched = True
                        match_text = m.group(0)
                elif rule["rule_type"] == "word":
                    if rule["pattern"].lower() in content.lower():
                        matched = True
                        match_text = rule["pattern"]
                elif rule["rule_type"] == "domain":
                    if rule["pattern"].lower() in content.lower():
                        matched = True
                        match_text = rule["pattern"]
            except Exception:
                pass
            if matched:
                await self._apply_action(message, rule.get("action", "delete"),
                                          rule.get("duration_seconds", 300), reason=f"Rule: {rule['name']}")
                await self._log_violation(guild_id, user_id, f"rule:{rule['name']}", match_text, rule.get("action", "delete"), channel_id)
                return

        # 3. Invite filter
        if settings.get("invites_blocked"):
            if INVITE_PATTERN.search(content):
                await self._apply_action(message, "warn", reason="Discord invite links are not allowed")
                await self._log_violation(guild_id, user_id, "invite_link", content[:100], "warn+delete", channel_id)
                return

        # 4. Link filter
        if settings.get("links_blocked"):
            if URL_PATTERN.search(content):
                await self._apply_action(message, "warn", reason="External links are not allowed")
                await self._log_violation(guild_id, user_id, "external_link", content[:100], "warn+delete", channel_id)
                return

        # 5. Caps filter
        if settings.get("caps_enabled"):
            min_chars = settings.get("caps_min_chars", 10)
            caps_pct = settings.get("caps_percentage", 70)
            letters = [c for c in content if c.isalpha()]
            if len(letters) >= min_chars:
                upper_pct = sum(1 for c in letters if c.isupper()) / len(letters) * 100
                if upper_pct >= caps_pct:
                    await self._apply_action(message, "warn", reason="Excessive caps")
                    await self._log_violation(guild_id, user_id, "caps", content[:100], "warn+delete", channel_id)
                    return

        # 6. Emoji filter
        if settings.get("emojis_enabled"):
            emoji_limit = settings.get("emoji_limit", 8)
            emoji_count = len(re.findall(r"<a?:[^:]+:\d+>|[\U00010000-\U0010ffff]", content))
            if emoji_count > emoji_limit:
                await self._apply_action(message, "warn", reason=f"Too many emojis (max {emoji_limit})")
                await self._log_violation(guild_id, user_id, "emoji_spam", f"{emoji_count} emojis", "warn+delete", channel_id)
                return

        # 7. Mention filter
        mention_limit = settings.get("mention_limit", 5)
        if len(message.mentions) + len(message.role_mentions) > mention_limit:
            await self._apply_action(message, "timeout", 300, reason=f"Mass mention (>{mention_limit})")
            await self._log_violation(guild_id, user_id, "mass_mention", f"{len(message.mentions)} mentions", "timeout+delete", channel_id)
            return

        # 8. Flood filter
        flood_interval = settings.get("flood_interval_seconds", 1.0)
        self._flood_tracker[guild_id][user_id].append(datetime.now(timezone.utc))
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=flood_interval * 5)
        self._flood_tracker[guild_id][user_id] = [
            t for t in self._flood_tracker[guild_id][user_id] if t > cutoff
        ]
        if len(self._flood_tracker[guild_id][user_id]) > 5:
            await self._apply_action(message, "timeout", 60, reason="Message flooding")
            await self._log_violation(guild_id, user_id, "flood", "5+ msgs rapid", "timeout+delete", channel_id)
            self._flood_tracker[guild_id][user_id].clear()
            return


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(AutoModService(bot))
