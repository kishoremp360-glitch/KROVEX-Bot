"""Comprehensive automated tests for KROVEX Phase 2A: Global DM Queue & Rate Limiter.

Verifies:
1. Two successful DMs within the eligible window (sent immediately).
2. Third DM waits for the oldest send to leave the rolling 60s window.
3. Global rate limit enforced across multiple guilds.
4. Concurrent worker protection / lock integrity.
5. Restart recovery: abandoned 'processing' jobs restored to 'pending'.
6. Persistent rate-limit timestamps survive restart.
7. Idempotency key prevents duplicate job insertion.
8. Discord HTTP 429 Retry-After handling (backoff, no slot consumed, paused dispatch).
9. Blocked DM handling (discord.Forbidden marks failed without consuming slot).
10. Invalid recipient handling (discord.NotFound marks failed without consuming slot).
11. Transient network failure retries with exponential backoff.
12. Strict FIFO ordering (oldest created_at jobs dispatched first).
13. Failed deliveries never consume successful-send slots.
14. Clean worker startup, shutdown, and cancellation.
15. Mention notification integration with DM queue.
16. Welcome service integration with DM queue.
17. Regression protection: logging spam prevention (bot voice events & audit channels ignored).
18. Regression protection: username formatting priority.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.services.dm_queue_service import (
    DMQueueService,
    WINDOW_SECONDS,
    MAX_SENDS_PER_WINDOW,
)
from bot.services.mention_service import MentionService
from bot.services.welcome_service import WelcomeService
from bot.services.logging_service import LoggingService


async def _create_test_env(tmp_path: Path):
    """Helper to initialize isolated SQLite database, mock bot, and DMQueueService."""
    db_file = tmp_path / f"test_dm_{time.time_ns()}.sqlite"
    mgr = SQLiteDatabaseManager(db_path=db_file)
    await mgr.connect()

    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.db_manager = mgr
    bot.db = mgr
    bot.get_user = MagicMock()
    bot.fetch_user = AsyncMock()

    service = DMQueueService(bot, db_manager=mgr)
    await service.initialize()
    service.stop_worker()  # Stop automatic worker so tests control dispatch deterministically

    return mgr, bot, service


# ── TEST 1: Two successful DMs within eligible window ─────────────────────────

@pytest.mark.asyncio
async def test_two_successful_dms_within_eligible_window(tmp_path):
    """Two DMs are eligible to send immediately in a fresh 60s rolling window."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        user1 = MagicMock(spec=discord.User)
        user1.send = AsyncMock()
        user2 = MagicMock(spec=discord.User)
        user2.send = AsyncMock()

        bot.get_user.side_effect = lambda uid: user1 if uid == 101 else user2

        j1 = await srv.enqueue(recipient_id=101, content="Hello 1")
        j2 = await srv.enqueue(recipient_id=102, content="Hello 2")

        # Claim & dispatch 1
        row1, wait1 = await srv._claim_next_job()
        assert row1 is not None and row1["job_id"] == j1
        assert wait1 == 0.0
        await srv._dispatch_job(row1)
        user1.send.assert_awaited_once_with(content="Hello 1")

        # Claim & dispatch 2
        row2, wait2 = await srv._claim_next_job()
        assert row2 is not None and row2["job_id"] == j2
        assert wait2 == 0.0
        await srv._dispatch_job(row2)
        user2.send.assert_awaited_once_with(content="Hello 2")

        stats = await srv.get_stats()
        assert stats["sent"] == 2
        assert stats["window_sends"] == 2
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 2: Third DM waits for oldest send to leave window ────────────────────

