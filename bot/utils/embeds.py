"""Neon Black & Purple embed builder for Death Bot.

Ensures visual uniformity, rich metadata, and clean typography across
all bot responses.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Optional

import discord

from bot.utils.emojis import KrovexEmoji


def _parse_color_env(name: str, fallback: int) -> int:
    val = os.getenv(name, "").strip()
    if not val:
        return fallback
    try:
        if val.startswith("0x") or val.startswith("0X"):
            return int(val, 16)
        if val.startswith("#"):
            return int(val[1:], 16)
        return int(val, 16)
    except ValueError:
        return fallback


# Premium Theme Palette (Dynamically loaded from .env visual theme with elegant fallbacks)
COLOR_PRIMARY = _parse_color_env("COLOR_PRIMARY", 0x8B5CF6)      # Electric Violet / Primary Accent
COLOR_SECONDARY = _parse_color_env("COLOR_SECONDARY", 0x22D3EE)  # Cyan Glow / Secondary Accent
COLOR_SUCCESS = _parse_color_env("COLOR_SUCCESS", 0x22C55E)      # Emerald Success
COLOR_ERROR = _parse_color_env("COLOR_ERROR", 0xEF4444)          # Ruby Crimson Error
COLOR_WARNING = _parse_color_env("COLOR_WARNING", 0xF59E0B)      # Amber Warning
COLOR_INFO = _parse_color_env("COLOR_INFO", 0x3B82F6)            # Sky Blue Accent
COLOR_DARK = 0x111216                                            # Obsidian Dark

# Global Typography Fonts from .env
UI_FONT_BODY = os.getenv("UI_FONT_BODY", "Inter").strip() or "Inter"
UI_FONT_HEADING = os.getenv("UI_FONT_HEADING", "Oxanium").strip() or "Oxanium"
UI_FONT_MONOSPACE = os.getenv("UI_FONT_MONOSPACE", "Chakra Petch").strip() or "Chakra Petch"

# Branding & Embed Configuration from .env
BOT_NAME = os.getenv("BOT_NAME", "KROVEX").strip() or "KROVEX"
BOT_AUTHOR_NAME = os.getenv("BOT_AUTHOR_NAME", "KROVEX").strip() or "KROVEX"
BOT_FOOTER_TEXT = os.getenv("BOT_FOOTER_TEXT", "Powered by KROVEX").strip() or "Powered by KROVEX"
EMBED_FOOTER = os.getenv("EMBED_FOOTER", "true").strip().lower() in ("true", "1", "yes")
EMBED_TIMESTAMP = os.getenv("EMBED_TIMESTAMP", "true").strip().lower() in ("true", "1", "yes")

# Standardized Emojis / Glyphs (Integrated with KROVEX Application Emojis)
EMOJI_SUCCESS = KrovexEmoji.CORRECT.discord_format      # <:843139correct:1571190648630153368>
EMOJI_ERROR = KrovexEmoji.FAILED.discord_format          # <:3972failed:1571191511528505384>
EMOJI_WARNING = KrovexEmoji.WARNING.discord_format       # <a:6850warning:1571191536472031262>
EMOJI_INFO = KrovexEmoji.BLUE.discord_format             # <a:550849blue:1571035143748194304>
EMOJI_MUSIC = KrovexEmoji.BLUE.discord_format            # <a:550849blue:1571035143748194304>
EMOJI_ADMIN = KrovexEmoji.SHIELD_CROWN.discord_format    # <:38124shieldcrown:1571189876177764493>
EMOJI_BULLET = KrovexEmoji.WHITE_WING.discord_format     # <a:602393rightangleallwhitewing:1571190676081869050>
EMOJI_TICKET = KrovexEmoji.MAKE_TICKET.discord_format    # <a:560905maketicket:1571145823042019379>
EMOJI_BOOST = KrovexEmoji.ROCKET.discord_format          # <a:968736rocket:1571160565622120549>
EMOJI_LIGHTNING = KrovexEmoji.LIGHTNING.discord_format  # <a:25801:1571196825220943902>
EMOJI_TADA = KrovexEmoji.TADA.discord_format            # <a:3368kokotadance:1571199726395588772>
EMOJI_VICTORY = KrovexEmoji.VICTORY.discord_format      # <:90177vforvictory:1571209730976649246>
EMOJI_LOSE = KrovexEmoji.YOU_SUCK.discord_format        # <:99311yousucksign:1571210484907114617>
EMOJI_CRYSTALS = KrovexEmoji.CRYSTALS.discord_format    # <a:34196crystals:1571209787922718743>
EMOJI_SPARKLES = KrovexEmoji.PURPLE_SPARKLES.discord_format # <a:55256purplesparkles:1571210505786495016>
EMOJI_HEART = KrovexEmoji.ANIMATED_HEART.discord_format # <a:19539heart:1571210595079037040>
EMOJI_PETALS = KrovexEmoji.FALLING_PETALS.discord_format # <a:62524fallingpetals:1571209707115253943>
EMOJI_SCORE_100 = KrovexEmoji.SCORE_100.discord_format  # <a:6433100:1571210615286931477>
EMOJI_VOICE = "🎙️"
EMOJI_WELCOME = KrovexEmoji.EMO_ANGEL.discord_format     # <a:414205emoangel:1571036723729928202>
EMOJI_LOADING = "⏳"
EMOJI_NITRO = KrovexEmoji.NITRO.discord_format
EMOJI_GREEN_SPARKLES = KrovexEmoji.GREEN_SPARKLES.discord_format
EMOJI_ANIMATED_CROSS = KrovexEmoji.ANIMATED_CROSS.discord_format
EMOJI_STARBUCKS = KrovexEmoji.STARBUCKS.discord_format
EMOJI_MUFFIN = KrovexEmoji.KITTY_MUFFIN.discord_format
EMOJI_CINNAMOROLL = KrovexEmoji.CINNAMOROLL.discord_format
EMOJI_MOON = KrovexEmoji.CRESCENT_MOON.discord_format
EMOJI_PURPLE_MOON = KrovexEmoji.PURPLE_MOON.discord_format
EMOJI_CRYSTAL_BALL = KrovexEmoji.CRYSTAL_BALL.discord_format
EMOJI_KNIFE = KrovexEmoji.RAINBOW_KNIFE.discord_format
EMOJI_WHITE_FLOWERS = KrovexEmoji.WHITE_FLOWERS.discord_format
EMOJI_BUBBLES = KrovexEmoji.BUBBLES.discord_format
EMOJI_MILK_MOCHA = KrovexEmoji.MILK_MOCHA.discord_format
EMOJI_BLUE_BUTTERFLIES = KrovexEmoji.BLUE_BUTTERFLIES.discord_format
EMOJI_PINK_STARS = KrovexEmoji.PINK_STARS.discord_format
EMOJI_DRAMA_QUEEN = KrovexEmoji.DRAMA_QUEEN.discord_format
EMOJI_YAE_HEART = KrovexEmoji.YAE_HEART.discord_format
EMOJI_RAINBOW_STAR = KrovexEmoji.RAINBOW_STAR.discord_format


class EmbedBuilder:
    """Builder class for constructing standard, visually consistent embeds."""

    @staticmethod
    def base(
        title: Optional[str] = None,
        description: Optional[str] = None,
        color: int = COLOR_PRIMARY,
        thumbnail: Optional[str] = None,
        image: Optional[str] = None,
        author_name: Optional[str] = None,
        author_icon_url: Optional[str] = None,
        footer_text: Optional[str] = None,
        footer_icon_url: Optional[str] = None,
        timestamp: bool = True,
    ) -> discord.Embed:
        """Construct a standardized base embed adhering to .env configuration."""
        actual_footer = footer_text if footer_text is not None else BOT_FOOTER_TEXT
        should_show_footer = EMBED_FOOTER and bool(actual_footer)
        should_show_timestamp = timestamp and EMBED_TIMESTAMP

        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc) if should_show_timestamp else None,
        )

        if author_name:
            embed.set_author(name=author_name, icon_url=author_icon_url)

        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        if image:
            embed.set_image(url=image)

        if should_show_footer:
            embed.set_footer(text=actual_footer, icon_url=footer_icon_url)

        return embed

    @staticmethod
    def success(
        title: str = "Success",
        description: Optional[str] = None,
        footer_text: Optional[str] = None,
    ) -> discord.Embed:
        """Create a success embed with neon green accent."""
        full_title = f"{EMOJI_SUCCESS} {title}"
        return EmbedBuilder.base(
            title=full_title,
            description=description,
            color=COLOR_SUCCESS,
            footer_text=footer_text or "KROVEX • Operation Successful",
        )

    @staticmethod
    def error(
        title: str = "Error",
        description: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> discord.Embed:
        """Create an error embed with neon red accent."""
        full_title = f"{EMOJI_ERROR} {title}"
        footer = f"Error Reference: {error_code}" if error_code else "KROVEX • Error"
        return EmbedBuilder.base(
            title=full_title,
            description=description or "An unexpected issue occurred while executing this action.",
            color=COLOR_ERROR,
            footer_text=footer,
        )

    @staticmethod
    def warning(
        title: str = "Warning",
        description: Optional[str] = None,
    ) -> discord.Embed:
        """Create a warning embed with amber accent."""
        return EmbedBuilder.base(
            title=f"{EMOJI_WARNING} {title}",
            description=description,
            color=COLOR_WARNING,
            footer_text="KROVEX • Caution Advised",
        )

    @staticmethod
    def info(
        title: str = "Information",
        description: Optional[str] = None,
    ) -> discord.Embed:
        """Create an informational embed with royal purple accent."""
        return EmbedBuilder.base(
            title=f"{EMOJI_INFO} {title}",
            description=description,
            color=COLOR_PRIMARY,
        )

    @staticmethod
    def loading(
        title: str = "Processing...",
        description: Optional[str] = None,
    ) -> discord.Embed:
        """Create a loading/pending embed."""
        return EmbedBuilder.base(
            title=f"{EMOJI_LOADING} {title}",
            description=description or "Please wait while your request is processed...",
            color=COLOR_SECONDARY,
        )

    @staticmethod
    def music(
        title: str,
        description: Optional[str] = None,
        thumbnail: Optional[str] = None,
        color: int = COLOR_PRIMARY,
    ) -> discord.Embed:
        """Create a specialized music player embed."""
        return EmbedBuilder.base(
            title=f"{EMOJI_MUSIC} {title}",
            description=description,
            color=color,
            thumbnail=thumbnail,
            footer_text="KROVEX Music Engine • High Fidelity",
        )

