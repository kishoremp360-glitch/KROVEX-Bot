"""Unit tests for embed builders and visual identity."""

import discord
from bot.utils.embeds import (
    COLOR_ERROR,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_WARNING,
    EMOJI_ERROR,
    EMOJI_MUSIC,
    EMOJI_SUCCESS,
    EMOJI_WARNING,
    EmbedBuilder,
)
from bot.utils.emojis import KrovexEmoji


def test_base_embed():
    """Verify base embed attributes and timestamp."""
    embed = EmbedBuilder.base(
        title="Test Title",
        description="Test Description",
        footer_text="Test Footer",
    )
    assert embed.title == "Test Title"
    assert embed.description == "Test Description"
    assert embed.color.value == COLOR_PRIMARY
    assert embed.footer.text == "Test Footer"
    assert embed.timestamp is not None


def test_success_embed():
    """Verify success embed colors and icon prefix."""
    embed = EmbedBuilder.success(title="Operation Completed", description="All tasks finished.")
    assert (EMOJI_SUCCESS in embed.title) or (KrovexEmoji.CORRECT.discord_format in embed.title)
    assert embed.color.value == COLOR_SUCCESS
    assert embed.description == "All tasks finished."


def test_error_embed():
    """Verify error embed colors and error code in footer."""
    embed = EmbedBuilder.error(
        title="Permission Denied",
        description="Cannot execute.",
        error_code="ERR-8842",
    )
    assert (EMOJI_ERROR in embed.title) or (KrovexEmoji.FAILED.discord_format in embed.title)
    assert embed.color.value == COLOR_ERROR
    assert "ERR-8842" in embed.footer.text


def test_warning_embed():
    """Verify warning embed colors."""
    embed = EmbedBuilder.warning(title="Rate Limit", description="Slow down.")
    assert (EMOJI_WARNING in embed.title) or (KrovexEmoji.WARNING.discord_format in embed.title)
    assert embed.color.value == COLOR_WARNING


def test_music_embed():
    """Verify music embed styling."""
    embed = EmbedBuilder.music(
        title="Now Playing: Synthwave Chill",
        description="Duration: 03:45",
        thumbnail="https://example.com/cover.png",
    )
    assert (EMOJI_MUSIC in embed.title) or (KrovexEmoji.MUSIC.discord_format in embed.title)
    assert embed.color.value == COLOR_PRIMARY
    assert embed.thumbnail.url == "https://example.com/cover.png"

