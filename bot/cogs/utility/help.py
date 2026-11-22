"""Interactive KROVEX help and command documentation engine."""

from __future__ import annotations

import difflib
import math
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Set

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.context import UnifiedContext
from bot.utils.embeds import EmbedBuilder
from bot.utils.emojis import KrovexEmoji
from bot.utils.permissions import get_krovex_invite_url

if TYPE_CHECKING:
    from bot.core.bot import DeathBot


BRAND_COLOR = 0x9D4EDD  # Neon Purple
DIVIDER = "──────────────────────────────────────────────"

CATEGORY_METADATA: Dict[str, Tuple[str, str, str]] = {
    "Security": (KrovexEmoji.SECURITY.discord_format, "Security & Anti-Nuke", "Emergency lockdown, anti-raid, panic switch"),
    "AutoMod": (KrovexEmoji.SECURITY.discord_format, "Automated Moderation", "Regex filters, spam limits, invite shields"),
    "OwnerVC": (KrovexEmoji.BLUE_BUTTERFLIES.discord_format, "Owner VC Controls", "Voice channel lock, kick, move, mute, bitrate"),
    "Administration": (KrovexEmoji.ADMIN.discord_format, "Server Administration", "Channels, roles, slowmode, verification"),
    "Moderation": (KrovexEmoji.MODERATION.discord_format, "Staff Moderation", "Ban, kick, mute, timeout, warn, purge"),
    "ReactionRoles": ("🎭", "Reaction & Button Roles", "Role menus, button assignment, persistence"),
    "Logging": (KrovexEmoji.CHECK_BW.discord_format, "Audit & Event Logging", "Audit channels, event toggles, history records"),
    "TicketsCog": (KrovexEmoji.TICKET.discord_format, "Support Tickets", "Multi-panel tickets, claiming, transcripts"),
    "Leveling": (KrovexEmoji.LEADERBOARD.discord_format, "XP & Leveling System", "XP curve, leaderboards, rank cards, role rewards"),
    "LevelingCog": (KrovexEmoji.LEADERBOARD.discord_format, "XP & Leveling System", "XP curve, leaderboards, rank cards, role rewards"),
    "EconomyCog": (KrovexEmoji.ECONOMY.discord_format, "Virtual Economy", "Wallet, bank, daily, work, robbery, coinflip"),
    "ShopCog": (KrovexEmoji.KITTY_MUFFIN.discord_format, "Server Shop & Items", "Custom role items, inventory, trade, refunds"),
    "Minigames": ("🎮", "Interactive Minigames", "Trivia, RPS, Blackjack, slots, roll"),
    "MinigamesCog": ("🎮", "Interactive Minigames", "Trivia, RPS, Blackjack, slots, roll"),
    "Music": (KrovexEmoji.MUSIC.discord_format, "High-Fidelity Music", "24-bit audio, DJ system, queue, filters"),
    "Music System": (KrovexEmoji.MUSIC.discord_format, "High-Fidelity Music", "24-bit audio, DJ system, queue, filters"),
    "Voice": ("🔊", "Dynamic Voice Channels", "Temp voice creation, channel naming, limit"),
    "Voice System": ("🔊", "Dynamic Voice Channels", "Temp voice creation, channel naming, limit"),
    "Welcome": (KrovexEmoji.WELCOME.discord_format, "Welcome & Farewell", "Join cards, DM greeters, autoroles"),
    "Utility": ("🧰", "General Utilities", "Ping, stats, afk, avatar, reminder, info"),
    "Social": (KrovexEmoji.SOCIAL.discord_format, "Social & Profiles", "Bio, badges, rep, user banners"),
    "Social & Economy": (KrovexEmoji.SOCIAL.discord_format, "Social & Profiles", "Bio, badges, rep, user banners"),
    "Fun": (KrovexEmoji.FUN.discord_format, "Fun & Entertainment", "Memes, quotes, 8ball, coin flip, roast"),
    "Fun & Entertainment": (KrovexEmoji.FUN.discord_format, "Fun & Entertainment", "Memes, quotes, 8ball, coin flip, roast"),
    "ServerAdmin": (KrovexEmoji.ADMIN.discord_format, "Server Administration", "Channels, roles, slowmode, verification"),
    "SecurityPanel": (KrovexEmoji.SECURITY.discord_format, "Security Management Panel", "Quick security configurations and anti-nuke toggles"),
    "SetupWizard": (KrovexEmoji.ROCKET.discord_format, "Setup Wizards", "Interactive server configuration wizards"),
    "System": (KrovexEmoji.LIGHTNING.discord_format, "System & Diagnostic", "Bot process metrics, memory, database stats"),
    "System & Utility": (KrovexEmoji.LIGHTNING.discord_format, "System & Diagnostic", "Bot process metrics, memory, database stats"),
    "Mimic": ("🎭", "Mimic Persona System", "Per-server bot nickname and custom appearance"),
    "Anime & Social Interactions": (KrovexEmoji.CHERRY_SPIN.discord_format, "Anime & Social Interactions", "Hugs, kisses, anime GIFs, shipping, reactions, AniList search"),
    "Ratings & Fun": ("🎯", "Ratings & Fun Meters", "Gaymeter, lovemeter, IQ test, roasts, fun rates"),
    "Mention Notifications": ("🔔", "Real-Time Mentions", "Direct message mention alerts and DM notifications"),
    "Owner Dashboard": (KrovexEmoji.ADMIN.discord_format, "Owner Controls & Sovereign Governance", "Sovereign server control panel, staff directory, bulk toggles"),
    "VCDashboard": (KrovexEmoji.BLUE_BUTTERFLIES.discord_format, "Voice Channel Control Panels", "Interactive VC staff and owner control stations"),
    "Soul": (KrovexEmoji.CUTE_STAR_STATIC.discord_format, "SOUL Conversational Intelligence", "Conversational friend companion, natural replies, session diagnostics"),
    "vault": ("🏛️", "KROVEX Vault DR", "Automated database backups, encryption, and recovery"),
    "Help": ("📖", "Help & Documentation", "Explore commands, syntax, and categories"),
    "BotRoleService": (KrovexEmoji.ADMIN.discord_format, "Bot Role Management", "Top-of-hierarchy dedicated security roles"),
    "DMQueueService": ("📬", "DM Queue System", "Rate-limited direct message delivery"),
}