@pytest.mark.asyncio
async def test_third_dm_waits_for_oldest_send(tmp_path):
    """Third DM cannot send until the oldest timestamp exits the 60s rolling window."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        user = MagicMock(spec=discord.User)
        user.send = AsyncMock()
        bot.get_user.return_value = user

        await srv.enqueue(recipient_id=101, content="DM 1")
        await srv.enqueue(recipient_id=102, content="DM 2")
        await srv.enqueue(recipient_id=103, content="DM 3")

        r1, _ = await srv._claim_next_job()
        await srv._dispatch_job(r1)
        r2, _ = await srv._claim_next_job()
        await srv._dispatch_job(r2)

        # Now 2 sends in window; claiming 3rd must return None and wait_seconds > 0
        r3, wait3 = await srv._claim_next_job()
        assert r3 is None
        assert wait3 > 0.0
        assert wait3 <= 60.0
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 3: Global limit across multiple guilds ───────────────────────────────

@pytest.mark.asyncio
async def test_global_limit_across_multiple_guilds(tmp_path):
    """The 2 sends per 60s limit is global across different guilds."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        user = MagicMock(spec=discord.User)
        user.send = AsyncMock()
        bot.get_user.return_value = user

        await srv.enqueue(recipient_id=101, guild_id=111111, content="Guild 1 Msg")
        await srv.enqueue(recipient_id=102, guild_id=222222, content="Guild 2 Msg")
        await srv.enqueue(recipient_id=103, guild_id=333333, content="Guild 3 Msg")

        r1, _ = await srv._claim_next_job()
        await srv._dispatch_job(r1)
        r2, _ = await srv._claim_next_job()
        await srv._dispatch_job(r2)

        # Third job from Guild 3 is blocked by global rate limit
        r3, wait = await srv._claim_next_job()
        assert r3 is None
        assert wait > 0.0
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 4: Concurrent worker protection ─────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_worker_protection(tmp_path):
    """Simultaneous claims do not double-claim or exceed limits."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        user = MagicMock(spec=discord.User)
        user.send = AsyncMock()
        bot.get_user.return_value = user

        await srv.enqueue(recipient_id=101, content="Concurrent 1")
        await srv.enqueue(recipient_id=102, content="Concurrent 2")

        c1, c2 = await asyncio.gather(
            srv._claim_next_job(),
            srv._claim_next_job(),
        )

        claimed_jobs = [c[0]["job_id"] for c in [c1, c2] if c[0] is not None]
        assert len(claimed_jobs) == 2
        assert claimed_jobs[0] != claimed_jobs[1]
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 5: Restart recovery of abandoned processing jobs ─────────────────────

@pytest.mark.asyncio
async def test_restart_recovery_of_processing_jobs(tmp_path):
    """Jobs left in 'processing' upon unexpected restart are reset to 'pending'."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        now = time.time()
        await mgr.execute(
            """
            INSERT INTO dm_queue (job_id, recipient_id, state, created_at, updated_at)
            VALUES ('stuck_job_1', 999, 'processing', ?, ?)
            """,
            (now - 100, now - 100)
        )

        await srv.initialize()
        srv.stop_worker()

        row = await mgr.fetchone("SELECT state FROM dm_queue WHERE job_id = 'stuck_job_1'")
        assert row["state"] == "pending"
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 6: Persistent rate-limit timestamps survive restart ──────────────────

@pytest.mark.asyncio
async def test_rate_limit_timestamps_survive_restart(tmp_path):
    """Timestamps in dm_rate_limit_log constrain sends even after service re-instantiation."""
    db_file = tmp_path / "test_restart_rate.sqlite"
    mgr = SQLiteDatabaseManager(db_path=db_file)
    await mgr.connect()

    bot = MagicMock()
    bot.user.id = 1570428426974662718
    bot.db_manager = mgr

    now = time.time()
    await mgr.execute("INSERT INTO dm_rate_limit_log (recipient_id, sent_at) VALUES (1, ?)", (now - 20,))
    await mgr.execute("INSERT INTO dm_rate_limit_log (recipient_id, sent_at) VALUES (2, ?)", (now - 10,))

    # Instantiate brand new service instance
    new_srv = DMQueueService(bot, db_manager=mgr)
    await new_srv.initialize()
    new_srv.stop_worker()

    try:
        await new_srv.enqueue(recipient_id=3, content="After Restart")
        row, wait = await new_srv._claim_next_job()
        assert row is None
        # Must wait until oldest send (now - 20s) rolls out at now + 40s
        assert 35.0 <= wait <= 45.0
    finally:
        await new_srv.stop()
        await mgr.close()


