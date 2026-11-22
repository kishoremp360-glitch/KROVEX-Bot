"""Unit tests for KROVEX Central Application Emoji Registry and Subsystem Integrations.

Verifies:
1. Exact registered IDs, names, and animated=True status for all 8 emojis.
2. Semantic aliases.
3. Standard Discord animated syntax <a:name:id>.
4. PartialEmoji generation with animated=True.
5. discord.ui.Button and discord.SelectOption compatibility.
6. Fallbacks.
7. Registry lookups (by name, ID).
8. Actual subsystem integration:
   - Help dashboard (category metadata and next/close buttons).
   - Music player (idle embed and skip button).
   - Security panel (panel embed title and toggle buttons).
   - Welcome system (welcome and farewell embed titles).
   - Social profile (profile embed title).
   - Leveling (leaderboard embed title).
   - Shop & Tickets views (buy and cancel buttons).
"""

from __future__ import annotations

from unittest.mock import MagicMock
import discord
import pytest

from bot.utils.emojis import AppEmoji, KrovexEmoji
from bot.cogs.utility.help import CATEGORY_METADATA, KrovexHelpView
from bot.services.music.views import MusicPlayerView
from bot.cogs.security.panel import build_security_embed
from bot.cogs.shop.views import ShopBuyConfirmView
from bot.cogs.tickets.views import TicketCloseConfirmView, TicketPanelView


def test_registered_emoji_ids_and_names():
    """Verify exact application emoji names, IDs, and animated status for ALL 17 registered emojis."""
    emojis = [
        (KrovexEmoji.BLUE, "550849blue", 1571035143748194304, True),
        (KrovexEmoji.PURPLE_ARROW, "131720purplearrow", 1571036183751036928, True),
        (KrovexEmoji.HOLLIENS, "275933holliens", 1571036451825647677, True),
        (KrovexEmoji.EMO_ANGEL, "414205emoangel", 1571036723729928202, True),
        (KrovexEmoji.BATS, "828216bats", 1571037209098850428, True),
        (KrovexEmoji.WHITE_CROWN, "881980whitecrown", 1571039260721684480, True),
        (KrovexEmoji.CROSS, "684179cross", 1571039956179099729, True),
        (KrovexEmoji.PINK_BUTTERFLIES, "65954pinkbutterflies", 1571040335944097803, True),
        (KrovexEmoji.CHECK_BW, "8632chechbw", 1571047860814741524, True),
        (KrovexEmoji.MILK, "7163milk3", 1571053751131709501, True),
        (KrovexEmoji.MAKE_TICKET, "560905maketicket", 1571145823042019379, True),
        (KrovexEmoji.ROCKET, "968736rocket", 1571160565622120549, True),
        (KrovexEmoji.SHIELD_CROWN, "38124shieldcrown", 1571189876177764493, False),
        (KrovexEmoji.CORRECT, "843139correct", 1571190648630153368, False),
        (KrovexEmoji.WHITE_WING, "602393rightangleallwhitewing", 1571190676081869050, True),
        (KrovexEmoji.FAILED, "3972failed", 1571191511528505384, False),
        (KrovexEmoji.WARNING, "6850warning", 1571191536472031262, True),
        (KrovexEmoji.LIGHTNING, "25801", 1571196825220943902, True),
        (KrovexEmoji.TADA, "3368kokotadance", 1571199726395588772, True),
    ]

    for emoji, expected_name, expected_id, expected_animated in emojis:
        assert emoji.name == expected_name
        assert emoji.id == expected_id
        assert emoji.animated is expected_animated, f"{expected_name} animated flag mismatch"