KNOWN_SLASH_EQUIVALENTS: Dict[str, str] = {
    # Logging & Audit
    "autolog": "/logs autolog",
    "log manual config": "/logs channel",
    "log reset": "/logs reset",
    "log disable": "/logs disable",
    "log enable": "/logs enable",
    "logging setup": "/logs autolog or /logs channel",
    "logging config": "/logs logstatus",
    "logging reset": "/logs reset",
    "logging enable": "/logs enable",
    "logchannel": "/logs channel",
    "logstatus": "/logs logstatus",
    "logclear": "/logs logclear",
    "logtoggle": "/logs logtoggle",
    "setuplogging": "/setup logging",
    # Mimic & Admin
    "mimic": "/admin mimic",
    "mimic nick": "/admin mimic",
    "mimic avatar": "/admin mimic",
    "mimic preview": "/admin mimic",
    "mimic reset": "/admin mimic",
    "setupbotroles": "/admin botroles",
    "krovexroles": "/admin botroles",
    "botroles": "/admin botroles",
    "slowmode": "/admin slowmode",
    "sm": "/admin slowmode",
    "setprefix": "/admin prefix",
    # Universal Top-Level Root Shortcuts
    "play": "/play",
    "pause": "/pause",
    "skip": "/skip",
    "stop": "/stop",
    "queue": "/queue",
    "ping": "/ping",
    "latency": "/ping",
    "avatar": "/avatar",
    "av": "/avatar",
    "pfp": "/avatar",
    "userinfo": "/userinfo",
    "whois": "/userinfo",
    "ui": "/userinfo",
    "serverinfo": "/serverinfo",
    "guildinfo": "/serverinfo",
    "si": "/serverinfo",
    "help": "/help",
    # Music & Playlist Groups
    "search": "/music search",
    "resume": "/music resume",
    "forceskip": "/music forceskip",
    "previous": "/music previous",
    "disconnect": "/music disconnect",
    "join": "/music join",
    "nowplaying": "/music nowplaying",
    "volume": "/music volume",
    "clear": "/music clear",
    "remove": "/music remove",
    "shuffle": "/music shuffle",
    "loop": "/music loop",
    "skipto": "/music skipto",
    "autoplay": "/music autoplay",
    "247": "/music 247",
    "lyrics": "/music lyrics",
    "djrole": "/music djrole",
    "voteskipsettings": "/music voteskipsettings",
    "musicstatus": "/music musicstatus",
    "musicsettings": "/music musicsettings",
    "8d": "/music filter 8d",
    "bassboost": "/music filter bass",
    "nightcore": "/music filter nightcore",
    "vaporwave": "/music filter vaporwave",
    "resetfilters": "/music filter clear",
    "playlistcreate": "/playlist create",
    "playlistadd": "/playlist add",
    "playlistplay": "/playlist play",
    "playlists": "/playlist list",
    "playlistlist": "/playlist list",
    "playlistdelete": "/playlist delete",
    # Utility Group
    "banner": "/util banner",
    "botinfo": "/util botinfo",
    "channelinfo": "/util channelinfo",
    "emojiinfo": "/util emojiinfo",
    "health": "/util health",
    "invite": "/util invite",
    "membercount": "/util membercount",
    "permissions": "/util permissions",
    "perms": "/util permissions",
    "prefix": "/util prefix",
    "profile": "/util profile",
    "roleinfo": "/util roleinfo",
    "support": "/util support",
    "uptime": "/util uptime",
    # Economy & Minigames
    "daily": "/eco daily",
    "pay": "/eco pay",
    "transfer": "/eco pay",
    "balance": "/eco balance",
    "bal": "/eco balance",
    "wallet": "/eco balance",
    "economytop": "/eco top",
    "richest": "/eco top",
    "8ball": "/game 8ball",
    "eightball": "/game 8ball",
    "ask": "/game 8ball",
    "coinflip": "/game coinflip",
    "flip": "/game coinflip",
    "coin": "/game coinflip",
    "roll": "/game roll",
    "dice": "/game roll",
    # Social & Anime Interactions
    "ship": "/interact ship",
    "shipp": "/interact ship",
    "love": "/interact ship",
    "lovemeter": "/interact ship",
    "couple": "/interact couple",
    "anime": "/interact anime",
    "mydog": "/interact mydog",
    "boy": "/interact boy",
    "hug": "/interact hug",
    "kiss": "/interact kiss",
    "cuddle": "/interact cuddle",
    "pat": "/interact pat",
    "pats": "/interact pat",
    "slap": "/interact slap",
    "roast": "/interact roast",
    "punch": "/interact punch",
    "bite": "/interact bite",
    "boop": "/interact boop",
    "bonk": "/interact bonk",
    "bully": "/interact bully",
    "greet": "/interact greet",
    "handholding": "/interact handholding",
    "handhold": "/interact handholding",
    "hold": "/interact handholding",
    "kill": "/interact knockout",
    "lick": "/interact lick",
    "nom": "/interact nom",
    "poke": "/interact poke",
    "highfive": "/interact highfive",
    "tickle": "/interact tickle",
    "stare": "/interact stare",
    "cheer": "/react cheer",
    "fuck": "/react outburst",
    "lewd": "/react fluster",
    "blush": "/react blush",
    "cry": "/react cry",
    "dance": "/react dance",
    "deredere": "/react deredere",
    "grin": "/react grin",
    "happy": "/react happy",
    "pout": "/react pout",
    "sleepy": "/react sleepy",
    "smile": "/react smile",
    "smug": "/react smug",
    "scoff": "/react scoff",
    "teehee": "/react teehee",
    "thinking": "/react thinking",
    "thumbs": "/react thumbs",
    "thumbsup": "/react thumbs",
    "triggered": "/react triggered",
    "wag": "/react wag",
    "wave": "/react wave",
    # Ratings & Fun Meters
    "gay": "/rate rainbow",
    "howgay": "/rate rainbow",
    "gaymeter": "/rate rainbow",
    "lesbian": "/rate harmony",
    "cute": "/rate cute",
    "howhot": "/rate howhot",
    "horny": "/rate mischief",
    "tharki": "/rate flirt",
    "dumb": "/rate dumb",
    "simprate": "/rate simprate",
    "toxic": "/rate toxic",
    "brainrate": "/rate brainrate",
    "chutiya": "/rate goofy",
    "intelligence": "/rate iq",
    "iq": "/rate iq",
    "genius": "/rate iq",
    "autorelationship": "/rate autorelationship",
    # Voice & Security Panels
    "vcdashboard": "/vc dashboard",
    "vcp": "/vc dashboard",
    "vcpanel": "/vc dashboard",
    "voicestats": "/vc stats",
    "voiceinfo": "/vc stats",
    "voicestat": "/vc stats",
    "voicetime": "/vc time",
    "vctime": "/vc time",
    "securitypanel": "/security panel",
    "secpanel": "/security panel",
    "mentionnotifs": "/security mentions",
    "mentions": "/security mentions",
    "mentionnotify": "/security mentions",
    # Tickets
    "ticketclose": "/ticket close",
    "ticketpanel": "/ticket panel",
    "ticketadd": "/ticket add",
    "ticketremove": "/ticket remove",
}