# ── TEST 7: Duplicate idempotency keys ────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_idempotency_keys(tmp_path):
    """Enqueuing with identical idempotency_key returns original job without duplicate insert."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        j1 = await srv.enqueue(recipient_id=111, content="Msg", idempotency_key="unique_evt_1")
        j2 = await srv.enqueue(recipient_id=111, content="Duplicate", idempotency_key="unique_evt_1")

        assert j1 == j2
        rows = await mgr.fetchall("SELECT * FROM dm_queue WHERE idempotency_key = 'unique_evt_1'")
        assert len(rows) == 1
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 8: HTTP 429 Retry-After handling ─────────────────────────────────────

@pytest.mark.asyncio
async def test_http_429_retry_after_handling(tmp_path):
    """HTTP 429 pauses dispatcher for retry_after without marking sent or consuming a slot."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        user = MagicMock(spec=discord.User)
        rate_err = discord.HTTPException(MagicMock(status=429), "Too Many Requests")
        rate_err.status = 429
        rate_err.retry_after = 8.5
        user.send = AsyncMock(side_effect=rate_err)
        bot.get_user.return_value = user

        j1 = await srv.enqueue(recipient_id=101, content="Hit 429")
        row, _ = await srv._claim_next_job()
        await srv._dispatch_job(row)

        db_job = await mgr.fetchone("SELECT state, backoff_until FROM dm_queue WHERE job_id = ?", (j1,))
        assert db_job["state"] == "pending"
        assert db_job["backoff_until"] > time.time()

        rate_logs = await mgr.fetchall("SELECT * FROM dm_rate_limit_log")
        assert len(rate_logs) == 0
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 9: Blocked DM handling (discord.Forbidden) ───────────────────────────

@pytest.mark.asyncio
async def test_blocked_dm_forbidden_handling(tmp_path):
    """discord.Forbidden marks job as failed without consuming a successful send slot."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        user = MagicMock(spec=discord.User)
        user.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "Cannot send messages to this user"))
        bot.get_user.return_value = user

        j1 = await srv.enqueue(recipient_id=202, content="Forbidden test")
        row, _ = await srv._claim_next_job()
        await srv._dispatch_job(row)

        db_job = await mgr.fetchone("SELECT state, error_message FROM dm_queue WHERE job_id = ?", (j1,))
        assert db_job["state"] == "failed"
        assert "Forbidden" in db_job["error_message"]

        rate_logs = await mgr.fetchall("SELECT * FROM dm_rate_limit_log")
        assert len(rate_logs) == 0
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 10: Invalid recipient handling (discord.NotFound) ────────────────────

@pytest.mark.asyncio
async def test_invalid_recipient_not_found_handling(tmp_path):
    """discord.NotFound marks job as failed without infinite retries."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        bot.get_user.return_value = None
        bot.fetch_user = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "Unknown User"))

        j1 = await srv.enqueue(recipient_id=999999999, content="Invalid User")
        row, _ = await srv._claim_next_job()
        await srv._dispatch_job(row)

        db_job = await mgr.fetchone("SELECT state, error_message FROM dm_queue WHERE job_id = ?", (j1,))
        assert db_job["state"] == "failed"
        assert "NotFound" in db_job["error_message"]
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 11: Transient failure retries ────────────────────────────────────────

