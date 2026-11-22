"""Automated tests for Zerina-style Help UI and Logging command mapping."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.core.bot import DeathBot
from bot.config import BotConfig
from bot.core.context import UnifiedContext
from bot.cogs.utility.help import Help, ZerinaHelpView, CategorySelect
from bot.cogs.logging.cog import Logging


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.user.display_avatar.url = "https://cdn.discordapp.com/avatars/test/avatar.png"
    bot.latency = 0.024
    bot.config = MagicMock()
    bot.config.default_prefix = ","
    bot.guild_repo = None
    bot.tree = MagicMock()
    bot.tree.get_command = MagicMock(return_value=None)
    bot.commands = []
    bot.cogs = {}
    return bot


@pytest.mark.asyncio
async def test_logging_subcommands_registered_in_cog():
    """Verify logging setup, config, reset, enable are real registered commands."""
    real_bot = DeathBot(config=BotConfig.from_env(validate=False))
    await real_bot.load_extension("bot.cogs.logging.cog")

    cmd_setup = real_bot.get_command("logging setup")
    cmd_config = real_bot.get_command("logging config")
    cmd_reset = real_bot.get_command("logging reset")
    cmd_enable = real_bot.get_command("logging enable")

    assert cmd_setup is not None, "logging setup must be registered"
    assert cmd_config is not None, "logging config must be registered"
    assert cmd_reset is not None, "logging reset must be registered"
    assert cmd_enable is not None, "logging enable must be registered"

    assert "audit log destination channels" in cmd_setup.help.lower()
    assert "configured log channels" in cmd_config.help.lower()
    assert "reset logging configuration" in cmd_reset.help.lower()
    assert "enable or toggle logging" in cmd_enable.help.lower()


@pytest.mark.asyncio
async def test_zerina_help_home_menu(mock_bot):
    """Verify home panel renders with Zerina headers and dynamic mention greeting."""
    author = MagicMock(spec=discord.Member)
    author.id = 999999
    author.mention = "<@999999>"

    view = ZerinaHelpView(mock_bot, author, prefix=",")
    home_embed = view.build_home_embed()

    assert "**KROVEX**" in home_embed.title
    assert "Premium Command Library" in home_embed.title
    assert "<@999999>" in home_embed.description
    assert "Browse the complete command library" in home_embed.description
    assert view.select_menu.placeholder in ("Choose a section", "Browse premium command categories")


@pytest.mark.asyncio
async def test_logging_category_page_displays_all_four_commands():
    """Verify the Logging category page lists logging setup, config, reset, enable with slash formats."""
    real_bot = DeathBot(config=BotConfig.from_env(validate=False))
    await real_bot.load_extension("bot.cogs.logging.cog")
    await real_bot.load_extension("bot.cogs.utility.help")

    author = MagicMock(spec=discord.Member)
    author.id = 123456
    author.mention = "<@123456>"

    view = ZerinaHelpView(real_bot, author, prefix=",")
    embed = view.build_category_embed("Logging", page=1)

    field_names = [f.name for f in embed.fields]
    field_values = [f.value for f in embed.fields]

    # Verify logging setup
    assert any("logging setup" in name for name in field_names)
    assert any("/setup logging" in val or "/logs logchannel" in val or "/logs channel" in val for val in field_values)

    # Verify logging config
    assert any("logging config" in name for name in field_names)
    assert any("/logs logstatus" in val for val in field_values)

    # Verify logging reset
    assert any("logging reset" in name for name in field_names)
    assert any("/logs" in val for val in field_values)

    # Verify logging enable
    assert any("logging enable" in name for name in field_names)
    assert any("/logs enable" in val or "/logs logtoggle" in val for val in field_values)


@pytest.mark.asyncio
async def test_drilldown_help_detail_for_each_logging_command():
    """Verify drilldown documentation embed for each of the 4 logging commands."""
    real_bot = DeathBot(config=BotConfig.from_env(validate=False))
    await real_bot.load_extension("bot.cogs.logging.cog")
    await real_bot.load_extension("bot.cogs.utility.help")

    help_cog: Help = real_bot.cogs["Help"]

    for sub in ["setup", "config", "reset", "enable"]:
        cmd = real_bot.get_command(f"logging {sub}")
        assert cmd is not None
        detail_embed = help_cog._build_command_detail_embed(cmd, prefix=",")

        assert f",logging {sub}" in detail_embed.description
        assert any("Syntax & Invocation" in f.name for f in detail_embed.fields)
        assert any("Required Permissions" in f.name for f in detail_embed.fields)

        # Check Administrator permission requirement
        perm_field = next(f for f in detail_embed.fields if "Required Permissions" in f.name)
        assert "Administrator" in perm_field.value



@pytest.mark.asyncio
async def test_author_lock_on_zerina_view(mock_bot):
    """Verify that users other than the invoker are blocked with an ephemeral message."""
    author = MagicMock(spec=discord.Member)
    author.id = 111111

    intruder = MagicMock(spec=discord.Member)
    intruder.id = 222222

    view = ZerinaHelpView(mock_bot, author, prefix=",")

    # Invoker interaction
    interaction_owner = MagicMock(spec=discord.Interaction)
    interaction_owner.user = author
    assert await view.interaction_check(interaction_owner) is True

    # Intruder interaction
    interaction_intruder = MagicMock(spec=discord.Interaction)
    interaction_intruder.user = intruder
    interaction_intruder.response = MagicMock()
    interaction_intruder.response.send_message = AsyncMock()

    assert await view.interaction_check(interaction_intruder) is False
    interaction_intruder.response.send_message.assert_awaited_with(
        "⚠️ This help menu was opened by another user. Run `,help` or `/help` to open your own.",
        ephemeral=True,
    )
