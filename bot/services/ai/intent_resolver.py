"""KROVEX SOUL Natural Language Understanding & Intent Resolver.

Transforms natural conversational text into structured tool intents, handles
contextual follow-ups, extracts entities (members, numbers, duration, song names),
and manages action confirmation lifecycle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import discord

from bot.utils.logger import get_logger

logger = get_logger("death_bot.ai.intent_resolver")


@dataclass
class ResolvedIntent:
    """Structured representation of a user's natural language request."""
    intent_type: str  # "action", "conversation", "confirmation", "cancellation", "termination"
    tool_name: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    confirmation_response: Optional[bool] = None  # True for yes, False for no
    raw_text: str = ""
    clarification_question: Optional[str] = None


class IntentResolver:
    """Natural Language understanding engine for KROVEX SOUL."""

    def __init__(self) -> None:
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for high performance intent matching."""
        # Confirmation & Cancellation
        self.re_confirm_yes = re.compile(
            r"^(yes|yeah|yep|confirm|proceed|do it|sure|aama|ok|okay|continue|accept)\b",
            re.IGNORECASE,
        )
        self.re_confirm_no = re.compile(
            r"^(no|cancel|stop|abort|dont|don\'t|nevermind|vendam|leave it|wait)\b",
            re.IGNORECASE,
        )

        # Session Termination
        self.re_termination = re.compile(
            r"^(goodbye|bye|byee|tata|see you|cya|stop assistant|end session|exit session|close session|podhum da|podhum|gn|goodnight)\b",
            re.IGNORECASE,
        )

    # ── Entity Extraction Utilities ──────────────────────────────────────────

    def extract_member(self, text: str, guild: discord.Guild) -> Tuple[Optional[discord.Member], str]:
        """Extract a Discord member from text via mention (<@id>), user ID, or display name/name match."""
        # 1. Mention check: <@123456789> or <@!123456789>
        mention_match = re.search(r"<@!?([0-9]+)>", text)
        if mention_match:
            user_id = int(mention_match.group(1))
            member = guild.get_member(user_id)
            cleaned = text[:mention_match.start()] + text[mention_match.end():]
            return member, re.sub(r"\s+", " ", cleaned).strip()

        # 2. Raw user ID check (17-20 digits)
        id_match = re.search(r"\b([0-9]{17,20})\b", text)
        if id_match:
            user_id = int(id_match.group(1))
            member = guild.get_member(user_id)
            if member:
                cleaned = text[:id_match.start()] + text[id_match.end():]
                return member, re.sub(r"\s+", " ", cleaned).strip()

        # 3. Name or Display Name substring check (e.g. "Alex", "Kishore")
        words = text.split()
        for word in words:
            clean_word = re.sub(r"[^\w]", "", word).lower()
            if len(clean_word) >= 3:
                for m in guild.members:
                    if clean_word == m.name.lower() or (m.nick and clean_word == m.nick.lower()):
                        cleaned = re.sub(rf"\b{re.escape(word)}\b", "", text, count=1, flags=re.IGNORECASE)
                        return m, re.sub(r"\s+", " ", cleaned).strip()

        return None, text

    def extract_number(self, text: str, default: int = 1) -> Tuple[int, str]:
        """Extract an integer count from text (e.g. '10', '50 messages')."""
        match = re.search(r"\b([0-9]{1,4})\b", text)
        if match:
            num = int(match.group(1))
            cleaned = text[:match.start()] + text[match.end():]
            return num, re.sub(r"\s+", " ", cleaned).strip()
        return default, text

    def extract_duration(self, text: str, default: str = "10m") -> Tuple[str, str]:
        """Extract a timeout duration string like '10m', '1h', '2d', '30s'."""
        match = re.search(r"\b([0-9]+[smhd])\b", text, re.IGNORECASE)
        if match:
            dur = match.group(1).lower()
            cleaned = text[:match.start()] + text[match.end():]
            return dur, re.sub(r"\s+", " ", cleaned).strip()
        return default, text

    # ── Main Intent Resolution ───────────────────────────────────────────────

    def resolve(
        self,
        text: str,
        guild: discord.Guild,
        author: discord.Member,
        last_action: Optional[str] = None,
        last_target_member: Optional[discord.Member] = None,
        has_pending_confirmation: bool = False,
    ) -> ResolvedIntent:
        """Resolve raw natural language into a canonical SOUL intent."""
        cleaned = text.strip()
        lower = cleaned.lower()

        # 1. Pending Confirmation Handling
        if has_pending_confirmation:
            if self.re_confirm_yes.search(lower):
                return ResolvedIntent(intent_type="confirmation", confirmation_response=True, raw_text=cleaned)
            if self.re_confirm_no.search(lower):
                return ResolvedIntent(intent_type="cancellation", confirmation_response=False, raw_text=cleaned)

        # 2. Session Termination
        if self.re_termination.search(lower) and len(cleaned.split()) <= 4:
            return ResolvedIntent(intent_type="termination", raw_text=cleaned)

        # 3. Music Intents
        # A. Volume relative adjustments ("louder", "quieter", "make it louder")
        if re.search(r"\b(make it louder|turn it up|louder|volume up|sound up)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="music_volume", args={"level": 80}, raw_text=cleaned)
        if re.search(r"\b(make it quieter|turn it down|quieter|volume down|sound down)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="music_volume", args={"level": 30}, raw_text=cleaned)

        # Volume absolute
        vol_match = re.search(r"\bvolume (?:to )?([0-9]{1,3})\b", lower)
        if vol_match:
            vol = int(vol_match.group(1))
            return ResolvedIntent(intent_type="action", tool_name="music_volume", args={"level": vol}, raw_text=cleaned)

        # Skip
        if re.search(r"\b(skip this|skip song|skip track|next song|next track|\bskip\b)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="music_skip", raw_text=cleaned)

        # Pause
        if re.search(r"\b(pause music|pause song|pause playback|\bpause\b)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="music_pause", raw_text=cleaned)

        # Resume
        if re.search(r"\b(resume music|resume song|unpause|\bresume\b|continue playing)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="music_resume", raw_text=cleaned)

        # Stop
        if re.search(r"\b(stop music|stop playback|stop the song|clear queue)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="music_stop", raw_text=cleaned)

        # Now Playing
        if re.search(r"\b(now playing|current song|what song is this|which song is playing)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="music_nowplaying", raw_text=cleaned)

        # Queue
        if re.search(r"\b(show queue|music queue|what is in queue|view queue|\bqueue\b)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="music_queue", raw_text=cleaned)

        # Play / Search song
        play_match = re.search(r"^(?:play|put on|i want to hear|can you play|stream)\s+(.+)$", lower)
        if play_match:
            query = play_match.group(1).strip()
            # Clean filler phrases
            query = re.sub(r"^(song|track|music)\s+", "", query).strip()
            if query:
                return ResolvedIntent(intent_type="action", tool_name="music_play", args={"query": query}, raw_text=cleaned)

        # Contextual music follow-up ("play something similar", "play some anime music")
        if re.search(r"\bplay (something similar|more like this|anime music|lofi|phonk)\b", lower):
            theme = lower.replace("play", "").strip()
            return ResolvedIntent(intent_type="action", tool_name="music_play", args={"query": theme}, raw_text=cleaned)

        # 4. Voice Channel & OwnerVC Intents
        # Lock / Unlock
        if re.search(r"\b(lock room|lock voice|lock vc|lock this room|lock channel)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="voice_lock", raw_text=cleaned)
        if re.search(r"\b(unlock room|unlock voice|unlock vc|open room|open voice)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="voice_unlock", raw_text=cleaned)

        # Hide / Show
        if re.search(r"\b(hide room|hide voice|hide vc|ghost room)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="voice_hide", raw_text=cleaned)
        if re.search(r"\b(show room|show voice|show vc|unhide room|visible room)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="voice_show", raw_text=cleaned)

        # Capacity Limit
        limit_match = re.search(r"\b(?:set )?(?:vc |room |channel )?limit (?:to )?([0-9]{1,2})\b", lower)
        if limit_match:
            lim = int(limit_match.group(1))
            return ResolvedIntent(intent_type="action", tool_name="voice_limit", args={"limit": lim}, raw_text=cleaned)

        # Claim voice
        if re.search(r"\b(claim vc|claim room|claim voice|make me owner)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="voice_claim", raw_text=cleaned)

        # Voice disconnect/kick
        if re.search(r"\b(voice kick|disconnect member|disconnect user|remove from voice)\b", lower):
            target, _ = self.extract_member(cleaned, guild)
            target = target or last_target_member
            if target:
                return ResolvedIntent(intent_type="action", tool_name="voice_kick", args={"target": target}, raw_text=cleaned)
            return ResolvedIntent(intent_type="action", clarification_question="Which member should I disconnect from voice?", raw_text=cleaned)

        # 5. Moderation Intents
        # Kick
        if re.search(r"\b(kick member|kick user|\bkick\b)\b", lower) and not re.search(r"\b(voice kick|vc kick)\b", lower):
            target, rem = self.extract_member(cleaned, guild)
            target = target or last_target_member
            if target:
                reason = rem.replace("kick", "").strip() or "Kicked via SOUL Assistant"
                return ResolvedIntent(intent_type="action", tool_name="mod_kick", args={"target": target, "reason": reason}, raw_text=cleaned)
            return ResolvedIntent(intent_type="action", clarification_question="Which member would you like me to kick?", raw_text=cleaned)

        # Ban
        if re.search(r"\b(ban member|ban user|\bban\b)\b", lower) and not re.search(r"\b(unban|vc ban|voice ban)\b", lower):
            target, rem = self.extract_member(cleaned, guild)
            target = target or last_target_member
            if target:
                reason = rem.replace("ban", "").strip() or "Banned via SOUL Assistant"
                return ResolvedIntent(intent_type="action", tool_name="mod_ban", args={"target": target, "reason": reason}, raw_text=cleaned)
            return ResolvedIntent(intent_type="action", clarification_question="Which member would you like me to ban?", raw_text=cleaned)

        # Unban
        if re.search(r"\b(unban member|unban user|\bunban\b)\b", lower):
            id_match = re.search(r"\b([0-9]{17,20})\b", cleaned)
            if id_match:
                uid = int(id_match.group(1))
                return ResolvedIntent(intent_type="action", tool_name="mod_unban", args={"user_id": uid}, raw_text=cleaned)
            return ResolvedIntent(intent_type="action", clarification_question="Please provide the User ID of the member to unban.", raw_text=cleaned)

        # Timeout
        if re.search(r"\b(timeout member|timeout user|mute text|\btimeout\b)\b", lower):
            target, rem = self.extract_member(cleaned, guild)
            target = target or last_target_member
            duration, rem = self.extract_duration(rem, default="10m")
            if target:
                return ResolvedIntent(intent_type="action", tool_name="mod_timeout", args={"target": target, "duration": duration}, raw_text=cleaned)
            return ResolvedIntent(intent_type="action", clarification_question="Which member should I timeout, and for how long?", raw_text=cleaned)

        # Untimeout
        if re.search(r"\b(untimeout|remove timeout|unmute text)\b", lower):
            target, _ = self.extract_member(cleaned, guild)
            target = target or last_target_member
            if target:
                return ResolvedIntent(intent_type="action", tool_name="mod_untimeout", args={"target": target}, raw_text=cleaned)
            return ResolvedIntent(intent_type="action", clarification_question="Which member should I remove timeout from?", raw_text=cleaned)

        # Warn
        if re.search(r"\b(warn member|warn user|\bwarn\b)\b", lower) and not re.search(r"\b(warnings|clearwarns)\b", lower):
            target, rem = self.extract_member(cleaned, guild)
            target = target or last_target_member
            if target:
                reason = rem.replace("warn", "").strip() or "Warned via SOUL Assistant"
                return ResolvedIntent(intent_type="action", tool_name="mod_warn", args={"target": target, "reason": reason}, raw_text=cleaned)
            return ResolvedIntent(intent_type="action", clarification_question="Which member should I warn?", raw_text=cleaned)

        # Warnings / Check Warns
        if re.search(r"\b(warnings|check warns|show warns|view warnings)\b", lower):
            target, _ = self.extract_member(cleaned, guild)
            target = target or author
            return ResolvedIntent(intent_type="action", tool_name="mod_warnings", args={"target": target}, raw_text=cleaned)

        # Clear Warnings
        if re.search(r"\b(clear warns|clear warnings|reset warns)\b", lower):
            target, _ = self.extract_member(cleaned, guild)
            target = target or last_target_member
            if target:
                return ResolvedIntent(intent_type="action", tool_name="mod_clearwarns", args={"target": target}, raw_text=cleaned)
            return ResolvedIntent(intent_type="action", clarification_question="Whose warnings should I clear?", raw_text=cleaned)

        # Purge
        purge_match = re.search(r"\b(purge|clear messages|delete messages|clean chat)\b", lower)
        if purge_match:
            count, _ = self.extract_number(cleaned, default=10)
            target, _ = self.extract_member(cleaned, guild)
            return ResolvedIntent(intent_type="action", tool_name="mod_purge", args={"count": count, "target": target}, raw_text=cleaned)

        # Channel Lockdown / Unlock
        if re.search(r"\b(lock channel|lockdown channel|lock text)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="mod_lock", raw_text=cleaned)
        if re.search(r"\b(unlock channel|unlockdown channel|unlock text)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="mod_unlock", raw_text=cleaned)

        # Slowmode
        slow_match = re.search(r"\b(?:set )?slowmode (?:to )?([0-9]{1,4})\b", lower)
        if slow_match:
            sec = int(slow_match.group(1))
            return ResolvedIntent(intent_type="action", tool_name="mod_slowmode", args={"seconds": sec}, raw_text=cleaned)

        # 6. Server & Utility Intents
        # Server Info / Stats
        if re.search(r"\b(server stats|serverinfo|server statistics|about server|server details)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="util_serverinfo", raw_text=cleaned)

        # Member Count
        if re.search(r"\b(member count|membercount|how many members|server population)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="util_membercount", raw_text=cleaned)

        # Avatar / PFP
        if re.search(r"\b(avatar|pfp|profile pic|profile picture)\b", lower):
            target, _ = self.extract_member(cleaned, guild)
            target = target or author
            return ResolvedIntent(intent_type="action", tool_name="util_avatar", args={"target": target}, raw_text=cleaned)

        # User Info
        if re.search(r"\b(user info|who is|userinfo|profile of)\b", lower):
            target, _ = self.extract_member(cleaned, guild)
            target = target or author
            return ResolvedIntent(intent_type="action", tool_name="util_userinfo", args={"target": target}, raw_text=cleaned)

        # Ping / Latency
        if re.search(r"\b(ping|bot latency|connection speed)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="util_ping", raw_text=cleaned)

        # Uptime
        if re.search(r"\b(uptime|bot uptime|how long have you been online)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="util_uptime", raw_text=cleaned)

        # Economy Balance
        if re.search(r"\b(balance|my coins|wallet|bank balance|how much money)\b", lower):
            target, _ = self.extract_member(cleaned, guild)
            target = target or author
            return ResolvedIntent(intent_type="action", tool_name="eco_balance", args={"target": target}, raw_text=cleaned)

        # Daily Reward
        if re.search(r"\b(claim daily|daily reward|daily coins|daily bonus|\bdaily\b)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="eco_daily", raw_text=cleaned)

        # Level / Rank
        if re.search(r"\b(my rank|my level|what level am i|check rank|\brank\b)\b", lower):
            target, _ = self.extract_member(cleaned, guild)
            target = target or author
            return ResolvedIntent(intent_type="action", tool_name="level_rank", args={"target": target}, raw_text=cleaned)

        # Leaderboard
        if re.search(r"\b(leaderboard|top levels|top members|xp leaderboard)\b", lower):
            return ResolvedIntent(intent_type="action", tool_name="level_leaderboard", raw_text=cleaned)

        # 7. Fallback: Pure Conversation
        return ResolvedIntent(intent_type="conversation", raw_text=cleaned)