@pytest.mark.asyncio
async def test_transient_failure_retries(tmp_path):
    """Transient errors increment attempts and apply exponential backoff."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        user = MagicMock(spec=discord.User)
        user.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "Internal Server Error"))
        bot.get_user.return_value = user

        j1 = await srv.enqueue(recipient_id=303, content="Transient test", max_attempts=3)
        row, _ = await srv._claim_next_job()
        await srv._dispatch_job(row)

        db_job = await mgr.fetchone("SELECT state, attempts, backoff_until FROM dm_queue WHERE job_id = ?", (j1,))
        assert db_job["state"] == "pending"
        assert db_job["attempts"] == 1
        assert db_job["backoff_until"] > time.time()
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 12: FIFO behavior ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fifo_ordering(tmp_path):
    """Older created_at jobs are claimed strictly before newer ones."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        now = time.time()
        await mgr.execute(
            "INSERT INTO dm_queue (job_id, recipient_id, state, created_at, updated_at) VALUES ('job_b', 2, 'pending', ?, ?)",
            (now - 10, now - 10)
        )
        await mgr.execute(
            "INSERT INTO dm_queue (job_id, recipient_id, state, created_at, updated_at) VALUES ('job_a', 1, 'pending', ?, ?)",
            (now - 20, now - 20)
        )

        r1, _ = await srv._claim_next_job()
        assert r1["job_id"] == "job_a"  # Oldest first

        r2, _ = await srv._claim_next_job()
        assert r2["job_id"] == "job_b"
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 13: Failed jobs do not consume successful send slots ─────────────────