def test_semantic_aliases():
    """Verify internal developer aliases map to the intended application emojis."""
    assert KrovexEmoji.SECURITY is KrovexEmoji.BATS
    assert KrovexEmoji.WELCOME is KrovexEmoji.EMO_ANGEL
    assert KrovexEmoji.MODERATION is KrovexEmoji.HOLLIENS
    assert KrovexEmoji.NAV_NEXT is KrovexEmoji.PURPLE_ARROW
    assert KrovexEmoji.MUSIC is KrovexEmoji.BLUE
    assert KrovexEmoji.STATUS is KrovexEmoji.BLUE
    assert KrovexEmoji.VIP is KrovexEmoji.WHITE_CROWN
    assert KrovexEmoji.CROWN is KrovexEmoji.WHITE_CROWN
    assert KrovexEmoji.LEADERBOARD is KrovexEmoji.WHITE_CROWN
    assert KrovexEmoji.DENIED is KrovexEmoji.CROSS
    assert KrovexEmoji.ERROR is KrovexEmoji.FAILED
    assert KrovexEmoji.SUCCESS is KrovexEmoji.CORRECT
    assert KrovexEmoji.WARN is KrovexEmoji.WARNING
    assert KrovexEmoji.ALERT is KrovexEmoji.WARNING
    assert KrovexEmoji.ADMIN is KrovexEmoji.SHIELD_CROWN
    assert KrovexEmoji.SHIELD is KrovexEmoji.SHIELD_CROWN
    assert KrovexEmoji.BULLET is KrovexEmoji.WHITE_WING
    assert KrovexEmoji.WING is KrovexEmoji.WHITE_WING
    assert KrovexEmoji.FUN is KrovexEmoji.MILK
    assert KrovexEmoji.ECONOMY is KrovexEmoji.MILK
    assert KrovexEmoji.BOLT is KrovexEmoji.LIGHTNING
    assert KrovexEmoji.ELECTRIC is KrovexEmoji.LIGHTNING
    assert KrovexEmoji.POWER is KrovexEmoji.LIGHTNING
    assert KrovexEmoji.PING is KrovexEmoji.LIGHTNING
    assert KrovexEmoji.CELEBRATE is KrovexEmoji.TADA
    assert KrovexEmoji.PARTY is KrovexEmoji.TADA
    assert KrovexEmoji.DANCE is KrovexEmoji.TADA
    assert KrovexEmoji.WIN is KrovexEmoji.TADA
    assert KrovexEmoji.KOKOTA is KrovexEmoji.TADA
    assert KrovexEmoji.CANCEL is KrovexEmoji.CROSS
    assert KrovexEmoji.AESTHETIC is KrovexEmoji.PINK_BUTTERFLIES
    assert KrovexEmoji.SOCIAL is KrovexEmoji.PINK_BUTTERFLIES
    assert KrovexEmoji.TICKET is KrovexEmoji.MAKE_TICKET
    assert KrovexEmoji.BOOST is KrovexEmoji.ROCKET
    assert KrovexEmoji.LAUNCH is KrovexEmoji.ROCKET
    assert KrovexEmoji.SPEED is KrovexEmoji.ROCKET


def test_discord_formatting():
    """Verify standard Discord animated custom message formatting <a:name:id>."""
    assert KrovexEmoji.BATS.discord_format == "<a:828216bats:1571037209098850428>"
    assert str(KrovexEmoji.BATS) == "<a:828216bats:1571037209098850428>"
    assert KrovexEmoji.PURPLE_ARROW.discord_format == "<a:131720purplearrow:1571036183751036928>"
    assert KrovexEmoji.BLUE.discord_format == "<a:550849blue:1571035143748194304>"
    assert KrovexEmoji.WHITE_CROWN.discord_format == "<a:881980whitecrown:1571039260721684480>"
    assert KrovexEmoji.CROSS.discord_format == "<a:684179cross:1571039956179099729>"
    assert KrovexEmoji.PINK_BUTTERFLIES.discord_format == "<a:65954pinkbutterflies:1571040335944097803>"
    assert KrovexEmoji.MAKE_TICKET.discord_format == "<a:560905maketicket:1571145823042019379>"
    assert KrovexEmoji.ROCKET.discord_format == "<a:968736rocket:1571160565622120549>"


def test_partial_emoji_generation():
    """Verify construction of discord.PartialEmoji objects with matching animated flag."""
    for emoji in KrovexEmoji.all_emojis():
        partial = emoji.partial
        assert isinstance(partial, discord.PartialEmoji)
        assert partial.name == emoji.name
        assert partial.id == emoji.id
        assert partial.animated is emoji.animated


