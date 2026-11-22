"""Advanced AutoMod cog — 22 admin commands for filter management, rule CRUD, and violation logs."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder, COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING

if TYPE_CHECKING:
    from bot.core.bot import DeathBot

# ── helpers ──────────────────────────────────────────────────────────────────

BRAND = 0x9D4EDD

FILTER_COLUMNS = {
    "bad_words": "bad_words_enabled",
    "invites":   "invites_blocked",
    "links":     "links_blocked",
    "caps":      "caps_enabled",
    "emoji":     "emojis_enabled",
    "mentions":  "mention_limit",   # toggled differently — see _execute_toggle
    "flood":     "flood_enabled",
}

TOGGLE_MAP = {
    "filterbadwords":  "bad_words_enabled",
    "filterinvites":   "invites_blocked",
    "filterlinks":     "links_blocked",
    "filtercaps":      "caps_enabled",
    "filteremoji":     "emojis_enabled",
    "filtermentions":  "mentions_enabled",
    "filterflood":     "flood_enabled",
}

FILTER_LABELS = {
    "bad_words_enabled": "Bad Words",
    "invites_blocked":   "Discord Invites",
    "links_blocked":     "External Links",
    "caps_enabled":      "Caps Lock",
    "emojis_enabled":    "Emoji Spam",
    "mentions_enabled":  "Mass Mentions",
    "flood_enabled":     "Message Flood",
}


def _bool_icon(val: object) -> str:
    return "🟢" if val else "🔴"


async def _ensure_settings(bot: "DeathBot", guild_id: int) -> dict:
    row = await bot.db.fetchone(
        "SELECT * FROM automod_settings WHERE guild_id=?", (guild_id,)
    )
    if not row:
        await bot.db.execute(
            "INSERT OR IGNORE INTO automod_settings (guild_id) VALUES (?)", (guild_id,)
        )
        row = await bot.db.fetchone(
            "SELECT * FROM automod_settings WHERE guild_id=?", (guild_id,)
        )
    return row or {}


# ── cog ───────────────────────────────────────────────────────────────────────


class AutoMod(commands.GroupCog, group_name="automod", group_description="Advanced automated moderation and filters"):
    """Advanced automated moderation: filters, custom rules, violation logs."""

    def __init__(self, bot: "DeathBot") -> None:
        super().__init__()
        self.bot = bot

    # ══════════════════════════════════════════════════════════════════════════
    # 1. automod — full status overview
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_automod(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        await ctx.defer(ephemeral=False)
        s = await _ensure_settings(self.bot, ctx.guild.id)

        try:
            exempt_roles    = json.loads(s.get("exempt_roles", "[]") or "[]")
            exempt_channels = json.loads(s.get("exempt_channels", "[]") or "[]")
        except Exception:
            exempt_roles, exempt_channels = [], []

        global_state = _bool_icon(s.get("enabled"))
        embed = EmbedBuilder.base(
            title="🛡️ AutoMod Status",
            description=f"**Global AutoMod:** {global_state} {'Enabled' if s.get('enabled') else 'Disabled'}",
            color=BRAND,
            footer_text="Death Bot • AutoMod System",
        )

        # Filter states
        filters = (
            f"{_bool_icon(s.get('bad_words_enabled'))} **Bad Words** — "
            f"`{len(json.loads(s.get('bad_words_list','[]') or '[]'))} words`\n"
            f"{_bool_icon(s.get('invites_blocked'))} **Discord Invites**\n"
            f"{_bool_icon(s.get('links_blocked'))} **External Links**\n"
            f"{_bool_icon(s.get('caps_enabled'))} **Caps Lock** — `{s.get('caps_percentage', 70)}%` threshold\n"
            f"{_bool_icon(s.get('emojis_enabled'))} **Emoji Spam** — max `{s.get('emoji_limit', 8)}`\n"
            f"{_bool_icon(s.get('mentions_enabled'))} **Mass Mentions** — max `{s.get('mention_limit', 5)}`\n"
            f"{_bool_icon(s.get('flood_enabled'))} **Message Flood** — `{s.get('flood_messages', 5)}` msgs / "
            f"`{s.get('flood_interval_seconds', 5)}s`"
        )
        embed.add_field(name="Filters", value=filters, inline=False)

        # Exempt roles
        if exempt_roles:
            roles_str = " ".join(f"<@&{r}>" for r in exempt_roles[:10])
            embed.add_field(name="Exempt Roles", value=roles_str, inline=True)
        else:
            embed.add_field(name="Exempt Roles", value="None", inline=True)

        # Exempt channels
        if exempt_channels:
            chans_str = " ".join(f"<#{c}>" for c in exempt_channels[:10])
            embed.add_field(name="Exempt Channels", value=chans_str, inline=True)
        else:
            embed.add_field(name="Exempt Channels", value="None", inline=True)

        await ctx.reply(embed=embed)

    @commands.command(name="automod", help="Show full automod status.")
    @commands.has_permissions(administrator=True)
    async def automod_prefix(self, ctx: commands.Context) -> None:
        await self._execute_automod(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="status", description="Show full automod status embed.")
    @app_commands.default_permissions(administrator=True)
    async def automod_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_automod(UnifiedContext.from_interaction(interaction))

    # ══════════════════════════════════════════════════════════════════════════
    # 2. automodrules — list custom rules
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_automodrules(self, ctx: UnifiedContext, page: int = 1) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        await ctx.defer(ephemeral=False)
        rules = await self.bot.db.fetchall(
            "SELECT * FROM automod_rules WHERE guild_id=? ORDER BY id", (ctx.guild.id,)
        )
        if not rules:
            await ctx.send_info("No Rules", "No custom automod rules configured yet.")
            return

        per_page = 10
        pages = max(1, (len(rules) + per_page - 1) // per_page)
        page = max(1, min(page, pages))
        slice_ = rules[(page - 1) * per_page: page * per_page]

        embed = EmbedBuilder.base(
            title="📋 AutoMod Custom Rules",
            description=f"Page {page}/{pages} — {len(rules)} rule(s) total",
            color=BRAND,
            footer_text="Death Bot • AutoMod Rules",
        )
        for r in slice_:
            state = _bool_icon(r.get("enabled", 1))
            action = r.get("action", "delete")
            embed.add_field(
                name=f"`#{r['id']}` {state} {r['name']}",
                value=f"**Type:** `{r['rule_type']}` | **Action:** `{action}`\n**Pattern:** `{r['pattern'][:80]}`",
                inline=False,
            )
        await ctx.reply(embed=embed)

    @commands.command(name="automodrules", help="List all custom automod rules.")
    @commands.has_permissions(administrator=True)
    async def automodrules_prefix(self, ctx: commands.Context, page: int = 1) -> None:
        await self._execute_automodrules(UnifiedContext.from_prefix(ctx), page)

    @app_commands.command(name="rules", description="List all custom automod rules.")
    @app_commands.describe(page="Page number (default 1)")
    @app_commands.default_permissions(administrator=True)
    async def automodrules_slash(self, interaction: discord.Interaction, page: int = 1) -> None:
        await self._execute_automodrules(UnifiedContext.from_interaction(interaction), page)

    # ══════════════════════════════════════════════════════════════════════════
    # 3. automodstats — violation statistics
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_automodstats(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        await ctx.defer(ephemeral=False)
        gid = ctx.guild.id
        now = datetime.now(timezone.utc)

        total_all = (await self.bot.db.fetchone(
            "SELECT COUNT(*) as cnt FROM automod_violations WHERE guild_id=?", (gid,)
        ) or {}).get("cnt", 0)

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        total_today = (await self.bot.db.fetchone(
            "SELECT COUNT(*) as cnt FROM automod_violations WHERE guild_id=? AND timestamp>=?",
            (gid, today_start)
        ) or {}).get("cnt", 0)

        week_start = (now - timedelta(days=7)).isoformat()
        total_week = (await self.bot.db.fetchone(
            "SELECT COUNT(*) as cnt FROM automod_violations WHERE guild_id=? AND timestamp>=?",
            (gid, week_start)
        ) or {}).get("cnt", 0)

        top_types = await self.bot.db.fetchall(
            "SELECT rule_type, COUNT(*) as cnt FROM automod_violations WHERE guild_id=? "
            "GROUP BY rule_type ORDER BY cnt DESC LIMIT 5", (gid,)
        )
        top_users = await self.bot.db.fetchall(
            "SELECT user_id, COUNT(*) as cnt FROM automod_violations WHERE guild_id=? "
            "GROUP BY user_id ORDER BY cnt DESC LIMIT 5", (gid,)
        )

        embed = EmbedBuilder.base(
            title="📊 AutoMod Violation Statistics",
            color=BRAND,
            footer_text="Death Bot • AutoMod Stats",
        )
        embed.add_field(
            name="Violations",
            value=f"Today: **{total_today}** | Week: **{total_week}** | All-time: **{total_all}**",
            inline=False,
        )
        if top_types:
            types_str = "\n".join(f"`{r['rule_type']}` — **{r['cnt']}**" for r in top_types)
            embed.add_field(name="Top Rule Types", value=types_str, inline=True)
        if top_users:
            users_str = "\n".join(f"<@{r['user_id']}> — **{r['cnt']}**" for r in top_users)
            embed.add_field(name="Top Offenders", value=users_str, inline=True)

        await ctx.reply(embed=embed)

    @commands.command(name="automodstats", help="Show automod violation statistics.")
    @commands.has_permissions(administrator=True)
    async def automodstats_prefix(self, ctx: commands.Context) -> None:
        await self._execute_automodstats(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="stats", description="Show automod violation statistics.")
    @app_commands.default_permissions(administrator=True)
    async def automodstats_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_automodstats(UnifiedContext.from_interaction(interaction))

    # ══════════════════════════════════════════════════════════════════════════
    # Generic filter toggle helper
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_toggle(self, ctx: UnifiedContext, command_name: str, state: str) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        state = state.lower()
        if state not in ("enable", "disable"):
            await ctx.send_error("Invalid Argument", "Use `enable` or `disable`.")
            return
        col = TOGGLE_MAP.get(command_name)
        if not col:
            await ctx.send_error("Internal Error", "Unknown toggle column.")
            return
        enabled = 1 if state == "enable" else 0
        await _ensure_settings(self.bot, ctx.guild.id)
        await self.bot.db.execute(
            f"UPDATE automod_settings SET {col}=? WHERE guild_id=?",
            (enabled, ctx.guild.id)
        )
        label = FILTER_LABELS.get(col, col)
        icon = "🟢" if enabled else "🔴"
        await ctx.send_success(
            f"{icon} Filter {'Enabled' if enabled else 'Disabled'}",
            f"**{label}** filter is now **{'enabled' if enabled else 'disabled'}**."
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 4. filterbadwords
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="filterbadwords", help="Toggle bad word filter.")
    @commands.has_permissions(administrator=True)
    async def filterbadwords_prefix(self, ctx: commands.Context, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_prefix(ctx), "filterbadwords", state)

    @app_commands.command(name="filterbadwords", description="Toggle bad word filter.")
    @app_commands.describe(state="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def filterbadwords_slash(self, interaction: discord.Interaction, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_interaction(interaction), "filterbadwords", state)

    # ══════════════════════════════════════════════════════════════════════════
    # 5. filterinvites
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="filterinvites", help="Toggle Discord invite link blocking.")
    @commands.has_permissions(administrator=True)
    async def filterinvites_prefix(self, ctx: commands.Context, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_prefix(ctx), "filterinvites", state)

    @app_commands.command(name="filterinvites", description="Toggle Discord invite link blocking.")
    @app_commands.describe(state="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def filterinvites_slash(self, interaction: discord.Interaction, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_interaction(interaction), "filterinvites", state)

    # ══════════════════════════════════════════════════════════════════════════
    # 6. filterlinks
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="filterlinks", help="Toggle external link blocking.")
    @commands.has_permissions(administrator=True)
    async def filterlinks_prefix(self, ctx: commands.Context, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_prefix(ctx), "filterlinks", state)

    @app_commands.command(name="filterlinks", description="Toggle external link blocking.")
    @app_commands.describe(state="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def filterlinks_slash(self, interaction: discord.Interaction, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_interaction(interaction), "filterlinks", state)

    # ══════════════════════════════════════════════════════════════════════════
    # 7. filtercaps
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="filtercaps", help="Toggle caps lock filter.")
    @commands.has_permissions(administrator=True)
    async def filtercaps_prefix(self, ctx: commands.Context, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_prefix(ctx), "filtercaps", state)

    @app_commands.command(name="filtercaps", description="Toggle caps lock filter.")
    @app_commands.describe(state="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def filtercaps_slash(self, interaction: discord.Interaction, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_interaction(interaction), "filtercaps", state)

    # ══════════════════════════════════════════════════════════════════════════
    # 8. filteremoji
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="filteremoji", help="Toggle emoji spam filter.")
    @commands.has_permissions(administrator=True)
    async def filteremoji_prefix(self, ctx: commands.Context, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_prefix(ctx), "filteremoji", state)

    @app_commands.command(name="filteremoji", description="Toggle emoji spam filter.")
    @app_commands.describe(state="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def filteremoji_slash(self, interaction: discord.Interaction, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_interaction(interaction), "filteremoji", state)

    # ══════════════════════════════════════════════════════════════════════════
    # 9. filtermentions
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="filtermentions", help="Toggle mass mention filter.")
    @commands.has_permissions(administrator=True)
    async def filtermentions_prefix(self, ctx: commands.Context, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_prefix(ctx), "filtermentions", state)

    @app_commands.command(name="filtermentions", description="Toggle mass mention filter.")
    @app_commands.describe(state="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def filtermentions_slash(self, interaction: discord.Interaction, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_interaction(interaction), "filtermentions", state)

    # ══════════════════════════════════════════════════════════════════════════
    # 10. filterflood
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="filterflood", help="Toggle message flood filter.")
    @commands.has_permissions(administrator=True)
    async def filterflood_prefix(self, ctx: commands.Context, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_prefix(ctx), "filterflood", state)

    @app_commands.command(name="filterflood", description="Toggle message flood filter.")
    @app_commands.describe(state="enable or disable")
    @app_commands.default_permissions(administrator=True)
    async def filterflood_slash(self, interaction: discord.Interaction, state: str) -> None:
        await self._execute_toggle(UnifiedContext.from_interaction(interaction), "filterflood", state)

    # ══════════════════════════════════════════════════════════════════════════
    # 11. badwordsadd
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_badwordsadd(self, ctx: UnifiedContext, word: str) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        word = word.lower().strip()
        if not word:
            await ctx.send_error("Invalid Word", "Word cannot be empty.")
            return
        s = await _ensure_settings(self.bot, ctx.guild.id)
        try:
            bad_words: list = json.loads(s.get("bad_words_list", "[]") or "[]")
        except Exception:
            bad_words = []
        if word in bad_words:
            await ctx.send_error("Already Exists", f"`{word}` is already in the bad words list.")
            return
        bad_words.append(word)
        await self.bot.db.execute(
            "UPDATE automod_settings SET bad_words_list=? WHERE guild_id=?",
            (json.dumps(bad_words), ctx.guild.id)
        )
        await ctx.send_success("Word Added", f"Added `{word}` to the bad words list. ({len(bad_words)} total)")

    @commands.command(name="badwordsadd", help="Add a word to the bad words filter.")
    @commands.has_permissions(administrator=True)
    async def badwordsadd_prefix(self, ctx: commands.Context, *, word: str) -> None:
        await self._execute_badwordsadd(UnifiedContext.from_prefix(ctx), word)

    @app_commands.command(name="badwordsadd", description="Add a word/phrase to the bad words filter.")
    @app_commands.describe(word="Word or phrase to block")
    @app_commands.default_permissions(administrator=True)
    async def badwordsadd_slash(self, interaction: discord.Interaction, word: str) -> None:
        await self._execute_badwordsadd(UnifiedContext.from_interaction(interaction), word)

    # ══════════════════════════════════════════════════════════════════════════
    # 12. badwordsremove
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_badwordsremove(self, ctx: UnifiedContext, word: str) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        word = word.lower().strip()
        s = await _ensure_settings(self.bot, ctx.guild.id)
        try:
            bad_words: list = json.loads(s.get("bad_words_list", "[]") or "[]")
        except Exception:
            bad_words = []
        if word not in bad_words:
            await ctx.send_error("Not Found", f"`{word}` is not in the bad words list.")
            return
        bad_words.remove(word)
        await self.bot.db.execute(
            "UPDATE automod_settings SET bad_words_list=? WHERE guild_id=?",
            (json.dumps(bad_words), ctx.guild.id)
        )
        await ctx.send_success("Word Removed", f"Removed `{word}` from the bad words list. ({len(bad_words)} remaining)")

    @commands.command(name="badwordsremove", help="Remove a word from the bad words filter.")
    @commands.has_permissions(administrator=True)
    async def badwordsremove_prefix(self, ctx: commands.Context, *, word: str) -> None:
        await self._execute_badwordsremove(UnifiedContext.from_prefix(ctx), word)

    @app_commands.command(name="badwordsremove", description="Remove a word/phrase from the bad words filter.")
    @app_commands.describe(word="Word or phrase to remove")
    @app_commands.default_permissions(administrator=True)
    async def badwordsremove_slash(self, interaction: discord.Interaction, word: str) -> None:
        await self._execute_badwordsremove(UnifiedContext.from_interaction(interaction), word)

    # ══════════════════════════════════════════════════════════════════════════
    # 13. badwordslist
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_badwordslist(self, ctx: UnifiedContext) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        await ctx.defer(ephemeral=True)
        s = await _ensure_settings(self.bot, ctx.guild.id)
        try:
            bad_words: list = json.loads(s.get("bad_words_list", "[]") or "[]")
        except Exception:
            bad_words = []
        if not bad_words:
            await ctx.send_info("Bad Words List", "No bad words configured yet.")
            return
        # Show words as spoilers to avoid triggering filters
        spoilered = " ".join(f"||{w}||" for w in bad_words)
        embed = EmbedBuilder.base(
            title="🚫 Bad Words List",
            description=f"**{len(bad_words)} word(s)** filtered:\n\n{spoilered[:3000]}",
            color=BRAND,
            footer_text="Death Bot • Words shown as spoilers",
        )
        await ctx.reply(embed=embed, ephemeral=True)

    @commands.command(name="badwordslist", help="Show all filtered words (admin only).")
    @commands.has_permissions(administrator=True)
    async def badwordslist_prefix(self, ctx: commands.Context) -> None:
        await self._execute_badwordslist(UnifiedContext.from_prefix(ctx))

    @app_commands.command(name="badwordslist", description="Show all filtered words/phrases.")
    @app_commands.default_permissions(administrator=True)
    async def badwordslist_slash(self, interaction: discord.Interaction) -> None:
        await self._execute_badwordslist(UnifiedContext.from_interaction(interaction))

    # ══════════════════════════════════════════════════════════════════════════
    # 14. capslimit
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_capslimit(self, ctx: UnifiedContext, percentage: int) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not (50 <= percentage <= 100):
            await ctx.send_error("Out of Range", "Percentage must be between 50 and 100.")
            return
        await _ensure_settings(self.bot, ctx.guild.id)
        await self.bot.db.execute(
            "UPDATE automod_settings SET caps_percentage=? WHERE guild_id=?",
            (percentage, ctx.guild.id)
        )
        await ctx.send_success("Caps Limit Updated", f"Caps filter threshold set to **{percentage}%**.")

    @commands.command(name="capslimit", help="Set caps filter percentage threshold (50-100).")
    @commands.has_permissions(administrator=True)
    async def capslimit_prefix(self, ctx: commands.Context, percentage: int) -> None:
        await self._execute_capslimit(UnifiedContext.from_prefix(ctx), percentage)

    @app_commands.command(name="capslimit", description="Set caps filter percentage threshold (50-100%).")
    @app_commands.describe(percentage="Caps percentage threshold (50-100)")
    @app_commands.default_permissions(administrator=True)
    async def capslimit_slash(self, interaction: discord.Interaction, percentage: int) -> None:
        await self._execute_capslimit(UnifiedContext.from_interaction(interaction), percentage)

    # ══════════════════════════════════════════════════════════════════════════
    # 15. emojilimit
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_emojilimit(self, ctx: UnifiedContext, count: int) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not (1 <= count <= 50):
            await ctx.send_error("Out of Range", "Emoji limit must be between 1 and 50.")
            return
        await _ensure_settings(self.bot, ctx.guild.id)
        await self.bot.db.execute(
            "UPDATE automod_settings SET emoji_limit=? WHERE guild_id=?",
            (count, ctx.guild.id)
        )
        await ctx.send_success("Emoji Limit Updated", f"Emoji spam filter limit set to **{count}** emojis per message.")

    @commands.command(name="emojilimit", help="Set emoji limit per message (1-50).")
    @commands.has_permissions(administrator=True)
    async def emojilimit_prefix(self, ctx: commands.Context, count: int) -> None:
        await self._execute_emojilimit(UnifiedContext.from_prefix(ctx), count)

    @app_commands.command(name="emojilimit", description="Set emoji limit per message (1-50).")
    @app_commands.describe(count="Max emojis per message (1-50)")
    @app_commands.default_permissions(administrator=True)
    async def emojilimit_slash(self, interaction: discord.Interaction, count: int) -> None:
        await self._execute_emojilimit(UnifiedContext.from_interaction(interaction), count)

    # ══════════════════════════════════════════════════════════════════════════
    # 16. mentionlimit
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_mentionlimit(self, ctx: UnifiedContext, count: int) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if not (1 <= count <= 20):
            await ctx.send_error("Out of Range", "Mention limit must be between 1 and 20.")
            return
        await _ensure_settings(self.bot, ctx.guild.id)
        await self.bot.db.execute(
            "UPDATE automod_settings SET mention_limit=? WHERE guild_id=?",
            (count, ctx.guild.id)
        )
        await ctx.send_success("Mention Limit Updated", f"Mass mention threshold set to **{count}** mentions per message.")

    @commands.command(name="mentionlimit", help="Set max mentions per message (1-20).")
    @commands.has_permissions(administrator=True)
    async def mentionlimit_prefix(self, ctx: commands.Context, count: int) -> None:
        await self._execute_mentionlimit(UnifiedContext.from_prefix(ctx), count)

    @app_commands.command(name="mentionlimit", description="Set max mentions per message (1-20).")
    @app_commands.describe(count="Max mentions per message (1-20)")
    @app_commands.default_permissions(administrator=True)
    async def mentionlimit_slash(self, interaction: discord.Interaction, count: int) -> None:
        await self._execute_mentionlimit(UnifiedContext.from_interaction(interaction), count)

    # ══════════════════════════════════════════════════════════════════════════
    # 17. floodlimit
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_floodlimit(self, ctx: UnifiedContext, messages: int, seconds: int) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        if messages < 2 or messages > 30:
            await ctx.send_error("Out of Range", "Message count must be between 2 and 30.")
            return
        if seconds < 1 or seconds > 60:
            await ctx.send_error("Out of Range", "Seconds must be between 1 and 60.")
            return
        await _ensure_settings(self.bot, ctx.guild.id)
        await self.bot.db.execute(
            "UPDATE automod_settings SET flood_messages=?, flood_interval_seconds=? WHERE guild_id=?",
            (messages, seconds, ctx.guild.id)
        )
        await ctx.send_success(
            "Flood Limit Updated",
            f"Flood filter set to **{messages} messages** per **{seconds} seconds**."
        )

    @commands.command(name="floodlimit", help="Set flood threshold: max N messages in X seconds.")
    @commands.has_permissions(administrator=True)
    async def floodlimit_prefix(self, ctx: commands.Context, messages: int, seconds: int) -> None:
        await self._execute_floodlimit(UnifiedContext.from_prefix(ctx), messages, seconds)

    @app_commands.command(name="floodlimit", description="Set flood threshold: max N messages in X seconds.")
    @app_commands.describe(messages="Max messages in the window", seconds="Time window in seconds")
    @app_commands.default_permissions(administrator=True)
    async def floodlimit_slash(self, interaction: discord.Interaction, messages: int, seconds: int) -> None:
        await self._execute_floodlimit(UnifiedContext.from_interaction(interaction), messages, seconds)

    # ══════════════════════════════════════════════════════════════════════════
    # 18. automodruleadd
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_automodruleadd(self, ctx: UnifiedContext, name: str, rule_type: str,
                                       pattern: str, action: str = "delete") -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        rule_type = rule_type.lower()
        action = action.lower()
        if rule_type not in ("regex", "word", "domain"):
            await ctx.send_error("Invalid Type", "Rule type must be `regex`, `word`, or `domain`.")
            return
        if action not in ("delete", "warn", "timeout"):
            await ctx.send_error("Invalid Action", "Action must be `delete`, `warn`, or `timeout`.")
            return
        # Validate regex
        if rule_type == "regex":
            try:
                re.compile(pattern)
            except re.error as e:
                await ctx.send_error("Invalid Regex", f"Pattern is not valid regex: `{e}`")
                return
        await self.bot.db.execute(
            "INSERT INTO automod_rules (guild_id, name, rule_type, pattern, action) VALUES (?,?,?,?,?)",
            (ctx.guild.id, name, rule_type, pattern, action)
        )
        await ctx.send_success(
            "Rule Added",
            f"Created `{rule_type}` rule **{name}**\nPattern: `{pattern[:100]}`\nAction: `{action}`"
        )

    @commands.command(name="automodruleadd", help="Add a custom automod rule.")
    @commands.has_permissions(administrator=True)
    async def automodruleadd_prefix(self, ctx: commands.Context, name: str, rule_type: str,
                                     pattern: str, action: str = "delete") -> None:
        await self._execute_automodruleadd(UnifiedContext.from_prefix(ctx), name, rule_type, pattern, action)

    @app_commands.command(name="ruleadd", description="Add a custom automod rule.")
    @app_commands.describe(
        name="Rule name", rule_type="Type: regex, word, domain",
        pattern="Pattern to match", action="Action: delete, warn, timeout"
    )
    @app_commands.default_permissions(administrator=True)
    async def automodruleadd_slash(self, interaction: discord.Interaction, name: str,
                                    rule_type: str, pattern: str, action: str = "delete") -> None:
        await self._execute_automodruleadd(UnifiedContext.from_interaction(interaction), name, rule_type, pattern, action)

    # ══════════════════════════════════════════════════════════════════════════
    # 19. automodruleremove
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_automodruleremove(self, ctx: UnifiedContext, rule_id: int) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        row = await self.bot.db.fetchone(
            "SELECT * FROM automod_rules WHERE id=? AND guild_id=?", (rule_id, ctx.guild.id)
        )
        if not row:
            await ctx.send_error("Not Found", f"No rule found with ID `{rule_id}`.")
            return
        await self.bot.db.execute("DELETE FROM automod_rules WHERE id=?", (rule_id,))
        await ctx.send_success("Rule Removed", f"Deleted rule **{row['name']}** (`#{rule_id}`).")

    @commands.command(name="automodruleremove", help="Remove a custom automod rule by ID.")
    @commands.has_permissions(administrator=True)
    async def automodruleremove_prefix(self, ctx: commands.Context, rule_id: int) -> None:
        await self._execute_automodruleremove(UnifiedContext.from_prefix(ctx), rule_id)

    @app_commands.command(name="ruleremove", description="Remove a custom automod rule by ID.")
    @app_commands.describe(rule_id="Rule ID to remove")
    @app_commands.default_permissions(administrator=True)
    async def automodruleremove_slash(self, interaction: discord.Interaction, rule_id: int) -> None:
        await self._execute_automodruleremove(UnifiedContext.from_interaction(interaction), rule_id)

    # ══════════════════════════════════════════════════════════════════════════
    # 20. automodruleedit
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_automodruleedit(self, ctx: UnifiedContext, rule_id: int,
                                        field: str, value: str) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        field = field.lower()
        allowed = {"pattern", "action", "enabled"}
        if field not in allowed:
            await ctx.send_error("Invalid Field", f"Field must be one of: {', '.join(f'`{f}`' for f in allowed)}")
            return
        row = await self.bot.db.fetchone(
            "SELECT * FROM automod_rules WHERE id=? AND guild_id=?", (rule_id, ctx.guild.id)
        )
        if not row:
            await ctx.send_error("Not Found", f"No rule found with ID `{rule_id}`.")
            return
        # Coerce
        if field == "enabled":
            db_val: object = 1 if value.lower() in ("1", "true", "yes", "enable") else 0
        elif field == "action":
            if value.lower() not in ("delete", "warn", "timeout"):
                await ctx.send_error("Invalid Action", "Action must be `delete`, `warn`, or `timeout`.")
                return
            db_val = value.lower()
        else:
            if row.get("rule_type") == "regex":
                try:
                    re.compile(value)
                except re.error as e:
                    await ctx.send_error("Invalid Regex", str(e))
                    return
            db_val = value

        await self.bot.db.execute(
            f"UPDATE automod_rules SET {field}=? WHERE id=?", (db_val, rule_id)
        )
        await ctx.send_success("Rule Updated", f"Rule `#{rule_id}` → `{field}` set to `{db_val}`.")

    @commands.command(name="automodruleedit", help="Edit a custom rule field (pattern, action, enabled).")
    @commands.has_permissions(administrator=True)
    async def automodruleedit_prefix(self, ctx: commands.Context, rule_id: int, field: str, *, value: str) -> None:
        await self._execute_automodruleedit(UnifiedContext.from_prefix(ctx), rule_id, field, value)

    @app_commands.command(name="ruleedit", description="Edit a custom rule field.")
    @app_commands.describe(rule_id="Rule ID", field="Field: pattern, action, enabled", value="New value")
    @app_commands.default_permissions(administrator=True)
    async def automodruleedit_slash(self, interaction: discord.Interaction,
                                     rule_id: int, field: str, value: str) -> None:
        await self._execute_automodruleedit(UnifiedContext.from_interaction(interaction), rule_id, field, value)

    # ══════════════════════════════════════════════════════════════════════════
    # 21. automodexempt
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_automodexempt(self, ctx: UnifiedContext, operation: str,
                                      target: str) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        operation = operation.lower()
        if operation not in ("add", "remove"):
            await ctx.send_error("Invalid Operation", "Use `add` or `remove`.")
            return
        s = await _ensure_settings(self.bot, ctx.guild.id)
        try:
            exempt_roles: list    = json.loads(s.get("exempt_roles", "[]") or "[]")
            exempt_channels: list = json.loads(s.get("exempt_channels", "[]") or "[]")
        except Exception:
            exempt_roles, exempt_channels = [], []

        # Resolve the target
        target_id: Optional[int] = None
        kind: Optional[str] = None
        # Try to parse as ID or mention
        raw_id = target.strip("<>#@&!")
        if raw_id.isdigit():
            tid = int(raw_id)
            # Check role
            role = ctx.guild.get_role(tid)
            if role:
                target_id = tid
                kind = "role"
            else:
                # Check channel
                chan = ctx.guild.get_channel(tid)
                if chan:
                    target_id = tid
                    kind = "channel"
        if target_id is None:
            # Try name match
            name_lower = target.lower().lstrip("#@")
            for r in ctx.guild.roles:
                if r.name.lower() == name_lower:
                    target_id = r.id
                    kind = "role"
                    break
            if target_id is None:
                for ch in ctx.guild.text_channels:
                    if ch.name.lower() == name_lower:
                        target_id = ch.id
                        kind = "channel"
                        break

        if target_id is None:
            await ctx.send_error("Not Found", f"Could not resolve `{target}` to a role or channel.")
            return

        if kind == "role":
            if operation == "add":
                if target_id not in exempt_roles:
                    exempt_roles.append(target_id)
            else:
                exempt_roles = [r for r in exempt_roles if r != target_id]
            await self.bot.db.execute(
                "UPDATE automod_settings SET exempt_roles=? WHERE guild_id=?",
                (json.dumps(exempt_roles), ctx.guild.id)
            )
            label = f"<@&{target_id}>"
        else:
            if operation == "add":
                if target_id not in exempt_channels:
                    exempt_channels.append(target_id)
            else:
                exempt_channels = [c for c in exempt_channels if c != target_id]
            await self.bot.db.execute(
                "UPDATE automod_settings SET exempt_channels=? WHERE guild_id=?",
                (json.dumps(exempt_channels), ctx.guild.id)
            )
            label = f"<#{target_id}>"

        verb = "Added" if operation == "add" else "Removed"
        await ctx.send_success(
            f"Exemption {verb}",
            f"{label} has been {'added to' if operation == 'add' else 'removed from'} AutoMod exemptions."
        )

    @commands.command(name="automodexempt", help="Add/remove a role or channel from automod exemptions.")
    @commands.has_permissions(administrator=True)
    async def automodexempt_prefix(self, ctx: commands.Context, operation: str, *, target: str) -> None:
        await self._execute_automodexempt(UnifiedContext.from_prefix(ctx), operation, target)

    @app_commands.command(name="exempt", description="Add/remove a role or channel from automod exemptions.")
    @app_commands.describe(operation="add or remove", target="Role or channel (name, ID, or mention)")
    @app_commands.default_permissions(administrator=True)
    async def automodexempt_slash(self, interaction: discord.Interaction,
                                   operation: str, target: str) -> None:
        await self._execute_automodexempt(UnifiedContext.from_interaction(interaction), operation, target)

    # ══════════════════════════════════════════════════════════════════════════
    # 22. automodlogs
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_automodlogs(self, ctx: UnifiedContext, limit: int = 10) -> None:
        if not ctx.guild:
            await ctx.send_error("Server Only", "This command can only be used in a server.")
            return
        await ctx.defer(ephemeral=False)
        limit = max(1, min(limit, 25))
        rows = await self.bot.db.fetchall(
            "SELECT * FROM automod_violations WHERE guild_id=? ORDER BY timestamp DESC LIMIT ?",
            (ctx.guild.id, limit)
        )
        if not rows:
            await ctx.send_info("No Violations", "No automod violations logged yet.")
            return
        embed = EmbedBuilder.base(
            title=f"📜 AutoMod Violation Log (last {len(rows)})",
            color=BRAND,
            footer_text="Death Bot • AutoMod Logs",
        )
        for row in rows:
            ts = row.get("timestamp", "")
            user_mention = f"<@{row['user_id']}>"
            embed.add_field(
                name=f"`#{row['id']}` {row['rule_type']} — {row['action_taken']}",
                value=f"**User:** {user_mention}\n**Matched:** `{str(row.get('matched_content',''))[:60]}`\n**When:** {ts}",
                inline=False,
            )
        await ctx.reply(embed=embed)

    @commands.command(name="automodlogs", help="Show last N automod violations (default 10, max 25).")
    @commands.has_permissions(administrator=True)
    async def automodlogs_prefix(self, ctx: commands.Context, limit: int = 10) -> None:
        await self._execute_automodlogs(UnifiedContext.from_prefix(ctx), limit)

    @app_commands.command(name="logs", description="Show last N automod violations (default 10, max 25).")
    @app_commands.describe(limit="Number of recent violations to show (1-25)")
    @app_commands.default_permissions(administrator=True)
    async def automodlogs_slash(self, interaction: discord.Interaction, limit: int = 10) -> None:
        await self._execute_automodlogs(UnifiedContext.from_interaction(interaction), limit)


# ── setup ─────────────────────────────────────────────────────────────────────


async def setup(bot: "DeathBot") -> None:
    await bot.add_cog(AutoMod(bot))