@pytest.mark.asyncio
async def test_failed_jobs_do_not_consume_slots(tmp_path):
    """A failed job leaves both send slots open for subsequent pending jobs."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        blocked_user = MagicMock(spec=discord.User)
        blocked_user.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "Forbidden"))
        good_user1 = MagicMock(spec=discord.User)
        good_user1.send = AsyncMock()
        good_user2 = MagicMock(spec=discord.User)
        good_user2.send = AsyncMock()

        bot.get_user.side_effect = lambda uid: blocked_user if uid == 1 else (good_user1 if uid == 2 else good_user2)

        await srv.enqueue(recipient_id=1, content="Fail DM")
        await srv.enqueue(recipient_id=2, content="Good DM 1")
        await srv.enqueue(recipient_id=3, content="Good DM 2")

        # 1. Fail
        r1, _ = await srv._claim_next_job()
        await srv._dispatch_job(r1)

        # 2. Good 1
        r2, wait2 = await srv._claim_next_job()
        assert r2 is not None and wait2 == 0.0
        await srv._dispatch_job(r2)

        # 3. Good 2 (still eligible because Job 1 failed and consumed no slot!)
        r3, wait3 = await srv._claim_next_job()
        assert r3 is not None and wait3 == 0.0
        await srv._dispatch_job(r3)

        stats = await srv.get_stats()
        assert stats["failed"] == 1
        assert stats["sent"] == 2
        assert stats["window_sends"] == 2
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 14: Worker startup and shutdown ──────────────────────────────────────

@pytest.mark.asyncio
async def test_worker_startup_and_shutdown(tmp_path):
    """Worker task initializes cleanly, processes, and cancels gracefully."""
    db_file = tmp_path / "test_worker_lifecycle.sqlite"
    mgr = SQLiteDatabaseManager(db_path=db_file)
    await mgr.connect()
    bot = MagicMock()
    bot.user.id = 1570428426974662718
    bot.db_manager = mgr

    srv = DMQueueService(bot, db_manager=mgr)
    await srv.initialize()
    assert srv._running is True
    assert srv._worker_task is not None and not srv._worker_task.done()

    await srv.stop()
    assert srv._running is False
    assert srv._worker_task is None
    await mgr.close()


# ── TEST 15: Mention notification integration ─────────────────────────────────

@pytest.mark.asyncio
async def test_mention_service_routes_through_dm_queue(tmp_path):
    """MentionService enqueues outgoing notifications via dm_queue_service."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        bot.dm_queue_service = srv
        mention_srv = MentionService(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 998877
        guild.name = "Test Guild"

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 112233
        channel.name = "general"
        channel.guild = guild
        channel.jump_url = "https://discord.com/channels/998877/112233/555"

        target = MagicMock(spec=discord.Member)
        target.id = 777666
        target.bot = False
        target.name = "TargetUser"

        author = MagicMock(spec=discord.Member)
        author.id = 111222
        author.bot = False
        author.name = "Sender"

        msg = MagicMock(spec=discord.Message)
        msg.id = 555
        msg.guild = guild
        msg.channel = channel
        msg.author = author
        msg.created_at = datetime.now(timezone.utc)
        msg.content = "Hey <@777666> check this!"
        msg.mentions = [target]
        msg.role_mentions = []
        msg.mention_everyone = False
        msg.jump_url = "https://discord.com/channels/998877/112233/555"

        channel.permissions_for.return_value = MagicMock(read_messages=True, view_channel=True)
        bot.mention_repo = MagicMock()
        bot.mention_repo.is_enabled = AsyncMock(return_value=True)

        await mention_srv.on_message(msg)

        stats = await srv.get_stats()
        assert stats["pending"] == 1
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 16: Welcome service integration ──────────────────────────────────────

@pytest.mark.asyncio
async def test_welcome_service_routes_through_dm_queue(tmp_path):
    """WelcomeService enqueues welcome DMs via dm_queue_service."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        bot.dm_queue_service = srv
        welcome_repo = MagicMock()
        welcome_settings = MagicMock()
        welcome_settings.send_welcome = False
        welcome_settings.dm_enabled = True
        welcome_settings.dm_template = "Welcome {user} to {server}!"
        welcome_repo.get_or_create = AsyncMock(return_value=welcome_settings)

        welcome_srv = WelcomeService(bot, welcome_repo)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 554433
        guild.name = "Join Guild"
        guild.icon = None

        member = MagicMock(spec=discord.Member)
        member.id = 998811
        member.guild = guild
        member.name = "NewJoiner"
        member.mention = "<@998811>"
        member.display_name = "NewJoiner"

        await welcome_srv.handle_member_join(member)

        stats = await srv.get_stats()
        assert stats["pending"] == 1
    finally:
        await srv.stop()
        await mgr.close()


# ── TEST 17: Regression protection for logging spam prevention ───────────────

@pytest.mark.asyncio
async def test_logging_spam_protections_intact():
    """Verify logging service retains voice self-logging and audit channel protections."""
    bot = MagicMock()
    bot.user.id = 1570428426974662718
    bot.logging_repo = MagicMock()

    log_srv = LoggingService(bot)
    log_srv._emit_log = AsyncMock()

    # 1. Voice self-logging suppression
    bot_member = MagicMock(spec=discord.Member)
    bot_member.id = bot.user.id
    before = MagicMock(spec=discord.VoiceState)
    after = MagicMock(spec=discord.VoiceState)
    await log_srv.on_voice_state_update(bot_member, before, after)
    log_srv._emit_log.assert_not_called()

    # 2. Audit channel ignore check
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1234
    audit_channel = MagicMock(spec=discord.TextChannel)
    audit_channel.id = 555666
    bot.logging_repo.get_settings = AsyncMock(return_value={"message_log_channel": 555666})
    bot.logging_repo.get_filters = AsyncMock(return_value=[])

    assert await log_srv._is_channel_ignored(guild, audit_channel) is True


# ── TEST 18: Regression protection for username formatting priority ───────────

@pytest.mark.asyncio
async def test_username_formatting_priority_intact():
    """Verify display formatting priority: Nickname -> Global Name -> Username -> Fallback."""
    bot = MagicMock()
    log_srv = LoggingService(bot)

    # Priority 1: Nickname
    m = MagicMock(spec=discord.Member)
    m.display_name = "Nick"
    m.name = "handle"
    disp, handle = await log_srv._format_user(m)
    assert disp == "Nick" and handle == "@handle"

    # Priority 4: Fallback
    disp_unk, handle_unk = await log_srv._format_user(None)
    assert disp_unk == "Unknown User" and handle_unk == "@unknown"


# ==============================================================================
# PHASE 2A.1 TESTS: TICKET CLOSURE DM QUEUE INTEGRATION & PERSISTENT VIEWS
# ==============================================================================

from bot.cogs.tickets.views import TicketCloseConfirmView, TicketRatingView
from bot.cogs.tickets.cog import TicketsCog


@pytest.mark.asyncio
async def test_ticket_closure_dm_enters_central_queue(tmp_path):
    """Closing a ticket enqueues the rating DM via central queue with metadata."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        bot.dm_queue_service = srv
        bot.ticket_repo = MagicMock()
        bot.ticket_repo.close_ticket = AsyncMock()
        bot.ticket_repo.get_settings = AsyncMock(return_value={})
        bot.ticket_repo.get_ticket_by_channel = AsyncMock(return_value={
            "id": 42,
            "channel_id": 888777,
            "creator_id": 999111,
            "status": "open",
        })

        guild = MagicMock(spec=discord.Guild)
        guild.id = 1001
        guild.name = "Support Hub"

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 888777
        channel.name = "ticket-0042"
        channel.send = AsyncMock()
        channel.delete = AsyncMock()

        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = guild
        interaction.guild_id = 1001
        interaction.channel = channel
        interaction.user = MagicMock(spec=discord.Member)
        interaction.client = bot
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.response.is_done.return_value = False

        confirm_view = TicketCloseConfirmView()
        button = MagicMock(spec=discord.ui.Button)

        # Execute closure confirm
        with patch("asyncio.sleep", AsyncMock()):  # Skip 5s deletion sleep
            await confirm_view.confirm_btn.callback(interaction)

        stats = await srv.get_stats()
        assert stats["pending"] == 1

        row = await mgr.fetchone("SELECT * FROM dm_queue WHERE recipient_id = 999111")
        assert row is not None
        assert row["message_type"] == "ticket_rating"
        meta = json.loads(row["metadata"])
        assert meta["channel_id"] == 888777
        assert meta["guild_id"] == 1001
    finally:
        await srv.stop()
        await mgr.close()


@pytest.mark.asyncio
async def test_ticket_rating_view_reconstruction_and_all_five_buttons(tmp_path):
    """Claiming and dispatching a ticket rating job reconstructs TicketRatingView with all 5 buttons."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        user = MagicMock(spec=discord.User)
        user.send = AsyncMock()
        bot.get_user.return_value = user

        job_id = await srv.enqueue(
            recipient_id=555,
            guild_id=1001,
            message_type="ticket_rating",
            content="Please rate your ticket",
            metadata={"channel_id": 777, "guild_id": 1001},
        )

        row, _ = await srv._claim_next_job()
        await srv._dispatch_job(row)

        user.send.assert_awaited_once()
        kwargs = user.send.call_args.kwargs
        view = kwargs.get("view")
        assert view is not None
        assert view.__class__.__name__ == "TicketRatingView"
        assert view.channel_id == 777
        assert view.guild_id == 1001

        # Verify all 5 buttons exist, have labels '1 ⭐'..'5 ⭐', and custom_ids
        buttons = [item for item in view.children if isinstance(item, discord.ui.Button)]
        assert len(buttons) == 5

        for star, btn in enumerate(buttons, 1):
            assert btn.label == f"{star} ⭐"
            assert btn.custom_id == f"ticket_rate:777:{star}"
            if star == 5:
                assert btn.style == discord.ButtonStyle.success
            else:
                assert btn.style == discord.ButtonStyle.secondary
    finally:
        await srv.stop()
        await mgr.close()


@pytest.mark.asyncio
async def test_ticket_rating_all_five_callbacks_functional():
    """Verify all five rating button callbacks execute and update repository."""
    view = TicketRatingView(channel_id=999, guild_id=1001)

    for stars in range(1, 6):
        bot = MagicMock()
        bot.ticket_repo = MagicMock()
        bot.ticket_repo.get_ticket_by_channel = AsyncMock(return_value={"creator_id": 55555, "rating": None})
        bot.ticket_repo.set_rating = AsyncMock()

        interaction = MagicMock(spec=discord.Interaction)
        interaction.client = bot
        interaction.user = MagicMock(id=55555)
        interaction.response.is_done.return_value = False
        interaction.response.edit_message = AsyncMock()

        # Call the specific button callback r1..r5
        cb = getattr(view, f"r{stars}")
        await cb.callback(interaction)

        bot.ticket_repo.set_rating.assert_awaited_once_with(999, stars)
        interaction.response.edit_message.assert_awaited_once()
        call_kwargs = interaction.response.edit_message.call_args.kwargs
        assert call_kwargs["view"] is None
        embed = call_kwargs["embed"]
        assert f"{stars} / 5 stars" in embed.description


@pytest.mark.asyncio
async def test_ticket_dm_survives_restart_and_recovery(tmp_path):
    """Ticket DM job in 'processing' state is recovered on restart and dispatched with reconstructed view."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        user = MagicMock(spec=discord.User)
        user.send = AsyncMock()
        bot.get_user.return_value = user

        await srv.enqueue(
            recipient_id=777,
            guild_id=1001,
            message_type="ticket_rating",
            content="Rate experience",
            metadata={"channel_id": 888, "guild_id": 1001},
        )

        # Claim into processing
        row, _ = await srv._claim_next_job()
        assert row["state"] == "pending"  # row fetched before DB update was committed
        # Verify in DB it's processing
        db_row = await mgr.fetchone("SELECT state FROM dm_queue WHERE recipient_id = 777")
        assert db_row["state"] == "processing"

        # Simulate abrupt restart
        await srv.stop()
        new_srv = DMQueueService(bot, db_manager=mgr)
        await new_srv.initialize()
        new_srv.stop_worker()

        # Recovered to pending
        db_recovered = await mgr.fetchone("SELECT state FROM dm_queue WHERE recipient_id = 777")
        assert db_recovered["state"] == "pending"

        # Now claim and dispatch cleanly
        rec_row, _ = await new_srv._claim_next_job()
        assert rec_row is not None
        await new_srv._dispatch_job(rec_row)

        user.send.assert_awaited_once()
        view = user.send.call_args.kwargs.get("view")
        assert view is not None
        assert view.__class__.__name__ == "TicketRatingView"
        assert view.channel_id == 888

        await new_srv.stop()
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_duplicate_ticket_notifications_prevented(tmp_path):
    """Duplicate ticket notifications with identical idempotency key are rejected."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        j1 = await srv.enqueue(
            recipient_id=123,
            message_type="ticket_rating",
            idempotency_key="ticket_rating:1001:555:123",
            metadata={"channel_id": 555},
        )
        j2 = await srv.enqueue(
            recipient_id=123,
            message_type="ticket_rating",
            idempotency_key="ticket_rating:1001:555:123",
            metadata={"channel_id": 555},
        )

        assert j1 == j2
        rows = await mgr.fetchall("SELECT * FROM dm_queue WHERE idempotency_key = 'ticket_rating:1001:555:123'")
        assert len(rows) == 1
    finally:
        await srv.stop()
        await mgr.close()


@pytest.mark.asyncio
async def test_missing_deleted_ticket_handling():
    """Rating callback handles deleted/missing ticket record gracefully."""
    view = TicketRatingView(channel_id=999999, guild_id=1001)

    bot = MagicMock()
    bot.ticket_repo = MagicMock()
    # Missing ticket: get_ticket_by_channel returns None
    bot.ticket_repo.get_ticket_by_channel = AsyncMock(return_value=None)
    bot.ticket_repo.set_rating = AsyncMock(return_value=False)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.client = bot
    interaction.user = MagicMock(id=11111)
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()

    await view.r5.callback(interaction)

    # Handled cleanly without raising exceptions; acknowledged with error
    interaction.response.send_message.assert_awaited_once()
    assert "not found" in interaction.response.send_message.call_args[0][0]
    bot.ticket_repo.set_rating.assert_not_called()


@pytest.mark.asyncio
async def test_missing_recipient_handling(tmp_path):
    """When ticket creator has deleted account, job is marked permanently failed without retry loops."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        bot.get_user.return_value = None
        bot.fetch_user = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "Unknown User"))

        j1 = await srv.enqueue(
            recipient_id=9999999,
            message_type="ticket_rating",
            metadata={"channel_id": 111},
        )

        row, _ = await srv._claim_next_job()
        await srv._dispatch_job(row)

        db_row = await mgr.fetchone("SELECT state, error_message FROM dm_queue WHERE job_id = ?", (j1,))
        assert db_row["state"] == "failed"
        assert "NotFound" in db_row["error_message"]
    finally:
        await srv.stop()
        await mgr.close()