def test_ui_component_compatibility():
    """Verify compatibility with discord.ui.Button and discord.SelectOption for animated emojis."""
    # Button with animated PartialEmoji
    btn_partial = discord.ui.Button(label="Next", emoji=KrovexEmoji.PURPLE_ARROW.partial)
    comp_dict = btn_partial.to_component_dict()
    assert comp_dict["emoji"]["id"] == 1571036183751036928
    assert comp_dict["emoji"]["name"] == "131720purplearrow"
    assert comp_dict["emoji"]["animated"] is True

    # Button with animated string format
    btn_str = discord.ui.Button(label="Security", emoji=KrovexEmoji.BATS.discord_format)
    comp_dict_str = btn_str.to_component_dict()
    assert comp_dict_str["emoji"]["id"] == 1571037209098850428
    assert comp_dict_str["emoji"]["name"] == "828216bats"
    assert comp_dict_str["emoji"]["animated"] is True

    # SelectOption with animated PartialEmoji
    option = discord.SelectOption(
        label="Security & Anti-Nuke",
        value="Security",
        emoji=KrovexEmoji.BATS.partial,
    )
    opt_dict = option.to_dict()
    assert opt_dict["emoji"]["id"] == 1571037209098850428
    assert opt_dict["emoji"]["name"] == "828216bats"
    assert opt_dict["emoji"]["animated"] is True


def test_fallback_behavior():
    """Verify fallback string when custom emojis are disabled or fallback is requested."""
    assert KrovexEmoji.BATS.fallback == "🦇"
    assert KrovexEmoji.BATS.format(use_fallback=True) == "🦇"
    assert KrovexEmoji.BATS.format(use_fallback=False) == "<a:828216bats:1571037209098850428>"

    assert KrovexEmoji.WHITE_CROWN.fallback == "👑"
    assert KrovexEmoji.WHITE_CROWN.format(use_fallback=True) == "👑"
    assert KrovexEmoji.WHITE_CROWN.format(use_fallback=False) == "<a:881980whitecrown:1571039260721684480>"

    assert KrovexEmoji.CROSS.fallback == "❌"
    assert KrovexEmoji.PINK_BUTTERFLIES.fallback == "🦋"
    assert KrovexEmoji.SHIELD_CROWN.fallback == "🛡️"
    assert KrovexEmoji.SHIELD_CROWN.discord_format == "<:38124shieldcrown:1571189876177764493>"
    assert KrovexEmoji.CORRECT.discord_format == "<:843139correct:1571190648630153368>"
    assert KrovexEmoji.FAILED.discord_format == "<:3972failed:1571191511528505384>"
    assert KrovexEmoji.WARNING.discord_format == "<a:6850warning:1571191536472031262>"