COMMAND_PERMISSIONS_MAP: Dict[str, str] = {
    "autolog": "Administrator",
    "mimic": "Administrator",
    "mimic nick": "Administrator",
    "mimic avatar": "Administrator",
    "mimic preview": "Administrator",
    "mimic reset": "Administrator",
    "log": "Administrator",
    "log manual config": "Administrator",
    "log reset": "Administrator",
    "log disable": "Administrator",
    "log enable": "Administrator",
    "logging": "Administrator",
    "logging setup": "Administrator",
    "logging config": "Administrator",
    "logging reset": "Administrator",
    "logging enable": "Administrator",
    "logchannel": "Administrator",
    "logstatus": "Administrator",
    "logclear": "Administrator",
    "logtoggle": "Administrator",
    "logignorechannel": "Administrator",
    "logignorerole": "Administrator",
    "logfilter": "Administrator",
    "loghistory": "Administrator",
    "logtest": "Administrator",
    "logmsgdelete": "Administrator",
    "logmsgedit": "Administrator",
    "logbulkdelete": "Administrator",
    "logmemberjoin": "Administrator",
    "logmemberleave": "Administrator",
    "logvoice": "Administrator",
    "logroles": "Administrator",
    "logchannels": "Administrator",
    "logserver": "Administrator",
    "setprefix": "Administrator",
}


def _get_category_meta(cog_name: str) -> Tuple[str, str, str]:
    """Retrieve emoji, display label, and description for cog."""
    return CATEGORY_METADATA.get(cog_name, ("📦", cog_name, f"Commands in {cog_name} module"))


def _flatten_cog_commands(cog: commands.Cog) -> List[Tuple[str, commands.Command]]:
    """Flatten prefix commands and subcommands in a cog with priority sorting."""
    groups: List[Tuple[str, commands.Command]] = []
    singles: List[Tuple[str, commands.Command]] = []

    priority_map = {"setup": 0, "config": 1, "reset": 2, "enable": 3}

    for cmd in cog.get_commands():
        if cmd.hidden:
            continue
        if isinstance(cmd, commands.Group):
            # Sort group subcommands with priority order
            sorted_subs = sorted(cmd.commands, key=lambda x: priority_map.get(x.name, 99))
            for sub in sorted_subs:
                if not sub.hidden:
                    groups.append((sub.qualified_name, sub))
        else:
            singles.append((cmd.qualified_name, cmd))

    return groups + singles


def _extract_command_permissions(cmd: commands.Command) -> str:
    """Inspect real command checks and runtime authorization logic. Never guess."""
    # 1. Check commands checks closures
    for check in getattr(cmd, "checks", []):
        qualname = getattr(check, "__qualname__", "")
        name = getattr(check, "__name__", "")
        if "is_owner" in qualname or "is_owner" in name:
            return "Bot Owner Only"

        # Check for has_permissions closure
        closure = getattr(check, "__closure__", None)
        if closure:
            for cell in closure:
                val = getattr(cell, "cell_contents", None)
                if isinstance(val, dict):
                    req_perms = [k.replace("_", " ").title() for k, v in val.items() if v is True]
                    if req_perms:
                        return ", ".join(req_perms)

    # 2. Check static mapping
    if cmd.qualified_name.lower() in COMMAND_PERMISSIONS_MAP:
        return COMMAND_PERMISSIONS_MAP[cmd.qualified_name.lower()]

    # 3. Default for unprivileged commands
    return "Standard Member (None Required)"


def _extract_command_cooldown(cmd: commands.Command) -> str:
    """Extract runtime cooldown information from command bucket."""
    buckets = getattr(cmd, "_buckets", None)
    if buckets:
        cd = getattr(buckets, "_cooldown", None)
        if cd and getattr(cd, "per", 0) > 0:
            rate = getattr(cd, "rate", 1)
            per = getattr(cd, "per", 0)
            btype = getattr(getattr(cd, "type", None), "name", "User").title()
            return f"{rate} use(s) every {per:g}s ({btype})"

    cd = getattr(cmd, "cooldown", None)
    if cd and getattr(cd, "per", 0) > 0:
        rate = getattr(cd, "rate", 1)
        per = getattr(cd, "per", 0)
        btype = getattr(getattr(cd, "type", None), "name", "User").title()
        return f"{rate} use(s) every {per:g}s ({btype})"

    return "*None (No active cooldown)*"


def _extract_slash_permissions(slash_cmd: Any) -> str:
    """Extract permissions required by Slash command from default_permissions."""
    perms = getattr(slash_cmd, "default_permissions", None)
    if not perms:
        return "Standard Member (None Required)"

    active_perms = []
    if getattr(perms, "administrator", False):
        return "Administrator"
    if getattr(perms, "manage_guild", False):
        active_perms.append("Manage Server")
    if getattr(perms, "manage_roles", False):
        active_perms.append("Manage Roles")
    if getattr(perms, "manage_channels", False):
        active_perms.append("Manage Channels")
    if getattr(perms, "ban_members", False):
        active_perms.append("Ban Members")
    if getattr(perms, "kick_members", False):
        active_perms.append("Kick Members")
    if getattr(perms, "manage_messages", False):
        active_perms.append("Manage Messages")

    if active_perms:
        return ", ".join(active_perms)
    return "Privileged / Configured Roles"


def _walk_slash_commands(tree_commands: List[Any], parent_path: str = "") -> List[Tuple[str, Any]]:
    """Walk Slash CommandTree recursively returning (full_path, cmd_obj)."""
    results: List[Tuple[str, Any]] = []
    for item in tree_commands:
        item_name = getattr(item, "name", "")
        full_path = f"{parent_path} {item_name}".strip()
        is_group = hasattr(item, "commands") and bool(getattr(item, "commands"))

        if is_group:
            results.extend(_walk_slash_commands(item.commands, full_path))
        else:
            results.append((full_path, item))
    return results


def _find_slash_command(bot: DeathBot, query: str) -> Optional[Tuple[str, Any]]:
    """Find a Slash command in tree matching full path or subcommand name."""
    clean = query.strip().lower().lstrip("/")
    all_slash = _walk_slash_commands(bot.tree.get_commands())

    # 1. Exact full path match
    for path, cmd in all_slash:
        if path.lower() == clean:
            return path, cmd

    # 2. Exact leaf name match
    for path, cmd in all_slash:
        if path.split()[-1].lower() == clean:
            return path, cmd

    return None