@pytest.mark.asyncio
async def test_ticket_dm_respects_global_rate_limit(tmp_path):
    """Ticket DM must wait when rolling 60s window already has 2 sends."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        user = MagicMock(spec=discord.User)
        user.send = AsyncMock()
        bot.get_user.return_value = user

        # Send 2 DMs
        await srv.enqueue(recipient_id=1, content="DM 1")
        await srv.enqueue(recipient_id=2, content="DM 2")
        await srv.enqueue(recipient_id=3, message_type="ticket_rating", metadata={"channel_id": 10})

        r1, _ = await srv._claim_next_job()
        await srv._dispatch_job(r1)
        r2, _ = await srv._claim_next_job()
        await srv._dispatch_job(r2)

        # 3rd job is ticket DM; rate limited!
        r3, wait3 = await srv._claim_next_job()
        assert r3 is None
        assert wait3 > 0.0
    finally:
        await srv.stop()
        await mgr.close()


@pytest.mark.asyncio
async def test_ticket_dm_does_not_bypass_other_queued_notifications(tmp_path):
    """Ticket DMs preserve FIFO queue order and cannot bypass earlier queued mentions."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        now = time.time()
        # Enqueue mention first, ticket DM second
        await mgr.execute(
            """
            INSERT INTO dm_queue (job_id, recipient_id, message_type, content, state, created_at, updated_at)
            VALUES ('mention_job', 101, 'mention', 'Mentioned!', 'pending', ?, ?)
            """,
            (now - 10, now - 10)
        )
        await mgr.execute(
            """
            INSERT INTO dm_queue (job_id, recipient_id, message_type, metadata, state, created_at, updated_at)
            VALUES ('ticket_job', 102, 'ticket_rating', '{"channel_id": 22}', 'pending', ?, ?)
            """,
            (now - 5, now - 5)
        )

        # First claim must be the older mention job
        r1, _ = await srv._claim_next_job()
        assert r1["job_id"] == "mention_job"

        # Second claim is the ticket job
        r2, _ = await srv._claim_next_job()
        assert r2["job_id"] == "ticket_job"
    finally:
        await srv.stop()
        await mgr.close()


