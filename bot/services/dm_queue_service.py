"""Centralized Persistent Outgoing DM Queue and Global Rate Limiter for KROVEX / Death Bot.

Core Guarantees:
1. Strict Global Rate Limit: Maximum 2 successfully sent bot-initiated DMs per rolling 60-second window.
   - Enforced globally across all guilds and notification subsystems.
   - True rolling-window calculation, persistent across bot restarts in SQLite (`dm_rate_limit_log`).
   - Failed deliveries (Forbidden, NotFound, 429) do NOT consume successful-send slots.
2. Persistent FIFO Queue:
   - Jobs persisted in SQLite (`dm_queue`) across states: 'pending', 'processing', 'sent', 'failed'.
   - Idempotency key support preventing duplicate notification dispatch.
   - Atomic job claiming with protection against concurrent worker races.
   - Safe recovery of abandoned processing jobs on startup / restart.
3. Resilient Error Handling:
   - HTTP 429: Respects Discord's Retry-After; pauses dispatcher; does not mark sent or consume slot.
   - discord.Forbidden: Permanent failure (DMs disabled/blocked); logs and moves immediately to next job.
   - discord.NotFound: Permanent failure (invalid recipient); logs and moves to next job.
   - Transient network/server failures: Bounded exponential backoff up to max_attempts.
4. Clean Diagnostics:
   - Prefix command: `<prefix>dmqueue status` (No top-level slash command added).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
import uuid

import discord
from discord.ext import commands

from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.core.bot import DeathBot
    from bot.database.sqlite_manager import SQLiteDatabaseManager

logger = get_logger("death_bot.services.dm_queue")

WINDOW_SECONDS: float = 60.0
MAX_SENDS_PER_WINDOW: int = 2
BRAND_COLOR: int = 0x9D4EDD


class DMQueueService(commands.Cog, name="DMQueueService"):
    """Service managing centralized persistent outgoing DMs and global rate limiting."""

    def __init__(self, bot: "DeathBot", db_manager: Optional["SQLiteDatabaseManager"] = None) -> None:
        self.bot = bot
        self._custom_db = db_manager
        self._lock = asyncio.Lock()
        self._notify_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._worker_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._paused_until: float = 0.0

    @property
    def db(self) -> Any:
        """Resolve database manager instance."""
        if self._custom_db:
            return self._custom_db
        if hasattr(self.bot, "db_manager") and self.bot.db_manager:
            return self.bot.db_manager
        if hasattr(self.bot, "db") and self.bot.db:
            return self.bot.db
        return None

    async def initialize(self) -> None:
        """Initialize database tables, recover abandoned processing jobs, and start worker."""
        if not self.db:
            logger.warning("DMQueueService initialized without active database connection.")
            return

        # 1. Recover abandoned processing jobs left over from unexpected restart/crash
        now = time.time()
        try:
            await self.db.execute(
                "UPDATE dm_queue SET state = 'pending', updated_at = ? WHERE state = 'processing'",
                (now,)
            )
            logger.info("DMQueueService recovered abandoned processing jobs.")
        except Exception as err:
            logger.error("Failed to recover abandoned DM jobs: %s", err)

        # 2. Start background worker loop
        self._running = True
        self._stop_event.clear()
        if not self._worker_task or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop(), name="dm_queue_worker")
            logger.info("KROVEX Global DM Queue worker started.")

    def cog_unload(self) -> None:
        """Cleanup worker task when cog unloads."""
        self.stop_worker()

    def stop_worker(self) -> None:
        """Signal background worker to terminate cleanly."""
        self._running = False
        self._stop_event.set()
        self._notify_event.set()
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()

    async def stop(self) -> None:
        """Async stop and await worker termination."""
        self.stop_worker()
        if self._worker_task:
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):
                pass
            self._worker_task = None
        logger.info("KROVEX Global DM Queue worker stopped.")

    # ── Job Enqueueing ────────────────────────────────────────────────────────

    async def enqueue(
        self,
        recipient_id: int,
        guild_id: Optional[int] = None,
        message_type: str = "notification",
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        idempotency_key: Optional[str] = None,
        max_attempts: int = 3,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Enqueue an outgoing DM job into persistent storage.
        
        Returns:
            job_id: str (unique identifier of the job), or existing job_id if skipped by idempotency.
        """
        if not self.db:
            logger.error("Cannot enqueue DM job: database unavailable.")
            return None

        # 1. Idempotency Check
        if idempotency_key:
            row = await self.db.fetchone(
                "SELECT job_id, state FROM dm_queue WHERE idempotency_key = ?",
                (idempotency_key,)
            )
            if row:
                logger.debug("Skipping duplicate DM job with idempotency_key=%s (existing job_id=%s)", idempotency_key, row["job_id"])
                return row["job_id"]

        job_id = uuid.uuid4().hex
        now = time.time()
        embed_json = json.dumps(embed.to_dict()) if embed else None
        metadata_json = json.dumps(metadata) if metadata else None

        await self.db.execute(
            """
            INSERT INTO dm_queue (
                job_id, idempotency_key, recipient_id, guild_id, message_type,
                content, embed_data, metadata, state, attempts, max_attempts, backoff_until,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, 0.0, ?, ?)
            """,
            (
                job_id, idempotency_key, recipient_id, guild_id, message_type,
                content, embed_json, metadata_json, max_attempts, now, now
            )
        )
        logger.debug("Enqueued DM job %s for recipient %s (type=%s)", job_id, recipient_id, message_type)

        # Notify worker to process pending job immediately
        self._notify_event.set()
        return job_id

    # ── Rate Limiter & Job Claiming ──────────────────────────────────────────

    async def _check_rate_limit(self, current_time: float) -> Tuple[bool, float]:
        """
        Check if an outgoing send is permitted within the rolling 60-second window.
        Returns: (can_send: bool, wait_seconds: float)
        """
        if current_time < self._paused_until:
            return False, max(0.05, self._paused_until - current_time)

        cutoff = current_time - WINDOW_SECONDS
        rows = await self.db.fetchall(
            "SELECT sent_at FROM dm_rate_limit_log WHERE sent_at > ? ORDER BY sent_at ASC",
            (cutoff,)
        )
        if len(rows) >= MAX_SENDS_PER_WINDOW:
            oldest_sent_at = rows[0]["sent_at"]
            wait_needed = (oldest_sent_at + WINDOW_SECONDS) - current_time
            return False, max(0.05, wait_needed)

        return True, 0.0

    async def _claim_next_job(self) -> Tuple[Optional[Dict[str, Any]], float]:
        """
        Atomically inspect rate limit and claim the oldest eligible pending job.
        Returns: (job_row: Optional[dict], wait_seconds: float)
        """
        async with self._lock:
            now = time.time()
            can_send, wait_seconds = await self._check_rate_limit(now)
            if not can_send:
                return None, wait_seconds

            # Fetch oldest pending job whose backoff has expired
            row = await self.db.fetchone(
                """
                SELECT * FROM dm_queue
                WHERE state = 'pending' AND backoff_until <= ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (now,)
            )
            if not row:
                return None, 0.0

            job_id = row["job_id"]
            cursor = await self.db.execute(
                "UPDATE dm_queue SET state = 'processing', updated_at = ? WHERE job_id = ? AND state = 'pending'",
                (now, job_id)
            )
            if hasattr(cursor, "rowcount") and cursor.rowcount == 0:
                # Concurrently claimed by another worker/process
                return None, 0.0

            return row, 0.0

    # ── Worker Dispatch Loop ─────────────────────────────────────────────────

    async def _worker_loop(self) -> None:
        """Background FIFO dispatch worker with rolling-window rate enforcement."""
        logger.info("KROVEX Global DM Queue worker loop active.")
        while self._running:
            if not getattr(self.db, "is_connected", True):
                break
            try:
                row, wait_seconds = await self._claim_next_job()
                if wait_seconds > 0:
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                        break
                    except asyncio.TimeoutError:
                        continue

                if not row:
                    # No pending job ready; wait for event or stop signal
                    self._notify_event.clear()
                    tasks = [
                        asyncio.create_task(self._notify_event.wait()),
                        asyncio.create_task(self._stop_event.wait()),
                    ]
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for t in pending:
                        t.cancel()
                    if self._stop_event.is_set():
                        break
                    continue

                # Dispatch claimed job
                await self._dispatch_job(row)

            except asyncio.CancelledError:
                break
            except Exception as err:
                if not getattr(self.db, "is_connected", True) or "closed database" in str(err).lower():
                    break
                logger.error("Error in DM Queue worker loop: %s", err, exc_info=True)
                await asyncio.sleep(1.0)

    async def _dispatch_job(self, row: Dict[str, Any]) -> None:
        """Attempt delivery of a single claimed DM job."""
        job_id = row["job_id"]
        recipient_id = row["recipient_id"]
        content = row.get("content")
        embed_data = json.loads(row["embed_data"]) if row.get("embed_data") else None
        embed = discord.Embed.from_dict(embed_data) if embed_data else None

        # 1. Resolve Recipient User
        user: Optional[Union[discord.User, discord.Member]] = None
        if hasattr(self.bot, "get_user"):
            user = self.bot.get_user(recipient_id)

        if not user and hasattr(self.bot, "fetch_user"):
            try:
                user = await self.bot.fetch_user(recipient_id)
            except discord.NotFound:
                await self._mark_failed(job_id, "NotFound: Invalid recipient account")
                return
            except discord.Forbidden:
                await self._mark_failed(job_id, "Forbidden: Blocked or inaccessible recipient")
                return
            except discord.HTTPException as err:
                if getattr(err, "status", None) == 429:
                    await self._handle_rate_limited(row, err)
                    return
                await self._mark_retry(row, err)
                return
            except Exception as err:
                await self._mark_retry(row, err)
                return

        if not user:
            await self._mark_failed(job_id, "NotFound: Could not resolve recipient user")
            return

        # 2. Reconstruct Interactive Views (e.g. TicketRatingView) from serializable metadata
        view: Optional[discord.ui.View] = None
        message_type = row.get("message_type")
        if message_type == "ticket_rating":
            try:
                from bot.cogs.tickets.views import TicketRatingView
                meta = json.loads(row["metadata"]) if row.get("metadata") else {}
                channel_id = meta.get("channel_id")
                guild_id = meta.get("guild_id") or row.get("guild_id")
                if channel_id:
                    view = TicketRatingView(channel_id=int(channel_id), guild_id=int(guild_id) if guild_id else 0)
            except Exception as e:
                logger.warning("Could not reconstruct TicketRatingView for job %s: %s", job_id, e)

        # 3. Transmit DM
        try:
            kwargs = {}
            if content:
                kwargs["content"] = content
            if embed:
                kwargs["embed"] = embed
            if view:
                kwargs["view"] = view

            await user.send(**kwargs)
            await self._mark_success(row)
            logger.info("Successfully delivered DM job %s to user %s (type=%s)", job_id, recipient_id, row.get("message_type"))

        except discord.Forbidden:
            # Permanent failure: DMs closed / user blocked bot.
            # Do NOT consume a successful-send slot!
            await self._mark_failed(job_id, "Forbidden: Recipient DMs are disabled or bot is blocked")
            logger.debug("Cannot deliver DM job %s to %s: DMs disabled or blocked", job_id, recipient_id)

        except discord.NotFound:
            # Permanent failure: Channel or user deleted.
            await self._mark_failed(job_id, "NotFound: Recipient DM channel or account not found")

        except discord.HTTPException as err:
            if getattr(err, "status", None) == 429:
                await self._handle_rate_limited(row, err)
            else:
                await self._mark_retry(row, err)

        except Exception as err:
            await self._mark_retry(row, err)

    # ── Job Status Transitions ───────────────────────────────────────────────

    async def _mark_success(self, row: Dict[str, Any]) -> None:
        """Mark job as sent and record successful send in persistent rate limiter log."""
        now = time.time()
        job_id = row["job_id"]
        await self.db.execute(
            "UPDATE dm_queue SET state = 'sent', updated_at = ? WHERE job_id = ?",
            (now, job_id)
        )
        await self.db.execute(
            "INSERT INTO dm_rate_limit_log (job_id, recipient_id, guild_id, sent_at) VALUES (?, ?, ?, ?)",
            (job_id, row["recipient_id"], row.get("guild_id"), now)
        )
        # Prune old logs older than 24 hours to keep table lean
        try:
            await self.db.execute("DELETE FROM dm_rate_limit_log WHERE sent_at < ?", (now - 86400.0,))
        except Exception:
            pass

    async def _mark_failed(self, job_id: str, error_message: str) -> None:
        """Mark job as permanently failed without consuming a rate limit slot."""
        now = time.time()
        await self.db.execute(
            "UPDATE dm_queue SET state = 'failed', error_message = ?, updated_at = ? WHERE job_id = ?",
            (error_message, now, job_id)
        )

    async def _handle_rate_limited(self, row: Dict[str, Any], err: Any) -> None:
        """Handle Discord HTTP 429 RateLimit by pausing dispatch for retry_after."""
        retry_after = getattr(err, "retry_after", 5.0) or 5.0
        now = time.time()
        self._paused_until = now + retry_after
        backoff_until = now + retry_after
        job_id = row["job_id"]

        logger.warning("Discord HTTP 429 encountered during DM dispatch. Backing off for %.2fs", retry_after)
        await self.db.execute(
            """
            UPDATE dm_queue
            SET state = 'pending', backoff_until = ?, error_message = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (backoff_until, f"RateLimited: retry_after={retry_after:.2f}s", now, job_id)
        )

    async def _mark_retry(self, row: Dict[str, Any], err: Any) -> None:
        """Handle transient network failure with bounded exponential backoff."""
        job_id = row["job_id"]
        attempts = (row.get("attempts") or 0) + 1
        max_attempts = row.get("max_attempts") or 3
        now = time.time()

        if attempts >= max_attempts:
            error_msg = f"Max attempts ({max_attempts}) reached: {err}"
            await self.db.execute(
                "UPDATE dm_queue SET state = 'failed', attempts = ?, error_message = ?, updated_at = ? WHERE job_id = ?",
                (attempts, error_msg, now, job_id)
            )
            logger.warning("DM job %s reached maximum retries (%d): %s", job_id, max_attempts, err)
        else:
            backoff_secs = (2 ** attempts) * 5.0  # 10s, 20s, 40s
            backoff_until = now + backoff_secs
            error_msg = f"Transient failure ({attempts}/{max_attempts}): {err}"
            await self.db.execute(
                """
                UPDATE dm_queue
                SET state = 'pending', attempts = ?, backoff_until = ?, error_message = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (attempts, backoff_until, error_msg, now, job_id)
            )
            logger.info("DM job %s scheduled for retry in %.1fs (attempt %d/%d)", job_id, backoff_secs, attempts, max_attempts)

    # ── Diagnostic Statistics ────────────────────────────────────────────────

    async def get_stats(self) -> Dict[str, Any]:
        """Fetch operational statistics and rate limit health."""
        if not self.db:
            return {
                "pending": 0, "processing": 0, "sent": 0, "failed": 0,
                "window_sends": 0, "next_eligible_seconds": 0.0, "worker_status": "No Database"
            }

        counts = {"pending": 0, "processing": 0, "sent": 0, "failed": 0}
        rows = await self.db.fetchall("SELECT state, COUNT(*) as cnt FROM dm_queue GROUP BY state")
        for r in rows:
            if r["state"] in counts:
                counts[r["state"]] = r["cnt"]

        now = time.time()
        cutoff = now - WINDOW_SECONDS
        recent = await self.db.fetchall(
            "SELECT sent_at FROM dm_rate_limit_log WHERE sent_at > ? ORDER BY sent_at ASC",
            (cutoff,)
        )
        window_sends = len(recent)
        next_eligible = 0.0
        if window_sends >= MAX_SENDS_PER_WINDOW:
            next_eligible = max(0.0, (recent[0]["sent_at"] + WINDOW_SECONDS) - now)
        elif now < self._paused_until:
            next_eligible = max(0.0, self._paused_until - now)

        status_str = "Active (Running)" if self._running else "Stopped"
        if now < self._paused_until:
            status_str = f"Paused (429 Backoff: {self._paused_until - now:.1f}s)"

        return {
            **counts,
            "window_sends": window_sends,
            "next_eligible_seconds": next_eligible,
            "worker_status": status_str,
        }

    # ── Diagnostics Prefix Command ───────────────────────────────────────────

    @commands.group(name="dmqueue", aliases=["dmq"], invoke_without_command=True)
    async def dmqueue_group(self, ctx: commands.Context) -> None:
        """KROVEX Centralized Outgoing DM Queue management."""
        await self.dmqueue_status(ctx)

    @dmqueue_group.command(name="status")
    async def dmqueue_status(self, ctx: commands.Context) -> None:
        """Display operational diagnostics and status of the global DM queue."""
        stats = await self.get_stats()
        next_str = "Immediate" if stats["next_eligible_seconds"] <= 0 else f"{stats['next_eligible_seconds']:.1f}s"

        embed = discord.Embed(
            title="📬 KROVEX Global DM Queue Diagnostics",
            description="Centralized outgoing rate-limiter and persistent FIFO delivery pipeline.",
            color=BRAND_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Worker Status", value=f"`{stats['worker_status']}`", inline=True)
        embed.add_field(name="Rolling Window (60s)", value=f"`{stats['window_sends']} / {MAX_SENDS_PER_WINDOW} sends`", inline=True)
        embed.add_field(name="Next Eligible Window", value=f"`{next_str}`", inline=True)
        embed.add_field(name="Pending Jobs", value=f"`{stats['pending']}`", inline=True)
        embed.add_field(name="Processing Jobs", value=f"`{stats['processing']}`", inline=True)
        embed.add_field(name="Sent (Total)", value=f"`{stats['sent']}`", inline=True)
        embed.add_field(name="Failed (Total)", value=f"`{stats['failed']}`", inline=True)
        embed.set_footer(text="KROVEX AUDIT VAULT • DM DELIVERY SUBSYSTEM")

        await ctx.send(embed=embed)


async def setup(bot: "DeathBot") -> None:
    """Setup hook to register DMQueueService cog."""
    service = DMQueueService(bot)
    await service.initialize()
    bot.dm_queue_service = service
    await bot.add_cog(service)