def _search_commands(bot: DeathBot, query: str) -> List[Dict[str, Any]]:
    """Unified search across Prefix commands, aliases, and Slash tree."""
    clean = query.strip().lower()
    results: List[Dict[str, Any]] = []
    seen_keys: Set[str] = set()

    # 1. Search Prefix Commands & Aliases
    for cmd in bot.walk_commands():
        if cmd.hidden:
            continue
        qname = cmd.qualified_name.lower()
        aliases = [a.lower() for a in cmd.aliases]
        help_text = (cmd.help or cmd.description or "").lower()
        cog_name = cmd.cog.qualified_name if cmd.cog else "Utility"

        score = 0
        if qname == clean:
            score = 100
        elif clean in aliases:
            score = 90
        elif qname.startswith(clean):
            score = 70
        elif clean in qname:
            score = 50
        elif any(clean in a for a in aliases):
            score = 45
        elif clean in help_text:
            score = 30
        elif clean in cog_name.lower():
            score = 25

        if score > 0:
            key = f"prefix:{cmd.qualified_name}"
            if key not in seen_keys:
                seen_keys.add(key)
                slash_equiv = KNOWN_SLASH_EQUIVALENTS.get(qname, f"/{cmd.qualified_name}")
                results.append({
                    "score": score,
                    "type": "prefix",
                    "name": cmd.qualified_name,
                    "signature": cmd.signature,
                    "description": cmd.help or "No description provided.",
                    "aliases": list(cmd.aliases),
                    "category": cog_name,
                    "slash_equiv": slash_equiv,
                    "permissions": _extract_command_permissions(cmd),
                    "cooldown": _extract_command_cooldown(cmd),
                })

    # 2. Search Slash Commands
    all_slash = _walk_slash_commands(bot.tree.get_commands())
    for path, sc in all_slash:
        p_lower = path.lower()
        leaf = p_lower.split()[-1]
        desc = getattr(sc, "description", "").lower()

        score = 0
        if p_lower == clean or leaf == clean:
            score = 95
        elif p_lower.startswith(clean) or leaf.startswith(clean):
            score = 65
        elif clean in p_lower:
            score = 45
        elif clean in desc:
            score = 25

        if score > 0:
            key = f"slash:{path}"
            if key not in seen_keys:
                seen_keys.add(key)
                results.append({
                    "score": score,
                    "type": "slash",
                    "name": f"/{path}",
                    "signature": "",
                    "description": getattr(sc, "description", "") or "No description provided.",
                    "aliases": [],
                    "category": path.split()[0].title(),
                    "slash_equiv": f"/{path}",
                    "permissions": _extract_slash_permissions(sc),
                    "cooldown": "*Standard*",
                })

    # Sort descending by score, then name
    results.sort(key=lambda x: (-x["score"], x["name"]))
    return results


class CommandSearchModal(discord.ui.Modal, title="🔍 Search KROVEX Commands"):
    """Modal dialog allowing users to enter search queries."""

    query_input = discord.ui.TextInput(
        label="Command, Keyword, or Category",
        placeholder="e.g. prefix, bass, daily, autolog, mute...",
        min_length=1,
        max_length=60,
        required=True,
    )

    def __init__(self, help_view: "KrovexHelpView") -> None:
        super().__init__()
        self.help_view = help_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.help_view.perform_search(interaction, self.query_input.value.strip())


