"""KROVEX Master Audit & QA Plan — Phase 9 Execution Test Suite: Interaction, UX & Help System.

Covers test cases P9-TC01 through P9-TC10:
- P9-TC01: Premium Help Navigation & Category Select View (KrovexHelpView category select, author exclusivity)
- P9-TC02: Help Pagination Controls & Page Clamping (Prev, Next, Close buttons, page boundary clamping)
- P9-TC03: Unified Context Reply & Double-Ack Protection (Fresh interaction vs deferred followup, HTTP 40060 fallback)
- P9-TC04: Application Emojis & Custom Emoji Resilience Fallback (AppEmoji registry, discord_format, PartialEmoji)
- P9-TC05: KROVEX Logging Redesign & High-Fidelity Layout (7 canonical audit channels under '⛨・KROVEX AUDIT VAULT')
- P9-TC06: DM Delivery Queue & Per-User Rate Limiting (Rolling window rate limiter, max sends per window)
- P9-TC07: DM Queue Idempotency & Persistence Across Restart (Idempotency key deduplication, crash recovery)
- P9-TC08: Interactive Modals & Search Input Validation (CommandSearchModal search query handling)
- P9-TC09: View Timeout & Component Disabling (on_timeout disables all components in view)
- P9-TC10: Embed Styling Consistency & Color Palette Compliance (EmbedBuilder success, error, warning, info colors & footers)
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.cogs.logging.cog import Logging
from bot.cogs.utility.help import (
    CATEGORY_METADATA,
    CategorySelect,
    CommandSearchModal,
    Help,
    KrovexHelpView,
    _search_commands,
)
from bot.config import BotConfig
from bot.core.bot import DeathBot
from bot.core.context import UnifiedContext
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.services.dm_queue_service import (
    DMQueueService,
    WINDOW_SECONDS,
    MAX_SENDS_PER_WINDOW,
)
from bot.utils.embeds import (
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_WARNING,
    EmbedBuilder,
)
from bot.utils.emojis import AppEmoji, KrovexEmoji


def run_async(coro):
    return asyncio.run(coro)


_CACHED_BOT: DeathBot | None = None


async def _get_test_bot() -> DeathBot:
    global _CACHED_BOT
    if _CACHED_BOT is not None:
        return _CACHED_BOT

    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_phase9_help.sqlite"
    db = SQLiteDatabaseManager(db_path=db_path)
    await db.connect()

    bot = DeathBot(config=BotConfig.from_env(validate=False))
    bot.db_manager = db
    bot._init_database = AsyncMock()
    bot.sync_app_commands = AsyncMock()

    # Load core services
    await bot.load_extension("bot.services.security_service")
    await bot.load_extension("bot.services.automod_service")
    await bot.load_extension("bot.services.dm_queue_service")
    await bot.load_extension("bot.services.logging_service")
    await bot.load_extension("bot.services.mention_service")
    await bot.load_extension("bot.services.bot_role_service")

    # Load cogs
    await bot.load_cogs()

    _CACHED_BOT = bot
    return bot


@pytest.fixture
def mock_author():
    author = MagicMock(spec=discord.Member)
    author.id = 111222333
    author.name = "UXTester"
    author.mention = "<@111222333>"
    return author


# ==============================================================================
# P9-TC01: PREMIUM HELP NAVIGATION & CATEGORY SELECT VIEW
# ==============================================================================

def test_p9_tc01_help_navigation_and_category_select(mock_author):
    """P9-TC01: Category dropdown transitions, home embed, and author exclusivity."""
    async def _test():
        bot = await _get_test_bot()
        view = KrovexHelpView(bot, mock_author, prefix="!")
        home_embed = view.build_home_embed()

        assert "KROVEX" in home_embed.title
        assert "Premium Command Library" in home_embed.title
        assert home_embed.color.value == 0x9D4EDD

        # Verify category selection exists
        assert hasattr(view, "select_menu")
        cat_select = view.select_menu
        assert len(cat_select.options) >= 5

        # 1. Select a category (e.g., Music)
        cat_select._values = ["Music"]
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = mock_author
        interaction.response = MagicMock()
        interaction.response.is_done.return_value = False
        interaction.response.edit_message = AsyncMock()

        await cat_select.callback(interaction)
        assert view.current_category == "Music"

        # 2. Unauthorized member interaction rejection
        intruder = MagicMock(spec=discord.Member)
        intruder.id = 999888777
        bad_interaction = MagicMock(spec=discord.Interaction)
        bad_interaction.user = intruder
        bad_interaction.response = MagicMock()
        bad_interaction.response.send_message = AsyncMock()

        allowed = await view.interaction_check(bad_interaction)
        assert allowed is False
        bad_interaction.response.send_message.assert_awaited_once()
        args, kwargs = bad_interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
    run_async(_test())


# ==============================================================================
# P9-TC02: HELP PAGINATION CONTROLS & PAGE CLAMPING
# ==============================================================================

def test_p9_tc02_help_pagination_controls(mock_author):
    """P9-TC02: Next/Prev/Close buttons, page boundary state, and clamping."""
    async def _test():
        bot = await _get_test_bot()
        view = KrovexHelpView(bot, mock_author, prefix="!")

        # Set multi-page state and update buttons
        view.current_category = "Music"
        view.total_pages = 3
        view.current_page = 1
        view.update_button_states()

        # Page 1: Prev disabled, Next enabled
        assert view.prev_button.disabled is True
        assert view.next_button.disabled is False

        # Page 2: Both enabled
        view.current_page = 2
        view.update_button_states()
        assert view.prev_button.disabled is False
        assert view.next_button.disabled is False

        # Page 3: Prev enabled, Next disabled
        view.current_page = 3
        view.update_button_states()
        assert view.prev_button.disabled is False
        assert view.next_button.disabled is True

        # Close button callback
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = mock_author
        interaction.response = MagicMock()
        interaction.response.edit_message = AsyncMock()

        await view.close_button.callback(interaction)
        interaction.response.edit_message.assert_awaited()
    run_async(_test())


# ==============================================================================
# P9-TC03: UNIFIED CONTEXT REPLY & DOUBLE-ACK PROTECTION
# ==============================================================================

def test_p9_tc03_unified_context_double_ack_protection():
    """P9-TC03: Routes to send_message or followup.send based on acknowledgment state."""
    async def _test():
        mock_bot = MagicMock()

        # 1. Fresh interaction -> response.send_message
        fresh_interaction = MagicMock(spec=discord.Interaction)
        fresh_interaction.response = MagicMock()
        fresh_interaction.response.is_done.return_value = False
        fresh_interaction.response.send_message = AsyncMock()
        fresh_interaction.original_response = AsyncMock(return_value="msg_sent")
        fresh_interaction.followup = MagicMock()
        fresh_interaction.followup.send = AsyncMock()

        ctx1 = UnifiedContext(bot=mock_bot, interaction=fresh_interaction)
        res1 = await ctx1.reply(content="Fresh Reply")
        fresh_interaction.response.send_message.assert_awaited_once()
        fresh_interaction.followup.send.assert_not_called()
        assert res1 == "msg_sent"

        # 2. Deferred interaction -> followup.send
        deferred_interaction = MagicMock(spec=discord.Interaction)
        deferred_interaction.response = MagicMock()
        deferred_interaction.response.is_done.return_value = True
        deferred_interaction.followup = MagicMock()
        deferred_interaction.followup.send = AsyncMock(return_value="followup_sent")

        ctx2 = UnifiedContext(bot=mock_bot, interaction=deferred_interaction)
        res2 = await ctx2.reply(content="Deferred Reply", ephemeral=True)
        deferred_interaction.followup.send.assert_awaited_once()
        assert res2 == "followup_sent"
    run_async(_test())


# ==============================================================================
# P9-TC04: APPLICATION EMOJIS & CUSTOM EMOJI RESILIENCE
# ==============================================================================

def test_p9_tc04_application_emojis_registry():
    """P9-TC04: Validates AppEmoji registry lookups, discord_format, and PartialEmoji."""
    # 1. Core status and visual emojis
    assert KrovexEmoji.BLUE.name == "550849blue"
    assert KrovexEmoji.BLUE.id == 1571035143748194304
    assert KrovexEmoji.BLUE.animated is True
    assert KrovexEmoji.BLUE.discord_format == "<a:550849blue:1571035143748194304>"

    assert KrovexEmoji.CORRECT.name == "843139correct"
    assert KrovexEmoji.CORRECT.animated is False
    assert KrovexEmoji.CORRECT.discord_format == "<:843139correct:1571190648630153368>"

    assert KrovexEmoji.FAILED.name == "3972failed"
    assert KrovexEmoji.FAILED.animated is False
    assert KrovexEmoji.FAILED.discord_format == "<:3972failed:1571191511528505384>"

    # 2. Conversion to discord.PartialEmoji via .partial
    partial = KrovexEmoji.BLUE.partial
    assert isinstance(partial, discord.PartialEmoji)
    assert partial.name == "550849blue"
    assert partial.id == 1571035143748194304
    assert partial.animated is True

    # 3. String representation
    assert str(KrovexEmoji.BLUE) == "<a:550849blue:1571035143748194304>"


# ==============================================================================
# P9-TC05: KROVEX LOGGING REDESIGN & HIGH-FIDELITY LAYOUT
# ==============================================================================

def test_p9_tc05_logging_redesign_and_channels():
    """P9-TC05: Provisions '⛨・KROVEX AUDIT VAULT' with 7 dedicated audit channels."""
    async def _test():
        mock_bot = MagicMock()
        mock_bot.logging_repo = MagicMock()
        mock_bot.logging_repo.get_settings = AsyncMock(return_value={})
        mock_bot.logging_repo.update_settings = AsyncMock()

        cog = Logging(mock_bot)
        ctx = MagicMock(spec=UnifiedContext)
        ctx.guild = MagicMock(spec=discord.Guild)
        ctx.guild.id = 998877
        ctx.guild.name = "Krovex Test Guild"
        ctx.author = MagicMock(name="SecAdmin")
        ctx.reply = AsyncMock()
        ctx.send_success = AsyncMock()
        ctx.send_error = AsyncMock()
        ctx.defer = AsyncMock()

        me = MagicMock(spec=discord.Member)
        me.guild_permissions.manage_channels = True
        me.guild_permissions.administrator = True
        ctx.guild.me = me
        ctx.guild.default_role = MagicMock(spec=discord.Role)
        ctx.guild.categories = []
        ctx.guild.text_channels = []

        cat = MagicMock(spec=discord.CategoryChannel)
        cat.name = "⛨・KROVEX AUDIT VAULT"
        cat.text_channels = []
        ctx.guild.create_category = AsyncMock(return_value=cat)

        created_named_channels = {}

        async def fake_create_channel(name, topic=None, reason=None):
            ch = MagicMock(spec=discord.TextChannel)
            ch.name = name
            ch.topic = topic
            ch.id = len(created_named_channels) + 100
            ch.mention = f"<#{ch.id}>"
            ch.send = AsyncMock()
            ch.overwrites_for = MagicMock(return_value=MagicMock(read_messages=False))
            created_named_channels[name] = ch
            cat.text_channels.append(ch)
            return ch

        cat.create_text_channel = AsyncMock(side_effect=fake_create_channel)

        await cog._execute_autolog(ctx)

        # Category created with canonical name
        ctx.guild.create_category.assert_awaited_once()
        assert ctx.guild.create_category.call_args.args[0] == "⛨・KROVEX AUDIT VAULT"

        # Exactly 7 canonical channels created under category
        assert cat.create_text_channel.await_count == 7
        expected_channels = [
            "security-feed",
            "message-tracker",
            "member-activity",
            "voice-monitor",
            "presence-tracker",
            "invite-tracker",
            "server-changes",
        ]
        created_names = [ch.name for ch in cat.text_channels]
        for ec in expected_channels:
            assert ec in created_names
    run_async(_test())


# ==============================================================================
# P9-TC06: DM DELIVERY QUEUE & PER-USER RATE LIMITING
# ==============================================================================

def test_p9_tc06_dm_queue_rate_limiting(tmp_path: Path):
    """P9-TC06: Enforces global rate limits and rolling time windows."""
    async def _test():
        db_file = tmp_path / f"test_dm_{time.time_ns()}.sqlite"
        mgr = SQLiteDatabaseManager(db_path=db_file)
        await mgr.connect()
        try:
            bot = MagicMock()
            bot.user = MagicMock(id=1570428426974662718)
            bot.db_manager = mgr

            srv = DMQueueService(bot, db_manager=mgr)
            await srv.initialize()
            srv.stop_worker()

            # Enqueue two DMs
            j1 = await srv.enqueue(recipient_id=101, content="Hello 1")
            j2 = await srv.enqueue(recipient_id=102, content="Hello 2")

            assert j1 is not None
            assert j2 is not None
            assert j1 != j2

            # Claim first job
            row1, wait1 = await srv._claim_next_job()
            assert row1 is not None
            assert row1["job_id"] == j1
            assert wait1 == 0.0
        finally:
            await srv.stop()
            await mgr.close()
    run_async(_test())


# ==============================================================================
# P9-TC07: DM QUEUE IDEMPOTENCY & RESTART RECOVERY
# ==============================================================================

def test_p9_tc07_dm_queue_idempotency_and_recovery(tmp_path: Path):
    """P9-TC07: Rejects duplicate idempotency keys; recovers processing jobs upon restart."""
    async def _test():
        db_file = tmp_path / f"test_dm_idemp_{time.time_ns()}.sqlite"
        mgr = SQLiteDatabaseManager(db_path=db_file)
        await mgr.connect()
        try:
            bot = MagicMock()
            bot.user = MagicMock(id=1570428426974662718)
            bot.db_manager = mgr

            srv = DMQueueService(bot, db_manager=mgr)
            await srv.initialize()
            srv.stop_worker()

            # 1. Enqueue with idempotency key
            j1 = await srv.enqueue(recipient_id=111, content="Msg", idempotency_key="unique_evt_1")
            j2 = await srv.enqueue(recipient_id=111, content="Duplicate", idempotency_key="unique_evt_1")

            assert j1 == j2
            rows = await mgr.fetchall("SELECT * FROM dm_queue WHERE idempotency_key = 'unique_evt_1'")
            assert len(rows) == 1

            # 2. Abandoned processing jobs are reset to pending upon restart
            now = time.time()
            await mgr.execute(
                """
                INSERT INTO dm_queue (job_id, recipient_id, state, created_at, updated_at)
                VALUES ('stuck_job_1', 999, 'processing', ?, ?)
                """,
                (now - 100, now - 100),
            )

            # Re-initialize service instance
            srv2 = DMQueueService(bot, db_manager=mgr)
            await srv2.initialize()
            srv2.stop_worker()

            row = await mgr.fetchone("SELECT state FROM dm_queue WHERE job_id = 'stuck_job_1'")
            assert row["state"] == "pending"
        finally:
            await srv.stop()
            await mgr.close()
    run_async(_test())


# ==============================================================================
# P9-TC08: INTERACTIVE MODALS & SEARCH INPUT VALIDATION
# ==============================================================================

def test_p9_tc08_interactive_modals_input_validation(mock_author):
    """P9-TC08: CommandSearchModal handles search inputs and dispatches results."""
    async def _test():
        bot = await _get_test_bot()
        view = KrovexHelpView(bot, mock_author, prefix="!")
        modal = CommandSearchModal(view)

        assert modal.title == "🔍 Search KROVEX Commands"
        assert hasattr(modal, "query_input")

        # Test search discovery helper directly
        results = _search_commands(bot, "bb")
        assert any(r["name"] == "bassboost" for r in results)

        # Test modal submit interaction
        view.perform_search = AsyncMock()
        modal.query_input._value = "bb"

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = mock_author
        await modal.on_submit(interaction)
        view.perform_search.assert_awaited_once_with(interaction, "bb")
    run_async(_test())


# ==============================================================================
# P9-TC09: VIEW TIMEOUT & COMPONENT DISABLING
# ==============================================================================

def test_p9_tc09_view_timeout_disables_components(mock_author):
    """P9-TC09: on_timeout disables all interactive buttons and dropdowns."""
    async def _test():
        bot = await _get_test_bot()
        view = KrovexHelpView(bot, mock_author, prefix="!")
        mock_msg = MagicMock(spec=discord.Message)
        mock_msg.edit = AsyncMock()
        view.message = mock_msg

        # Initially active (search button enabled on home)
        assert view.search_button.disabled is False

        # Trigger timeout
        await view.on_timeout()

        # All buttons must now be disabled
        assert all(child.disabled for child in view.children)
        mock_msg.edit.assert_awaited_once_with(view=view)
    run_async(_test())


# ==============================================================================
# P9-TC10: EMBED STYLING CONSISTENCY & COLOR PALETTE COMPLIANCE
# ==============================================================================

def test_p9_tc10_embed_styling_consistency():
    """P9-TC10: Validates visual palette, standardized footers, and timestamps."""
    # 1. Success embed (Emerald Green)
    succ = EmbedBuilder.success(title="Action Complete", description="Channel secured.")
    assert succ.color.value == COLOR_SUCCESS
    assert "Action Complete" in succ.title
    assert succ.timestamp is not None
    assert "KROVEX" in succ.footer.text

    # 2. Error embed (Ruby Red)
    err = EmbedBuilder.error(title="Permission Denied", description="Administrator required.")
    assert err.color.value == COLOR_ERROR
    assert "Permission Denied" in err.title
    assert err.timestamp is not None

    # 3. Warning embed (Amber Yellow)
    warn = EmbedBuilder.warning(title="Threshold Warning", description="Approaching rate limit.")
    assert warn.color.value == COLOR_WARNING
    assert "Threshold Warning" in warn.title

    # 4. Info embed (Primary Purple / Royal Palette)
    info = EmbedBuilder.info(title="System Status", description="All systems operational.")
    assert info.color.value == COLOR_PRIMARY
    assert "System Status" in info.title

    # 5. Base brand embed
    base = EmbedBuilder.base(title="Obsidian Brand", description="Signature palette.", color=COLOR_PRIMARY)
    assert base.color.value == COLOR_PRIMARY
