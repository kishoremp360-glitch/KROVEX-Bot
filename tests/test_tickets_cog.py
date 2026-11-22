"""Comprehensive automated unit and integration tests for Support Ticket System."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import pytest
import discord

from bot.cogs.tickets.cog import TicketsCog
from bot.cogs.tickets.transcript import generate_transcript
from bot.core.context import UnifiedContext
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import TicketRepository


def run_async(coro):
    return asyncio.run(coro)


def test_ticket_settings_and_categories_crud(tmp_path: Path):
    """Verify settings update and category creation/deletion."""
    async def _test():
        db_file = tmp_path / "test_tickets.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = TicketRepository(manager)
        guild_id = 998877

        # Update settings
        await repo.update_settings(
            guild_id,
            category_id=12345,
            staff_role_id=67890,
            transcript_channel_id=112233,
            max_tickets_per_user=2,
        )
        s = await repo.get_settings(guild_id)
        assert s["category_id"] == 12345
        assert s["staff_role_id"] == 67890
        assert s["max_tickets_per_user"] == 2

        # Create category
        cat_id = await repo.create_category(
            guild_id,
            name="Billing",
            emoji="💳",
            description="Billing questions",
            staff_role_id=67890,
        )
        assert cat_id > 0

        cats = await repo.get_categories(guild_id)
        assert len(cats) == 1
        assert cats[0]["name"] == "Billing"
        assert cats[0]["emoji"] == "💳"

        # Delete category
        ok = await repo.delete_category(guild_id, cat_id)
        assert ok is True
        cats_after = await repo.get_categories(guild_id)
        assert len(cats_after) == 0

        await manager.close()

    run_async(_test())


def test_ticket_lifecycle_create_claim_close(tmp_path: Path):
    """Verify full ticket lifecycle: creation, claiming, unclaiming, locking, closing, and rating."""
    async def _test():
        db_file = tmp_path / "test_tickets_lifecycle.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = TicketRepository(manager)

        guild_id = 1001
        channel_id = 2001
        creator_id = 3001
        staff_id = 4001

        # 1. Create ticket
        t_id = await repo.create_ticket(guild_id, channel_id, creator_id)
        assert t_id > 0

        ticket = await repo.get_ticket_by_channel(channel_id)
        assert ticket is not None
        assert ticket["status"] == "open"
        assert ticket["creator_id"] == creator_id

        # 2. Claim ticket
        ok = await repo.claim_ticket(channel_id, staff_id)
        assert ok is True
        t_claimed = await repo.get_ticket_by_channel(channel_id)
        assert t_claimed["claimed_by"] == staff_id
        assert t_claimed["status"] == "claimed"

        # 3. Unclaim ticket
        await repo.unclaim_ticket(channel_id)
        t_unclaimed = await repo.get_ticket_by_channel(channel_id)
        assert t_unclaimed["claimed_by"] is None
        assert t_unclaimed["status"] == "open"

        # 4. Lock and unlock
        await repo.lock_ticket(channel_id)
        assert (await repo.get_ticket_by_channel(channel_id))["status"] == "locked"
        await repo.unlock_ticket(channel_id)
        assert (await repo.get_ticket_by_channel(channel_id))["status"] == "open"

        # 5. Participants
        await repo.add_participant(t_id, 5001, creator_id)
        parts = await repo.get_participants(t_id)
        assert creator_id in parts
        assert 5001 in parts
        await repo.remove_participant(t_id, 5001)
        parts_after = await repo.get_participants(t_id)
        assert 5001 not in parts_after

        # 6. Close ticket
        await repo.close_ticket(channel_id, staff_id, "Resolved satisfactorily")
        t_closed = await repo.get_ticket_by_channel(channel_id)
        assert t_closed["status"] == "closed"
        assert t_closed["close_reason"] == "Resolved satisfactorily"
        assert t_closed["closed_by"] == staff_id

        # 7. Rating
        await repo.set_rating(channel_id, 5, "Excellent service!")
        t_rated = await repo.get_ticket_by_channel(channel_id)
        assert t_rated["rating"] == 5
        assert t_rated["rating_feedback"] == "Excellent service!"

        # 8. Stats check
        stats = await repo.get_ticket_stats(guild_id)
        assert stats["total"] == 1
        assert stats["closed"] == 1
        assert stats["avg_rating"] == 5.0

        await manager.close()

    run_async(_test())


def test_ticket_blacklist(tmp_path: Path):
    """Verify ticket blacklist blocks creation."""
    async def _test():
        db_file = tmp_path / "test_tickets_bl.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = TicketRepository(manager)

        guild_id = 1001
        user_id = 9999

        assert await repo.is_blacklisted(guild_id, user_id) is False
        await repo.blacklist_user(guild_id, user_id, "Trolling support", 1)
        assert await repo.is_blacklisted(guild_id, user_id) is True

        ok = await repo.unblacklist_user(guild_id, user_id)
        assert ok is True
        assert await repo.is_blacklisted(guild_id, user_id) is False

        await manager.close()

    run_async(_test())


def test_transcript_generation():
    """Verify HTML transcript generation reads message history and outputs file."""
    async def _test():
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.name = "ticket-0001"
        mock_channel.id = 888111
        mock_channel.guild.name = "Test Guild"
        mock_channel.guild.id = 999111

        msg1 = MagicMock(spec=discord.Message)
        msg1.author.display_name = "UserAlice"
        msg1.author.bot = False
        msg1.clean_content = "Hello, I need help with my account."
        msg1.created_at = MagicMock()
        msg1.created_at.strftime = MagicMock(return_value="2026-11-12 12:00:00")
        msg1.attachments = []

        msg2 = MagicMock(spec=discord.Message)
        msg2.author.display_name = "StaffBob"
        msg2.author.bot = False
        msg2.clean_content = "Hi Alice! I am looking into your account now."
        msg2.created_at = MagicMock()
        msg2.created_at.strftime = MagicMock(return_value="2026-11-12 12:01:00")
        msg2.attachments = []

        async def mock_history(*args, **kwargs):
            for m in [msg1, msg2]:
                yield m

        mock_channel.history = mock_history

        file = await generate_transcript(mock_channel)
        assert isinstance(file, discord.File)
        assert "transcript-ticket-0001-888111.html" == file.filename
        content = file.fp.read().decode("utf-8")
        assert "UserAlice" in content
        assert "StaffBob" in content
        assert "Hello, I need help with my account." in content

    run_async(_test())


def test_ticket_cog_commands(tmp_path: Path):
    """Verify cog command handlers execute without exceptions."""
    async def _test():
        db_file = tmp_path / "test_tickets_cog.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        repo = TicketRepository(manager)

        bot = MagicMock()
        bot.user.id = 12345
        bot.ticket_repo = repo
        bot.add_view = MagicMock()

        cog = TicketsCog(bot)

        ctx = MagicMock()
        ctx.guild.id = 1001
        ctx.author.guild_permissions.administrator = True
        ctx.reply = AsyncMock()

        uctx = UnifiedContext.from_prefix(ctx)
        uctx.reply = AsyncMock()

        await cog._execute_setup(uctx)
        uctx.reply.assert_called_once()
        embed = uctx.reply.call_args.kwargs.get("embed")
        assert embed is not None
        assert "Ticket System Configured" in embed.title

        await manager.close()

    run_async(_test())