@pytest.mark.asyncio
async def test_persistent_ticket_rating_on_interaction_after_restart():
    """Interaction listener in TicketsCog processes rating button click after bot restart."""
    bot = MagicMock()
    bot.ticket_repo = MagicMock()
    bot.ticket_repo.get_ticket_by_channel = AsyncMock(return_value={"creator_id": 999123, "rating": None})
    bot.ticket_repo.set_rating = AsyncMock()

    cog = TicketsCog(bot)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.type = discord.InteractionType.component
    interaction.user = MagicMock(id=999123)
    interaction.data = {"custom_id": "ticket_rate:888111:4"}
    interaction.response.is_done.return_value = False
    interaction.response.edit_message = AsyncMock()

    await cog.on_interaction(interaction)

    bot.ticket_repo.set_rating.assert_awaited_once_with(888111, 4)
    interaction.response.edit_message.assert_awaited_once()
    embed = interaction.response.edit_message.call_args.kwargs["embed"]
    assert "4 / 5 stars" in embed.description


@pytest.mark.asyncio
async def test_multi_worker_atomic_claiming_protection(tmp_path):
    """Database-level conditional UPDATE prevents race conditions if multiple workers claim simultaneously."""
    mgr, bot, srv = await _create_test_env(tmp_path)
    try:
        await srv.enqueue(recipient_id=1, content="Single Job")

        # Two simultaneous claims
        c1, c2 = await asyncio.gather(
            srv._claim_next_job(),
            srv._claim_next_job(),
        )

        claimed = [c[0] for c in [c1, c2] if c[0] is not None]
        # Exactly one worker succeeded in claiming the job
        assert len(claimed) == 1
        assert claimed[0]["recipient_id"] == 1
    finally:
        await srv.stop()
        await mgr.close()