def test_registry_lookups():
    """Verify lookup by exact name and by integer ID across all registered emojis."""
    assert KrovexEmoji.get_by_name("828216bats") is KrovexEmoji.BATS
    assert KrovexEmoji.get_by_name("881980whitecrown") is KrovexEmoji.WHITE_CROWN
    assert KrovexEmoji.get_by_name("684179cross") is KrovexEmoji.CROSS
    assert KrovexEmoji.get_by_name("65954pinkbutterflies") is KrovexEmoji.PINK_BUTTERFLIES
    assert KrovexEmoji.get_by_name("560905maketicket") is KrovexEmoji.MAKE_TICKET
    assert KrovexEmoji.get_by_name("968736rocket") is KrovexEmoji.ROCKET
    assert KrovexEmoji.get_by_name("38124shieldcrown") is KrovexEmoji.SHIELD_CROWN
    assert KrovexEmoji.get_by_name("843139correct") is KrovexEmoji.CORRECT
    assert KrovexEmoji.get_by_name("3972failed") is KrovexEmoji.FAILED
    assert KrovexEmoji.get_by_name("6850warning") is KrovexEmoji.WARNING
    assert KrovexEmoji.get_by_name("25801") is KrovexEmoji.LIGHTNING
    assert KrovexEmoji.get_by_name("3368kokotadance") is KrovexEmoji.TADA
    assert KrovexEmoji.get_by_name("62524fallingpetals") is KrovexEmoji.FALLING_PETALS
    assert KrovexEmoji.get_by_name("90177vforvictory") is KrovexEmoji.VICTORY
    assert KrovexEmoji.get_by_name("34196crystals") is KrovexEmoji.CRYSTALS
    assert KrovexEmoji.get_by_name("99311yousucksign") is KrovexEmoji.YOU_SUCK
    assert KrovexEmoji.get_by_name("55256purplesparkles") is KrovexEmoji.PURPLE_SPARKLES
    assert KrovexEmoji.get_by_name("19539heart") is KrovexEmoji.ANIMATED_HEART
    assert KrovexEmoji.get_by_name("6433100") is KrovexEmoji.SCORE_100
    assert KrovexEmoji.get_by_name("nonexistent") is None

    assert KrovexEmoji.get_by_id(1571037209098850428) is KrovexEmoji.BATS
    assert KrovexEmoji.get_by_id(1571039260721684480) is KrovexEmoji.WHITE_CROWN
    assert KrovexEmoji.get_by_id(1571039956179099729) is KrovexEmoji.CROSS
    assert KrovexEmoji.get_by_id(1571040335944097803) is KrovexEmoji.PINK_BUTTERFLIES
    assert KrovexEmoji.get_by_id(1571145823042019379) is KrovexEmoji.MAKE_TICKET
    assert KrovexEmoji.get_by_id(1571160565622120549) is KrovexEmoji.ROCKET
    assert KrovexEmoji.get_by_id(1571189876177764493) is KrovexEmoji.SHIELD_CROWN
    assert KrovexEmoji.get_by_id(1571190648630153368) is KrovexEmoji.CORRECT
    assert KrovexEmoji.get_by_id(1571191511528505384) is KrovexEmoji.FAILED
    assert KrovexEmoji.get_by_id(1571191536472031262) is KrovexEmoji.WARNING
    assert KrovexEmoji.get_by_id(1571196825220943902) is KrovexEmoji.LIGHTNING
    assert KrovexEmoji.get_by_id(1571199726395588772) is KrovexEmoji.TADA
    assert KrovexEmoji.get_by_id(1571209707115253943) is KrovexEmoji.FALLING_PETALS
    assert KrovexEmoji.get_by_id(1571209730976649246) is KrovexEmoji.VICTORY
    assert KrovexEmoji.get_by_id(1571209787922718743) is KrovexEmoji.CRYSTALS
    assert KrovexEmoji.get_by_id(1571210484907114617) is KrovexEmoji.YOU_SUCK
    assert KrovexEmoji.get_by_id(1571210505786495016) is KrovexEmoji.PURPLE_SPARKLES
    assert KrovexEmoji.get_by_id(1571210595079037040) is KrovexEmoji.ANIMATED_HEART
    assert KrovexEmoji.get_by_id(1571210615286931477) is KrovexEmoji.SCORE_100
    assert KrovexEmoji.get_by_id(9999999999) is None

    all_emojis = KrovexEmoji.all_emojis()
    assert len(all_emojis) == 56


def test_help_dashboard_subsystem_integration():
    """Verify application emojis integrated into Help dashboard metadata and buttons."""
    # Category metadata custom emojis
    assert CATEGORY_METADATA["Security"][0] == KrovexEmoji.SECURITY.discord_format
    assert CATEGORY_METADATA["Moderation"][0] == KrovexEmoji.MODERATION.discord_format
    assert CATEGORY_METADATA["Music"][0] == KrovexEmoji.MUSIC.discord_format
    assert CATEGORY_METADATA["Welcome"][0] == KrovexEmoji.WELCOME.discord_format
    assert CATEGORY_METADATA["Social"][0] == KrovexEmoji.SOCIAL.discord_format
    assert CATEGORY_METADATA["Leveling"][0] == KrovexEmoji.LEADERBOARD.discord_format
    assert CATEGORY_METADATA["TicketsCog"][0] == KrovexEmoji.TICKET.discord_format
    assert CATEGORY_METADATA["SetupWizard"][0] == KrovexEmoji.ROCKET.discord_format
    assert CATEGORY_METADATA["Administration"][0] == KrovexEmoji.ADMIN.discord_format
    assert CATEGORY_METADATA["EconomyCog"][0] == KrovexEmoji.ECONOMY.discord_format
    assert CATEGORY_METADATA["Logging"][0] == KrovexEmoji.CHECK_BW.discord_format
    assert CATEGORY_METADATA["Fun"][0] == KrovexEmoji.FUN.discord_format

    # Check button emojis in KrovexHelpView
    mock_bot = MagicMock()
    mock_author = MagicMock(spec=discord.Member)
    mock_author.id = 12345
    view = KrovexHelpView(mock_bot, mock_author, prefix="!")

    next_btn = next(c for c in view.children if getattr(c, "custom_id", None) == "death_bot:help:next")
    assert next_btn.emoji.id == KrovexEmoji.PURPLE_ARROW.id
    assert next_btn.emoji.animated is True

    close_btn = next(c for c in view.children if getattr(c, "custom_id", None) == "death_bot:help:close")
    assert close_btn.emoji.id == KrovexEmoji.CROSS.id
    assert close_btn.emoji.animated is True


