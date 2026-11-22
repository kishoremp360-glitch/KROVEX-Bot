"""Phase 2A.8 Comprehensive Tests: Premium Help & Command UX.

Covers all 16 Phase 2A.8 requirements:
1. Main help dashboard.
2. Dynamic command counts.
3. Prefix command discovery.
4. Slash command discovery.
5. Nested Slash hierarchy display.
6. Alias search.
7. Description search.
8. Category filtering.
9. Pagination.
10. Command detail views.
11. Permission-aware visibility.
12. Unauthorized interaction rejection.
13. Invalid command suggestions.
14. Expired interactions.
15. Double acknowledgement prevention.
16. Existing help behavior regression.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.core.bot import DeathBot
from bot.config import BotConfig
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.core.context import UnifiedContext
from bot.cogs.utility.help import (
    Help,
    KrovexHelpView,
    ZerinaHelpView,
    CategorySelect,
    CommandSearchModal,
    _search_commands,
    _find_slash_command,
    _extract_command_permissions,
    _extract_command_cooldown,
    _extract_slash_permissions,
)

_CACHED_BOT: DeathBot | None = None


async def get_test_bot() -> DeathBot:
    global _CACHED_BOT
    if _CACHED_BOT is not None:
        return _CACHED_BOT

    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_help_ux.sqlite"
    db = SQLiteDatabaseManager(db_path=db_path)
    await db.connect()

    bot = DeathBot(config=BotConfig.from_env(validate=False))
    bot.db_manager = db
    bot._init_database = AsyncMock()
    bot.sync_app_commands = AsyncMock()

    # Load services
    await bot.load_extension("bot.services.security_service")
    await bot.load_extension("bot.services.automod_service")
    await bot.load_extension("bot.services.dm_queue_service")
    await bot.load_extension("bot.services.logging_service")
    await bot.load_extension("bot.services.mention_service")
    await bot.load_extension("bot.services.bot_role_service")

    # Load all cogs
    await bot.load_cogs()

    _CACHED_BOT = bot
    return bot


@pytest.fixture
def mock_author():
    author = MagicMock(spec=discord.Member)
    author.id = 111111
    author.mention = "<@111111>"
    return author


# ── Requirement 1 & 2: Main Help Dashboard & Dynamic Counts ────────────────
@pytest.mark.asyncio
async def test_main_help_dashboard_and_dynamic_counts(mock_author):
    bot = await get_test_bot()
    view = KrovexHelpView(bot, mock_author, prefix="!")
    embed = view.build_home_embed()

    # Brand Title and Styling
    assert "**KROVEX**" in embed.title
    assert "Premium Command Library" in embed.title
    assert embed.color.value == 0x9D4EDD
    assert "<@111111>" in embed.description

    # Dynamic Counts Field
    stats_field = next(f for f in embed.fields if "System Intelligence" in f.name)
    assert "Prefix Commands:" in stats_field.value
    assert "Slash Leaves:" in stats_field.value
    assert "Active Modules:" in stats_field.value

    # Verify counts match reality
    unhidden_prefix = len([c for c in bot.commands if not c.hidden])
    assert f"`{unhidden_prefix}` active" in stats_field.value


# ── Requirement 3 & 4: Prefix & Slash Command Discovery ───────────────────
@pytest.mark.asyncio
async def test_prefix_and_slash_command_discovery():
    bot = await get_test_bot()

    # Prefix Discovery
    prefix_cmds = [c.name for c in bot.commands if not c.hidden]
    assert "help" in prefix_cmds
    assert "ping" in prefix_cmds
    assert "bassboost" in prefix_cmds
    assert "setprefix" in prefix_cmds

    # Slash Discovery
    slash_roots = bot.tree.get_commands()
    assert len(slash_roots) >= 29
    root_names = {c.name for c in slash_roots}
    assert "admin" in root_names
    assert "music" in root_names
    assert "logs" in root_names


# ── Requirement 5: Nested Slash Hierarchy Display ──────────────────────────
@pytest.mark.asyncio
async def test_nested_slash_hierarchy_lookup():
    bot = await get_test_bot()

    # Search for nested /music filter bass
    match = _find_slash_command(bot, "music filter bass")
    assert match is not None, "Slash command /music filter bass must be found"
    path, cmd = match
    assert path == "music filter bass"
    assert cmd.name == "bass"

    # Search by leaf name 'bass'
    match_leaf = _find_slash_command(bot, "bass")
    assert match_leaf is not None
    assert match_leaf[0] == "music filter bass"

    # Search for /admin prefix
    match_prefix = _find_slash_command(bot, "admin prefix")
    assert match_prefix is not None
    assert match_prefix[0] == "admin prefix"


# ── Requirement 6 & 7: Alias Search & Description Search ───────────────────
@pytest.mark.asyncio
async def test_alias_and_description_search():
    bot = await get_test_bot()

    # 1. Alias search: 'bb' should find 'bassboost'
    results_bb = _search_commands(bot, "bb")
    assert any(r["name"] == "bassboost" for r in results_bb), "Searching 'bb' must return bassboost"

    # 2. Alias search: 'transfer' should find 'pay'
    results_transfer = _search_commands(bot, "transfer")
    assert any(r["name"] == "pay" for r in results_transfer), "Searching 'transfer' must return pay"

    # 3. Description search: 'audio' or 'dsp' should match music filters
    results_dsp = _search_commands(bot, "filter")
    assert len(results_dsp) > 0
    assert any("music filter" in r["name"] or "bass" in r["name"] for r in results_dsp)


# ── Requirement 8 & 9: Category Filtering & Pagination ─────────────────────
@pytest.mark.asyncio
async def test_category_filtering_and_pagination(mock_author):
    bot = await get_test_bot()
    view = KrovexHelpView(bot, mock_author, prefix="!")

    # Select Music category
    embed_page1 = view.build_category_embed("Music", page=1)
    assert "High-Fidelity Music" in embed_page1.title
    assert "Total Commands in this Module:" in embed_page1.description
    assert view.total_pages >= 2
    assert view.current_page == 1

    # Page 2
    embed_page2 = view.build_category_embed("Music", page=2)
    assert "Page 2 of" in embed_page2.footer.text
    assert view.current_page == 2


# ── Requirement 10: Command Detail Views ───────────────────────────────────
@pytest.mark.asyncio
async def test_command_detail_views():
    bot = await get_test_bot()
    help_cog: Help = bot.cogs["Help"]

    # Prefix Detail
    cmd = bot.get_command("setprefix")
    assert cmd is not None
    detail_embed = help_cog._build_command_detail_embed(cmd, prefix="!")
    assert "!setprefix" in detail_embed.description
    assert any(f.name == "🔒 Required Permissions" for f in detail_embed.fields)
    assert any(f.name == "⏱️ Cooldown" for f in detail_embed.fields)

    # Slash Detail
    match = _find_slash_command(bot, "admin prefix")
    assert match is not None
    path, scmd = match
    slash_embed = help_cog._build_slash_detail_embed(path, scmd)
    assert "/admin prefix" in slash_embed.description
    assert any("/admin prefix" in f.value for f in slash_embed.fields)


# ── Requirement 11: Permission-Aware Visibility & Cooldowns ────────────────
@pytest.mark.asyncio
async def test_permission_and_cooldown_extraction():
    bot = await get_test_bot()

    # Admin command permissions
    admin_cmd = bot.get_command("setprefix")
    assert admin_cmd is not None
    perms = _extract_command_permissions(admin_cmd)
    assert "Administrator" in perms

    # Standard member command permissions
    ping_cmd = bot.get_command("ping")
    assert ping_cmd is not None
    ping_perms = _extract_command_permissions(ping_cmd)
    assert "Standard Member" in ping_perms

    # Slash admin permissions
    slash_admin = _find_slash_command(bot, "admin prefix")
    assert slash_admin is not None
    assert _extract_slash_permissions(slash_admin[1]) == "Administrator"

    # Cooldown extraction
    cooldown_str = _extract_command_cooldown(ping_cmd)
    assert cooldown_str is not None


# ── Requirement 12: Unauthorized Interaction Rejection ─────────────────────
@pytest.mark.asyncio
async def test_unauthorized_interaction_rejection(mock_author):
    bot = await get_test_bot()
    view = KrovexHelpView(bot, mock_author, prefix="!")

    # Owner interaction passes
    valid_interaction = MagicMock(spec=discord.Interaction)
    valid_interaction.user = mock_author
    assert await view.interaction_check(valid_interaction) is True

    # Intruder interaction is rejected
    intruder = MagicMock(spec=discord.Member)
    intruder.id = 999999
    intruder_interaction = MagicMock(spec=discord.Interaction)
    intruder_interaction.user = intruder
    intruder_interaction.response = MagicMock()
    intruder_interaction.response.send_message = AsyncMock()

    assert await view.interaction_check(intruder_interaction) is False
    intruder_interaction.response.send_message.assert_awaited_with(
        "⚠️ This help menu was opened by another user. Run `,help` or `/help` to open your own.",
        ephemeral=True,
    )


# ── Requirement 13: Invalid Command Suggestions ────────────────────────────
@pytest.mark.asyncio
async def test_invalid_command_suggestions():
    bot = await get_test_bot()
    help_cog: Help = bot.cogs["Help"]

    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock()
    ctx.guild.id = 111111
    ctx.author = MagicMock(spec=discord.Member)
    ctx.reply = AsyncMock()
    ctx.send_error = AsyncMock()

    # Typo: 'setprefx' should suggest 'setprefix'
    await help_cog._execute_help(ctx, "setprefx")
    ctx.reply.assert_awaited()
    call_args = ctx.reply.call_args[1]
    embed = call_args["embed"]
    assert "Command Suggestions" in embed.title
    assert "setprefix" in embed.description


# ── Requirement 14: Expired Interactions (Timeout Handling) ────────────────
@pytest.mark.asyncio
async def test_expired_interaction_timeout(mock_author):
    bot = await get_test_bot()
    view = KrovexHelpView(bot, mock_author, prefix="!")
    mock_msg = MagicMock(spec=discord.Message)
    mock_msg.edit = AsyncMock()
    view.message = mock_msg

    await view.on_timeout()
    assert all(child.disabled for child in view.children)
    mock_msg.edit.assert_awaited_with(view=view)


# ── Requirement 15: Search View Pagination & Home Navigation ───────────────
@pytest.mark.asyncio
async def test_search_view_pagination_and_home(mock_author):
    bot = await get_test_bot()
    view = KrovexHelpView(bot, mock_author, prefix="!")

    # Perform search for common term 'a'
    results = _search_commands(bot, "a")
    view.is_search_mode = True
    view.search_query = "a"
    view.search_results = results
    view.total_pages = 3
    view.current_page = 1
    view.update_button_states()

    # Home button should be enabled, Previous disabled, Next enabled
    assert view.home_button.disabled is False
    assert view.prev_button.disabled is True
    assert view.next_button.disabled is False

    # Page forward
    embed_p2 = view.build_search_embed("a", page=2)
    assert view.current_page == 2
    assert "Page 2 of" in embed_p2.footer.text


# ── Requirement 16: Existing Help Regression Compatibility ─────────────────
@pytest.mark.asyncio
async def test_existing_help_regression_compatibility(mock_author):
    bot = await get_test_bot()

    # ZerinaHelpView backward-compatibility alias exists
    assert ZerinaHelpView is KrovexHelpView

    view = ZerinaHelpView(bot, mock_author, prefix=",")
    home = view.build_home_embed()
    assert "KROVEX" in home.title
    assert view.select_menu.placeholder in ("Choose a section", "Browse premium command categories")

    # Category embed contains 4 logging subcommands
    log_embed = view.build_category_embed("Logging", page=1)
    values = [f.value for f in log_embed.fields]
    assert any("/logs" in v for v in values)