class CategorySelect(discord.ui.Select):
    """Dropdown component for browsing command categories with pagination."""

    def __init__(self, view: "KrovexHelpView") -> None:
        self.help_view = view
        eligible_cogs = view.get_eligible_cogs()
        start_idx = (view.category_page - 1) * view.categories_per_page
        end_idx = start_idx + view.categories_per_page
        page_cogs = eligible_cogs[start_idx:end_idx]

        options: List[discord.SelectOption] = []
        for cog_name, cog in page_cogs:
            cmds = [c for c in cog.get_commands() if not c.hidden]
            icon, label, desc = _get_category_meta(cog_name)
            short_desc = (desc[:85] + "...") if len(desc) > 88 else desc
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=cog_name,
                    description=f"{short_desc} ({len(cmds)} cmds)"[:100],
                    emoji=icon,
                )
            )

        if not options:
            options = [discord.SelectOption(label="No categories on this page", value="none", emoji="ℹ️")]

        super().__init__(
            placeholder="Browse premium command categories",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="death_bot:help:category_select",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self.values or self.values[0] == "none":
            await interaction.response.defer()
            return
        selected_cog = self.values[0]
        self.help_view.is_search_mode = False
        self.help_view.search_query = None
        self.help_view.search_results = []
        self.help_view.current_category = selected_cog
        self.help_view.current_page = 1
        embed = self.help_view.build_category_embed(selected_cog, page=1)
        self.help_view._render_components()
        await interaction.response.edit_message(embed=embed, view=self.help_view)


class KrovexHelpView(discord.ui.View):
    """Interactive KROVEX UI View with category pagination, command browsing, and modal search."""

    def __init__(
        self,
        bot: DeathBot,
        author: discord.User | discord.Member,
        prefix: str,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.author = author
        self.prefix = prefix
        self.current_category: Optional[str] = None
        self.current_page: int = 1
        self.total_pages: int = 1
        self.category_page: int = 1
        self.categories_per_page: int = 10
        self.is_search_mode: bool = False
        self.search_query: Optional[str] = None
        self.search_results: List[Dict[str, Any]] = []
        self.message: Optional[discord.Message] = None

        self._init_buttons()
        self._render_components()

    def get_eligible_cogs(self) -> List[Tuple[str, commands.Cog]]:
        """Retrieve sorted list of active cogs filtered for authorization."""
        is_owner = False
        guild = getattr(self.author, "guild", None)
        if guild and self.author.id == guild.owner_id:
            is_owner = True
        elif hasattr(self.bot, "config") and self.author.id in getattr(self.bot.config, "owner_ids", []):
            is_owner = True

        eligible: List[Tuple[str, commands.Cog]] = []
        for cog_name, cog in sorted(self.bot.cogs.items(), key=lambda x: x[0]):
            if cog_name == "Owner Dashboard" and not is_owner:
                continue
            cmds = [c for c in cog.get_commands() if not c.hidden]
            if not cmds:
                continue
            eligible.append((cog_name, cog))
        return eligible

    @property
    def total_category_pages(self) -> int:
        cogs = self.get_eligible_cogs()
        return max(1, math.ceil(len(cogs) / self.categories_per_page))

    def _init_buttons(self) -> None:
        """Instantiate UI buttons for category and command browsing."""
        # 1. Category Navigation (Home Mode)
        self.prev_cat_button = discord.ui.Button(
            label="→ Previous Categories",
            style=discord.ButtonStyle.secondary,
            custom_id="death_bot:help:prev_cat",
            row=1,
        )
        self.prev_cat_button.callback = self._on_prev_cat

        self.cat_page_button = discord.ui.Button(
            label=f"Category Page {self.category_page}/{self.total_category_pages}",
            style=discord.ButtonStyle.secondary,
            emoji="📑",
            disabled=True,
            custom_id="death_bot:help:cat_page_indicator",
            row=1,
        )

        self.next_cat_button = discord.ui.Button(
            label="Next Categories",
            emoji=KrovexEmoji.PURPLE_ARROW.partial,
            style=discord.ButtonStyle.secondary,
            custom_id="death_bot:help:next",
            row=1,
        )
        self.next_cat_button.callback = self._on_next_cat

        # 2. Command / Search Navigation (Category / Search Mode)
        self.home_button = discord.ui.Button(
            label="← Main Library",
            emoji="🏠",
            style=discord.ButtonStyle.primary,
            custom_id="death_bot:help:home",
            row=1,
        )
        self.home_button.callback = self._on_home

        self.prev_button = discord.ui.Button(
            label="◀ Previous",
            style=discord.ButtonStyle.secondary,
            custom_id="death_bot:help:prev",
            row=1,
        )
        self.prev_button.callback = self._on_prev_cmd

        self.cmd_page_button = discord.ui.Button(
            label=f"Page {self.current_page}/{self.total_pages}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            custom_id="death_bot:help:cmd_page_indicator",
            row=1,
        )

        self.next_button = discord.ui.Button(
            label="Next",
            emoji=KrovexEmoji.PURPLE_ARROW.partial,
            style=discord.ButtonStyle.secondary,
            custom_id="death_bot:help:next_cmd",
            row=1,
        )
        self.next_button.callback = self._on_next_cmd

        # 3. Universal Action Buttons
        self.search_button = discord.ui.Button(
            label="🔍 Search",
            style=discord.ButtonStyle.secondary,
            custom_id="death_bot:help:search",
            row=1,
        )
        self.search_button.callback = self._on_search

        self.close_button = discord.ui.Button(
            label="Close",
            emoji=KrovexEmoji.CROSS.partial,
            style=discord.ButtonStyle.danger,
            custom_id="death_bot:help:close",
            row=1,
        )
        self.close_button.callback = self._on_close

    def _render_components(self) -> None:
        """Synchronize button states and render active row components."""
        self.clear_items()
        self.select_menu = CategorySelect(self)
        self.add_item(self.select_menu)

        if self.current_category or self.is_search_mode:
            # Active Category or Search results mode
            self.home_button.disabled = False
            self.prev_button.disabled = self.current_page <= 1
            self.cmd_page_button.label = f"Page {self.current_page}/{self.total_pages}"
            self.next_button.disabled = self.current_page >= self.total_pages

            self.add_item(self.home_button)
            self.add_item(self.prev_button)
            self.add_item(self.cmd_page_button)
            self.add_item(self.next_button)
            self.add_item(self.close_button)
        else:
            # Main Library Home mode (Category Navigation)
            self.prev_cat_button.disabled = self.category_page <= 1
            self.cat_page_button.label = f"Category Page {self.category_page}/{self.total_category_pages}"
            self.next_cat_button.disabled = self.category_page >= self.total_category_pages

            # Maintain legacy button disabled attributes for regression tests
            self.home_button.disabled = True
            self.prev_button.disabled = True
            self.next_button.disabled = True

            self.add_item(self.prev_cat_button)
            self.add_item(self.cat_page_button)
            self.add_item(self.next_cat_button)
            self.add_item(self.search_button)
            self.add_item(self.close_button)

    def update_button_states(self) -> None:
        """Public alias for refreshing component states."""
        self._render_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "⚠️ This help menu was opened by another user. Run `,help` or `/help` to open your own.",
                ephemeral=True,
            )
            return False
        return True

    async def _on_prev_cat(self, interaction: discord.Interaction) -> None:
        if self.category_page > 1:
            self.category_page -= 1
        embed = self.build_home_embed()
        self._render_components()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_next_cat(self, interaction: discord.Interaction) -> None:
        if self.category_page < self.total_category_pages:
            self.category_page += 1
        embed = self.build_home_embed()
        self._render_components()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_home(self, interaction: discord.Interaction) -> None:
        self.current_category = None
        self.is_search_mode = False
        self.search_query = None
        self.search_results = []
        self.current_page = 1
        embed = self.build_home_embed()
        self._render_components()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_prev_cmd(self, interaction: discord.Interaction) -> None:
        if self.current_page > 1:
            self.current_page -= 1
        if self.is_search_mode and self.search_query:
            embed = self.build_search_embed(self.search_query, page=self.current_page)
        elif self.current_category:
            embed = self.build_category_embed(self.current_category, page=self.current_page)
        else:
            embed = self.build_home_embed()
        self._render_components()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_next_cmd(self, interaction: discord.Interaction) -> None:
        if self.current_page < self.total_pages:
            self.current_page += 1
        if self.is_search_mode and self.search_query:
            embed = self.build_search_embed(self.search_query, page=self.current_page)
        elif self.current_category:
            embed = self.build_category_embed(self.current_category, page=self.current_page)
        else:
            embed = self.build_home_embed()
        self._render_components()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_search(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CommandSearchModal(self))

    async def _on_close(self, interaction: discord.Interaction) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    def build_home_embed(self) -> discord.Embed:
        """Build premium KROVEX command library home embed matching Zerina layout."""
        # 1. Dynamically calculate command statistics
        all_prefix = list(self.bot.walk_commands())
        unhidden_prefix = [c for c in all_prefix if not c.hidden]
        prefix_subcommands = [c for c in unhidden_prefix if c.parent is not None]

        all_slash = _walk_slash_commands(self.bot.tree.get_commands())
        slash_subcommands = [c for p, c in all_slash if ' ' in p]

        total_subcommands = len(prefix_subcommands) + len(slash_subcommands)
        total_command_entries = len(unhidden_prefix) + len(all_slash)

        # 2. Server Plan status check (Strictly real data)
        guild = getattr(self.author, "guild", None)
        if not guild:
            plan_status = "Unavailable"
            plan_intro = "Server plan information is not available in direct messages."
            plan_action = "Run this command inside a server to inspect guild subscription status."
        else:
            is_prem = False
            if hasattr(self.bot, "config") and getattr(self.bot.config, "is_premium", None):
                is_prem = True
            elif hasattr(guild, "id") and hasattr(self.bot, "config") and guild.id in getattr(self.bot.config, "premium_guild_ids", []):
                is_prem = True

            if is_prem:
                plan_status = "Premium"
                plan_intro = "Premium is active for this server. Browse the complete command library, including premium-only features."
                plan_action = "All high-fidelity audio, Sovereign controls, and advanced security engines are unlocked."
            else:
                plan_status = "Free"
                plan_intro = "Browse the complete command library, including premium and community features."
                plan_action = "Create a premium plan to unlock all commands and features.\nTo Get started, visit our website and sign up for a plan."

        # 3. Formulate Links from real config
        app_id = (
            getattr(self.bot.config, "client_id", None)
            or getattr(self.bot.config, "application_id", None)
            or (self.bot.user.id if getattr(self.bot, "user", None) else None)
            or getattr(self.bot, "application_id", None)
            or 1570428426974662718
        )
        invite_url = get_krovex_invite_url(int(app_id))

        links_parts = []
        links_parts.append(f"[Invite Me]({invite_url})")

        support_url = (
            getattr(self.bot.config, "support_server_url", None)
            or getattr(self.bot.config, "support_url", None)
            or "https://discord.gg/89tXm2ZEqR"
        )
        links_parts.append(f"[Support Server]({support_url})")

        website_url = getattr(self.bot.config, "website_url", None) or "https://krovex.bot"
        links_parts.append(f"[Website]({website_url})")

        links_str = " | ".join(links_parts)

        # 4. Description matching exact Zerina Reference hierarchy
        description_lines = [
            f"> **Welcome {self.author.mention}** — {plan_intro} Select a category to browse available commands, then run `{self.prefix}help <command>` for usage, arguments, and detailed guidance.",
            "",
            f"▎ **Plan: {plan_status}**",
            f"**{plan_action}**",
            f"**Prefix Entries (including subcommands):** `{len(unhidden_prefix)}`",
            f"**Slash Entries (including subcommands):** `{len(all_slash)}`",
            f"**Subcommands:** `{total_subcommands}`",
            f"**Total Command Entries:** `{total_command_entries}`",
            "",
            f"Select a category below to browse commands and their descriptions. For step-by-step details, run `{self.prefix}help <command>` ; use the category selector to switch sections and the navigation buttons to move through longer lists.",
            "",
            f"▎ {links_str}",
        ]

        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        latency_val = getattr(self.bot, "latency", None)
        latency_ms = round(latency_val * 1000) if (latency_val is not None and not math.isnan(latency_val)) else 0

        embed = discord.Embed(
            title="**KROVEX** • Premium Command Library",
            description="\n".join(description_lines),
            color=BRAND_COLOR,
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        # Overview field ensuring regression compatibility with test assertions
        active_cogs = self.get_eligible_cogs()
        root_prefix = len([c for c in self.bot.commands if not c.hidden])
        stats_text = (
            f"• **Prefix Commands:** `{root_prefix}` active\n"
            f"• **Slash Leaves:** `{len(all_slash)}` registered\n"
            f"• **Active Modules:** `{len(active_cogs)}` loaded\n"
            f"• **Gateway Latency:** `{latency_ms}ms`"
        )
        embed.add_field(name=f"{KrovexEmoji.LIGHTNING} System Intelligence", value=stats_text, inline=False)

        # Overview fields grouping key categories (Paginated per category page)
        start_idx = (self.category_page - 1) * self.categories_per_page
        end_idx = start_idx + self.categories_per_page
        page_cogs = active_cogs[start_idx:end_idx]

        categories_display: List[str] = []
        for cog_name, cog in page_cogs:
            cmds = [c for c in cog.get_commands() if not c.hidden]
            if not cmds:
                continue
            icon, label, _ = _get_category_meta(cog_name)
            categories_display.append(f"{icon} **{label}** `({len(cmds)})`")

        half = math.ceil(len(categories_display) / 2)
        col1 = "\n".join(categories_display[:half])
        col2 = "\n".join(categories_display[half:])
        if col1:
            embed.add_field(
                name=f"📦 Available Sections (Page {self.category_page}/{self.total_category_pages})",
                value=col1,
                inline=True,
            )
        if col2:
            embed.add_field(name="✨ More Modules", value=col2, inline=True)

        author_name = getattr(self.author, "display_name", str(self.author))
        author_avatar = getattr(getattr(self.author, "display_avatar", None), "url", None)
        embed.set_footer(
            text=f"Requested by {author_name} • Use {self.prefix}help <command> for syntax",
            icon_url=author_avatar,
        )
        return embed

    def build_category_embed(self, cog_name: str, page: int = 1) -> discord.Embed:
        """Build paginated category command list embed."""
        cog = self.bot.cogs.get(cog_name)
        if not cog:
            for cname, c in self.bot.cogs.items():
                if cname.lower() == cog_name.lower() or cog_name.lower() in cname.lower():
                    cog = c
                    cog_name = cname
                    break
        if not cog:
            return EmbedBuilder.error("Error", f"Category `{cog_name}` is not loaded.")

        icon, label, desc = _get_category_meta(cog_name)
        flat_commands = _flatten_cog_commands(cog)
        total_cmds = len(flat_commands)

        per_page = 8
        self.total_pages = max(1, math.ceil(total_cmds / per_page))
        self.current_page = max(1, min(page, self.total_pages))

        start_idx = (self.current_page - 1) * per_page
        end_idx = start_idx + per_page
        page_commands = flat_commands[start_idx:end_idx]

        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        embed = discord.Embed(
            title=f"**KROVEX** • {icon} {label}",
            description=(
                f"{DIVIDER}\n"
                f"*{desc}*\n\n"
                f"**Total Commands in this Module:** `{total_cmds}`\n"
                f"Use `{self.prefix}help <command>` for detailed syntax, permissions, and arguments.\n"
                f"{DIVIDER}"
            ),
            color=BRAND_COLOR,
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        for qname, cmd in page_commands:
            help_text = cmd.help or cmd.description or "No description available."
            slash_fmt = KNOWN_SLASH_EQUIVALENTS.get(qname.lower(), f"/{qname}")
            sig = f" {cmd.signature}" if cmd.signature else ""
            perms = _extract_command_permissions(cmd)
            alias_str = f"\n• **Aliases:** `{'`, `'.join(cmd.aliases)}`" if cmd.aliases else ""
            embed.add_field(
                name=f"`{self.prefix}{qname}{sig}`",
                value=f"• **Info:** {help_text}\n• **Slash:** `{slash_fmt}`\n• **Access:** `{perms}`{alias_str}",
                inline=False,
            )

        author_name = getattr(self.author, "display_name", str(self.author))
        embed.set_footer(
            text=f"Page {self.current_page} of {self.total_pages} • {label} • Requested by {author_name}"
        )
        return embed

    def build_search_embed(self, query: str, page: int = 1) -> discord.Embed:
        """Build paginated search results embed."""
        total_matches = len(self.search_results)
        per_page = 6
        self.total_pages = max(1, math.ceil(total_matches / per_page))
        self.current_page = max(1, min(page, self.total_pages))

        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        embed = discord.Embed(
            title=f"**KROVEX** • Command Search: `{query}`",
            description=(
                f"{DIVIDER}\n"
                f"Found **{total_matches}** command match(es) for query: **`{query}`**\n"
                f"Use `{self.prefix}help <command>` for full argument breakdowns.\n"
                f"{DIVIDER}"
            ),
            color=BRAND_COLOR,
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        if total_matches == 0:
            embed.description = (
                f"{DIVIDER}\n"
                f"❌ No commands, aliases, or categories found matching **`{query}`**.\n\n"
                f"**Tips:**\n"
                f"• Check for typos or use fewer keywords (e.g. `pay`, `ban`, `bass`).\n"
                f"• Browse the full category catalog from the dropdown below.\n"
                f"{DIVIDER}"
            )
            embed.set_footer(text=f"Page 1 of 1 • KROVEX Search Engine")
            return embed

        start_idx = (self.current_page - 1) * per_page
        end_idx = start_idx + per_page
        page_results = self.search_results[start_idx:end_idx]

        for item in page_results:
            itype = item["type"]
            sig = f" {item['signature']}" if item["signature"] else ""
            perms = item.get("permissions", "Standard Member")
            alias_str = f" • Aliases: `{'`, `'.join(item['aliases'])}`" if item.get("aliases") else ""

            if itype == "prefix":
                embed.add_field(
                    name=f"⌨️ `{self.prefix}{item['name']}{sig}`",
                    value=(
                        f"• **Description:** {item['description']}\n"
                        f"• **Slash Equivalent:** `{item['slash_equiv']}`\n"
                        f"• **Category:** `{item['category']}` • **Access:** `{perms}`{alias_str}"
                    ),
                    inline=False,
                )
            else:
                embed.add_field(
                    name=f"{KrovexEmoji.LIGHTNING} `{item['name']}`",
                    value=(
                        f"• **Description:** {item['description']}\n"
                        f"• **Type:** Slash Command Subcommand\n"
                        f"• **Category:** `{item['category']}` • **Access:** `{perms}`"
                    ),
                    inline=False,
                )

        embed.set_footer(
            text=f"Page {self.current_page} of {self.total_pages} • {total_matches} Matches • KROVEX Search"
        )
        return embed

    async def perform_search(self, interaction: discord.Interaction, query: str) -> None:
        """Execute search logic, update view state, and edit host message."""
        self.is_search_mode = True
        self.search_query = query
        self.search_results = _search_commands(self.bot, query)
        self.current_page = 1
        self.current_category = None

        embed = self.build_search_embed(query, page=1)
        self._render_components()
        if interaction.response.is_done():
            if self.message:
                await self.message.edit(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except (discord.NotFound, discord.HTTPException):
            pass


# Backward-compatibility alias
ZerinaHelpView = KrovexHelpView


class Help(commands.Cog, name="Help"):
    """Interactive KROVEX help and command documentation engine."""

    def __init__(self, bot: DeathBot) -> None:
        self.bot = bot

    async def _execute_help(self, ctx: UnifiedContext, query: Optional[str] = None) -> None:
        """Execute KROVEX help command, drill-down, search, or smart suggestions."""
        prefix = (
            await self.bot.guild_repo.get_prefix(ctx.guild.id, self.bot.config.default_prefix)
            if ctx.guild and getattr(self.bot, "guild_repo", None)
            else getattr(self.bot.config, "default_prefix", "!")
        )

        # ── Case 1: Specific query drill-down or search ─────────────────────
        if query:
            clean_query = query.strip().lower()

            # 1.1 Direct Search Mode: "search <term>" or "find <term>"
            if clean_query.startswith("search ") or clean_query.startswith("find "):
                search_term = clean_query.split(maxsplit=1)[1].strip()
                view = KrovexHelpView(self.bot, ctx.author, prefix)
                view.is_search_mode = True
                view.search_query = search_term
                view.search_results = _search_commands(self.bot, search_term)
                embed = view.build_search_embed(search_term, page=1)
                view.update_button_states()
                msg = await ctx.reply(embed=embed, view=view)
                if isinstance(msg, discord.Message):
                    view.message = msg
                return

            # 1.2 Exact Prefix Command Lookup
            cmd = self.bot.get_command(clean_query)
            if cmd and not cmd.hidden:
                embed = self._build_command_detail_embed(cmd, prefix)
                await ctx.reply(embed=embed)
                return

            # 1.3 Exact Slash Command Lookup (including nested groups)
            slash_match = _find_slash_command(self.bot, clean_query)
            if slash_match:
                path, slash_cmd = slash_match
                embed = self._build_slash_detail_embed(path, slash_cmd)
                await ctx.reply(embed=embed)
                return

            # 1.4 Category / Cog Name Lookup
            for cog_name, cog in self.bot.cogs.items():
                if cog_name.lower() == clean_query:
                    view = KrovexHelpView(self.bot, ctx.author, prefix)
                    view.current_category = cog_name
                    embed = view.build_category_embed(cog_name, page=1)
                    view.update_button_states()
                    msg = await ctx.reply(embed=embed, view=view)
                    if isinstance(msg, discord.Message):
                        view.message = msg
                    return

            # 1.5 Smart Command Suggestions (Fuzzy Matching)
            all_valid_candidates: List[str] = []
            for c in self.bot.commands:
                if not c.hidden:
                    all_valid_candidates.append(c.qualified_name)
                    all_valid_candidates.extend(c.aliases)

            all_slash = _walk_slash_commands(self.bot.tree.get_commands())
            for path, _ in all_slash:
                all_valid_candidates.append(path)
                leaf = path.split()[-1]
                if leaf not in all_valid_candidates:
                    all_valid_candidates.append(leaf)

            matches = difflib.get_close_matches(clean_query, all_valid_candidates, n=3, cutoff=0.55)
            if matches:
                avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                sugg_embed = discord.Embed(
                    title="🔍 Command Suggestions",
                    description=(
                        f"{DIVIDER}\n"
                        f"No exact command or category found matching **`{query}`**.\n\n"
                        f"**Did you mean one of these?**\n"
                    ),
                    color=BRAND_COLOR,
                )
                if avatar_url:
                    sugg_embed.set_thumbnail(url=avatar_url)

                for match in matches:
                    slash_equiv = KNOWN_SLASH_EQUIVALENTS.get(match.lower(), f"/{match}")
                    sugg_embed.description += f"• **`{prefix}{match}`** *(or `{slash_equiv}`)*\n"

                sugg_embed.description += (
                    f"\n*Tip: Use `{prefix}help <command>` for detailed arguments or `/help` to open the interactive menu.*\n"
                    f"{DIVIDER}"
                )
                sugg_embed.set_footer(text="KROVEX Command Intelligence • Typo Recovery")
                await ctx.reply(embed=sugg_embed)
                return

            await ctx.send_error(
                "Command Not Found",
                f"No command, subcommand, or category found matching `{query}`.\n"
                f"Type `{prefix}help` to browse all available sections or use the search feature."
            )
            return

        # ── Case 2: Root KROVEX Home Menu ──────────────────────────────────
        view = KrovexHelpView(self.bot, ctx.author, prefix)
        embed = view.build_home_embed()
        msg = await ctx.reply(embed=embed, view=view)
        if isinstance(msg, discord.Message):
            view.message = msg

    def _build_command_detail_embed(self, cmd: commands.Command, prefix: str) -> discord.Embed:
        """Format detailed KROVEX command documentation card."""
        qname = cmd.qualified_name
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        slash_fmt = KNOWN_SLASH_EQUIVALENTS.get(qname.lower(), f"/{qname}")
        perms = _extract_command_permissions(cmd)
        cooldown = _extract_command_cooldown(cmd)

        embed = discord.Embed(
            title=f"**KROVEX** • Command Guide",
            description=(
                f"{DIVIDER}\n"
                f"### 📖 `{prefix}{qname}`\n"
                f"*{cmd.help or 'No detailed description provided.'}*\n"
                f"{DIVIDER}"
            ),
            color=BRAND_COLOR,
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        sig = f" {cmd.signature}" if cmd.signature else ""
        syntax_text = (
            f"**Prefix:** `{prefix}{qname}{sig}`\n"
            f"**Slash:** `{slash_fmt}`"
        )
        embed.add_field(name="⌨️ Syntax & Invocation", value=syntax_text, inline=False)

        # Arguments breakdown
        if cmd.clean_params:
            args_lines = []
            for p_name, param in cmd.clean_params.items():
                req = "Required" if param.default is param.empty else f"Optional (Default: `{param.default}`)"
                args_lines.append(f"• `{p_name}` — *{req}*")
            embed.add_field(name="⚙️ Parameters & Arguments", value="\n".join(args_lines), inline=False)
        else:
            embed.add_field(name="⚙️ Parameters & Arguments", value="*None required.*", inline=False)

        # Aliases
        aliases_text = ", ".join(f"`{a}`" for a in cmd.aliases) if cmd.aliases else "*None*"
        embed.add_field(name="🏷️ Aliases", value=aliases_text, inline=True)

        # Required Permissions
        embed.add_field(name="🔒 Required Permissions", value=f"`{perms}`", inline=True)

        # Cooldown
        embed.add_field(name="⏱️ Cooldown", value=cooldown, inline=True)

        if cmd.cog:
            icon, label, _ = _get_category_meta(cmd.cog.qualified_name)
            embed.add_field(name="📦 Category", value=f"{icon} {label}", inline=True)

        embed.set_footer(text=f"KROVEX Engine • Command Documentation")
        return embed

    def _build_slash_detail_embed(self, path: str, slash_cmd: Any) -> discord.Embed:
        """Format detailed Slash command documentation card with complete hierarchy."""
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        desc = getattr(slash_cmd, "description", "") or "No detailed description provided."
        perms = _extract_slash_permissions(slash_cmd)
        params = getattr(slash_cmd, "parameters", [])

        # Build full invocation signature
        sig_parts = []
        param_lines = []
        for p in params:
            p_name = getattr(p, "name", "param")
            p_desc = getattr(p, "description", "")
            p_req = getattr(p, "required", False)
            if p_req:
                sig_parts.append(f"<{p_name}>")
                param_lines.append(f"• `<{p_name}>` — **Required**: {p_desc}")
            else:
                sig_parts.append(f"[{p_name}]")
                param_lines.append(f"• `[{p_name}]` — *Optional*: {p_desc}")

        sig_str = f" {' '.join(sig_parts)}" if sig_parts else ""

        embed = discord.Embed(
            title=f"**KROVEX** • Slash Command Guide",
            description=(
                f"{DIVIDER}\n"
                f"### {KrovexEmoji.LIGHTNING} `/{path}`\n"
                f"*{desc}*\n"
                f"{DIVIDER}"
            ),
            color=BRAND_COLOR,
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        embed.add_field(
            name="⌨️ Invocation Syntax",
            value=f"**Slash Command:** `/{path}{sig_str}`",
            inline=False,
        )

        if param_lines:
            embed.add_field(name="⚙️ Parameters & Options", value="\n".join(param_lines), inline=False)
        else:
            embed.add_field(name="⚙️ Parameters & Options", value="*None required.*", inline=False)

        embed.add_field(name="🔒 Required Permissions", value=f"`{perms}`", inline=True)
        embed.add_field(name="📦 Root Domain", value=f"`/{path.split()[0]}`", inline=True)

        embed.set_footer(text=f"KROVEX Engine • Slash Application Command")
        return embed

    @commands.command(name="help", help="Display the KROVEX interactive help menu and command guides.")
    async def help_prefix(self, ctx: commands.Context, *, command_or_category: Optional[str] = None) -> None:
        await self._execute_help(UnifiedContext.from_prefix(ctx), command_or_category)

    @app_commands.command(name="help", description="Browse bot command documentation and categories.")
    @app_commands.describe(command_or_category="Specific command or category name to inspect")
    async def help_slash(self, interaction: discord.Interaction, command_or_category: Optional[str] = None) -> None:
        await self._execute_help(UnifiedContext.from_interaction(interaction), command_or_category)


async def setup(bot: DeathBot) -> None:
    """Setup hook to register cog."""
    await bot.add_cog(Help(bot))