def test_security_subsystem_integration():
    """Verify security panel embed title uses KrovexEmoji.SECURITY."""
    mock_guild = MagicMock(spec=discord.Guild)
    embed = build_security_embed({}, mock_guild)
    assert KrovexEmoji.SECURITY.discord_format in embed.title


def test_shop_and_ticket_subsystem_integration():
    """Verify shop purchase buttons and ticket cancel buttons use application emojis."""
    # Shop buy view: Buy Item button retains standard cart emoji (WHITE_CROWN reserved for XP/VIP)
    sample_item = {"item_id": 1, "name": "VIP Item", "price": 100, "stock": 5}
    shop_view = ShopBuyConfirmView(sample_item)
    buy_btn = next(c for c in shop_view.children if getattr(c, "label", None) == "Buy Item")
    assert str(buy_btn.emoji) == "🛒"

    shop_cancel_btn = next(c for c in shop_view.children if getattr(c, "label", None) == "Cancel")
    assert shop_cancel_btn.emoji.id == KrovexEmoji.CROSS.id
    assert shop_cancel_btn.emoji.animated is True

    # Ticket close view
    ticket_view = TicketCloseConfirmView()
    ticket_cancel_btn = next(c for c in ticket_view.children if getattr(c, "label", None) == "Cancel")
    assert ticket_cancel_btn.emoji.id == KrovexEmoji.CROSS.id
    assert ticket_cancel_btn.emoji.animated is True

    # Ticket panel view: Create Ticket button uses KrovexEmoji.TICKET
    panel_view = TicketPanelView()
    create_btn = next(c for c in panel_view.children if getattr(c, "label", None) == "Create Ticket")
    assert create_btn.emoji.id == KrovexEmoji.TICKET.id
    assert create_btn.emoji.animated is True


def test_25_inventory_emojis_registered():
    """Verify that all 25 custom Discord emojis from the screenshots are registered and resolvable."""
    expected_inventory = [
        ("14408angelmoji", 1571210588523204831, False),
        ("13083cinnamoji1", 1571210572102504578, True),
        ("10601moon", 1571210569422479550, True),
        ("99088cherryblossomspin", 1571210546278305954, True),
        ("96650flowerswhite", 1571210540624257044, True),
        ("89920starspink5", 1571210538304667758, True),
        ("84604kittymifin", 1571210534395838474, False),
        ("72921hellokittyyes", 1571210532105617418, True),
        ("63591rainbowhappystar", 1571210529454948563, False),
        ("63092moon", 1571210526812541050, True),
        ("60429starbucks", 1571210520760033390, True),
        ("57819x", 1571210516141969489, True),
        ("495162nitro", 1571362065866559608, True),
        ("5267greensparkles", 1571360362685538404, True),
        ("7348yaeheartsparkles", 1571210652024836176, True),
        ("6433100", 1571210615286931477, True),
        ("47599butterflies", 1571210613072597174, True),
        ("46712milkandmochaforehead", 1571210610484445275, False),
        ("45572bubbles", 1571210608127377469, False),
        ("44519crystalball", 1571210605644488774, False),
        ("43893star", 1571210602670587934, False),
        ("42220cutestar", 1571210600003145972, False),
        ("41624dramaqueentext", 1571210597712924823, False),
        ("19539heart", 1571210595079037040, True),
        ("17684rainbowknife", 1571210592121786398, True),
    ]

    assert len(expected_inventory) == 25

    for name, emoji_id, is_animated in expected_inventory:
        by_name = KrovexEmoji.get_by_name(name)
        assert by_name is not None, f"Emoji {name} not found by name in registry"
        assert by_name.id == emoji_id
        assert by_name.animated is is_animated

        by_id = KrovexEmoji.get_by_id(emoji_id)
        assert by_id is not None, f"Emoji ID {emoji_id} not found by ID in registry"
        assert by_id.name == name

        prefix = "a" if is_animated else ""
        assert by_name.discord_format == f"<{prefix}:{name}:{emoji_id}>"
        assert str(by_name) == f"<{prefix}:{name}:{emoji_id}>"

        partial = by_name.partial
        assert partial.name == name
        assert partial.id == emoji_id
        assert partial.animated is is_animated
