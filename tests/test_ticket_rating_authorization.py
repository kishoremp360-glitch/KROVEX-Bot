"""Tests for Ticket Rating Authorization Hardening (Phase 2A.2).

Verifies:
1. Authorized ticket creator can submit ratings.
2. Different/unauthorized user is rejected without changing rating.
3. Missing or deleted ticket records are rejected safely.
4. Malformed custom IDs (invalid parts, non-integer, out-of-range stars) are rejected.
5. Duplicate rating submissions are rejected per existing rating policy.
6. All five valid star ratings (1-5) function correctly.
7. Persistent interaction handler (on_interaction) enforces authorization across bot restart.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.cogs.tickets.cog import TicketsCog
from bot.cogs.tickets.views import (
    TicketRatingView,
    handle_ticket_rating_interaction,
)


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.ticket_repo = MagicMock()
    bot.ticket_repo.get_ticket_by_channel = AsyncMock()
    bot.ticket_repo.set_rating = AsyncMock(return_value=True)
    return bot


@pytest.fixture
def base_interaction(mock_bot):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.client = mock_bot
    interaction.type = discord.InteractionType.component
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.mark.asyncio
async def test_authorized_creator_successfully_rates(mock_bot, base_interaction):
    """Authorized creator (interaction.user.id == ticket['creator_id']) rates ticket successfully."""
    channel_id = 111222333
    creator_id = 999888777
    stars = 5

    mock_bot.ticket_repo.get_ticket_by_channel.return_value = {
        "channel_id": channel_id,
        "creator_id": creator_id,
        "rating": None,
    }

    base_interaction.user = MagicMock(id=creator_id)
    base_interaction.data = {"custom_id": f"ticket_rate:{channel_id}:{stars}"}

    success = await handle_ticket_rating_interaction(base_interaction, bot=mock_bot)

    assert success is True
    mock_bot.ticket_repo.get_ticket_by_channel.assert_awaited_once_with(channel_id)
    mock_bot.ticket_repo.set_rating.assert_awaited_once_with(channel_id, stars)
    base_interaction.response.edit_message.assert_awaited_once()
    embed = base_interaction.response.edit_message.call_args.kwargs["embed"]
    assert "5 / 5 stars" in embed.description
    base_interaction.response.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_unauthorized_user_attempting_to_rate_rejected(mock_bot, base_interaction):
    """Unauthorized user (interaction.user.id != ticket['creator_id']) is rejected without modifying rating."""
    channel_id = 111222333
    creator_id = 999888777
    intruder_id = 111000111
    stars = 5

    mock_bot.ticket_repo.get_ticket_by_channel.return_value = {
        "channel_id": channel_id,
        "creator_id": creator_id,
        "rating": None,
    }

    base_interaction.user = MagicMock(id=intruder_id)
    base_interaction.data = {"custom_id": f"ticket_rate:{channel_id}:{stars}"}

    success = await handle_ticket_rating_interaction(base_interaction, bot=mock_bot)

    assert success is False
    mock_bot.ticket_repo.set_rating.assert_not_called()
    base_interaction.response.edit_message.assert_not_called()
    base_interaction.response.send_message.assert_awaited_once()
    assert "Only the ticket creator" in base_interaction.response.send_message.call_args[0][0]
    assert base_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_missing_ticket_record_rejected_safely(mock_bot, base_interaction):
    """Interaction referencing non-existent ticket in database is rejected safely with error response."""
    channel_id = 404404404
    mock_bot.ticket_repo.get_ticket_by_channel.return_value = None

    base_interaction.user = MagicMock(id=123456)
    base_interaction.data = {"custom_id": f"ticket_rate:{channel_id}:3"}

    success = await handle_ticket_rating_interaction(base_interaction, bot=mock_bot)

    assert success is False
    mock_bot.ticket_repo.set_rating.assert_not_called()
    base_interaction.response.send_message.assert_awaited_once()
    assert "not found" in base_interaction.response.send_message.call_args[0][0]
    assert base_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed_id",
    [
        "ticket_rate:",
        "ticket_rate:123",
        "ticket_rate:abc:3",
        "ticket_rate:123:abc",
        "ticket_rate:123:0",
        "ticket_rate:123:6",
        "ticket_rate:123:99",
        "ticket_rate:123:3:extra",
    ],
)
async def test_invalid_custom_ids_rejected_safely(mock_bot, base_interaction, malformed_id):
    """Malformed or out-of-range custom IDs are safely rejected without DB queries or unhandled exceptions."""
    base_interaction.user = MagicMock(id=123456)
    base_interaction.data = {"custom_id": malformed_id}

    success = await handle_ticket_rating_interaction(base_interaction, bot=mock_bot)

    assert success is False
    mock_bot.ticket_repo.get_ticket_by_channel.assert_not_called()
    mock_bot.ticket_repo.set_rating.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_rating_submission_rejected(mock_bot, base_interaction):
    """Submitting a rating on a ticket that has already been rated is rejected."""
    channel_id = 222333444
    creator_id = 555666777

    # Already has rating = 4
    mock_bot.ticket_repo.get_ticket_by_channel.return_value = {
        "channel_id": channel_id,
        "creator_id": creator_id,
        "rating": 4,
    }

    base_interaction.user = MagicMock(id=creator_id)
    base_interaction.data = {"custom_id": f"ticket_rate:{channel_id}:5"}

    success = await handle_ticket_rating_interaction(base_interaction, bot=mock_bot)

    assert success is False
    mock_bot.ticket_repo.set_rating.assert_not_called()
    base_interaction.response.send_message.assert_awaited_once()
    assert "already been rated" in base_interaction.response.send_message.call_args[0][0]
    assert base_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("stars", [1, 2, 3, 4, 5])
async def test_all_five_valid_ratings_through_view(mock_bot, base_interaction, stars):
    """All 5 rating buttons on TicketRatingView execute correctly for authorized creator."""
    channel_id = 333444555
    creator_id = 777888999

    mock_bot.ticket_repo.get_ticket_by_channel.return_value = {
        "channel_id": channel_id,
        "creator_id": creator_id,
        "rating": None,
    }

    view = TicketRatingView(channel_id=channel_id, guild_id=1001)
    base_interaction.user = MagicMock(id=creator_id)

    cb = getattr(view, f"r{stars}")
    await cb.callback(base_interaction)

    mock_bot.ticket_repo.set_rating.assert_awaited_once_with(channel_id, stars)
    base_interaction.response.edit_message.assert_awaited_once()
    embed = base_interaction.response.edit_message.call_args.kwargs["embed"]
    assert f"{stars} / 5 stars" in embed.description


@pytest.mark.asyncio
async def test_persistent_on_interaction_authorized_after_restart(mock_bot, base_interaction):
    """TicketsCog.on_interaction listener authorizes creator and records rating after bot restart."""
    cog = TicketsCog(mock_bot)
    channel_id = 888999000
    creator_id = 444333222
    stars = 4

    mock_bot.ticket_repo.get_ticket_by_channel.return_value = {
        "channel_id": channel_id,
        "creator_id": creator_id,
        "rating": None,
    }

    base_interaction.user = MagicMock(id=creator_id)
    base_interaction.data = {"custom_id": f"ticket_rate:{channel_id}:{stars}"}

    await cog.on_interaction(base_interaction)

    mock_bot.ticket_repo.set_rating.assert_awaited_once_with(channel_id, stars)
    base_interaction.response.edit_message.assert_awaited_once()
    embed = base_interaction.response.edit_message.call_args.kwargs["embed"]
    assert "4 / 5 stars" in embed.description


@pytest.mark.asyncio
async def test_persistent_on_interaction_unauthorized_after_restart(mock_bot, base_interaction):
    """TicketsCog.on_interaction listener rejects unauthorized user after bot restart."""
    cog = TicketsCog(mock_bot)
    channel_id = 888999000
    creator_id = 444333222
    intruder_id = 999111222
    stars = 4

    mock_bot.ticket_repo.get_ticket_by_channel.return_value = {
        "channel_id": channel_id,
        "creator_id": creator_id,
        "rating": None,
    }

    base_interaction.user = MagicMock(id=intruder_id)
    base_interaction.data = {"custom_id": f"ticket_rate:{channel_id}:{stars}"}

    await cog.on_interaction(base_interaction)

    mock_bot.ticket_repo.set_rating.assert_not_called()
    base_interaction.response.send_message.assert_awaited_once()
    assert "Only the ticket creator" in base_interaction.response.send_message.call_args[0][0]


@pytest.mark.asyncio
async def test_error_response_fallback_when_ephemeral_fails(mock_bot, base_interaction):
    """When ephemeral response raises an exception, error responder falls back to normal message safely."""
    channel_id = 555666777
    creator_id = 111222333
    intruder_id = 444555666

    mock_bot.ticket_repo.get_ticket_by_channel.return_value = {
        "channel_id": channel_id,
        "creator_id": creator_id,
        "rating": None,
    }

    # Simulate ephemeral failing on first attempt, succeeding on non-ephemeral
    base_interaction.response.send_message.side_effect = [
        discord.HTTPException(MagicMock(status=400), "Ephemeral not supported"),
        None,
    ]

    base_interaction.user = MagicMock(id=intruder_id)
    base_interaction.data = {"custom_id": f"ticket_rate:{channel_id}:5"}

    success = await handle_ticket_rating_interaction(base_interaction, bot=mock_bot)

    assert success is False
    assert base_interaction.response.send_message.call_count == 2


# =========================================================================
# REAL SQLITE INTEGRATION TESTS (Non-Mocked SQLite Database)
# =========================================================================

from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import TicketRepository


async def _create_real_sqlite_env(tmp_path):
    """Create isolated SQLite database and real TicketRepository."""
    from pathlib import Path
    db_file = tmp_path / "test_tickets.sqlite"
    mgr = SQLiteDatabaseManager(db_path=Path(db_file))
    await mgr.connect()

    repo = TicketRepository(mgr)
    bot = MagicMock()
    bot.ticket_repo = repo
    bot.db_manager = mgr

    return mgr, repo, bot


@pytest.mark.asyncio
async def test_sqlite_real_creator_rating_persisted(tmp_path):
    """Real SQLite integration: Authorized creator rating is atomically written and persisted."""
    mgr, repo, bot = await _create_real_sqlite_env(tmp_path)
    try:
        channel_id = 10001
        creator_id = 50001

        # Seed real ticket in SQLite
        await repo.create_ticket(guild_id=999, channel_id=channel_id, creator_id=creator_id)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.client = bot
        interaction.user = MagicMock(id=creator_id)
        interaction.type = discord.InteractionType.component
        interaction.data = {"custom_id": f"ticket_rate:{channel_id}:5"}
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        interaction.response.edit_message = AsyncMock()
        interaction.followup.send = AsyncMock()

        success = await handle_ticket_rating_interaction(interaction, bot=bot)
        assert success is True

        # Verify real database row
        row = await mgr.fetchone("SELECT rating FROM tickets WHERE channel_id = ?", (channel_id,))
        assert row is not None
        assert row["rating"] == 5
        interaction.response.edit_message.assert_awaited_once()
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_sqlite_real_unauthorized_user_rejected(tmp_path):
    """Real SQLite integration: Unauthorized user cannot modify ticket rating."""
    mgr, repo, bot = await _create_real_sqlite_env(tmp_path)
    try:
        channel_id = 10002
        creator_id = 50002
        intruder_id = 99999

        await repo.create_ticket(guild_id=999, channel_id=channel_id, creator_id=creator_id)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.client = bot
        interaction.user = MagicMock(id=intruder_id)
        interaction.type = discord.InteractionType.component
        interaction.data = {"custom_id": f"ticket_rate:{channel_id}:5"}
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        interaction.response.edit_message = AsyncMock()
        interaction.followup.send = AsyncMock()

        success = await handle_ticket_rating_interaction(interaction, bot=bot)
        assert success is False

        # Verify database rating remains NULL
        row = await mgr.fetchone("SELECT rating FROM tickets WHERE channel_id = ?", (channel_id,))
        assert row is not None
        assert row["rating"] is None
        interaction.response.send_message.assert_awaited_once()
        assert "Only the ticket creator" in interaction.response.send_message.call_args[0][0]
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_sqlite_real_duplicate_submission_rejected(tmp_path):
    """Real SQLite integration: Subsequent rating submission cannot overwrite existing rating."""
    mgr, repo, bot = await _create_real_sqlite_env(tmp_path)
    try:
        channel_id = 10003
        creator_id = 50003

        await repo.create_ticket(guild_id=999, channel_id=channel_id, creator_id=creator_id)

        # First rating: 4 stars
        i1 = MagicMock(spec=discord.Interaction)
        i1.client = bot
        i1.user = MagicMock(id=creator_id)
        i1.type = discord.InteractionType.component
        i1.data = {"custom_id": f"ticket_rate:{channel_id}:4"}
        i1.response.is_done.return_value = False
        i1.response.send_message = AsyncMock()
        i1.response.edit_message = AsyncMock()
        i1.followup.send = AsyncMock()

        s1 = await handle_ticket_rating_interaction(i1, bot=bot)
        assert s1 is True

        # Second rating attempt: 5 stars
        i2 = MagicMock(spec=discord.Interaction)
        i2.client = bot
        i2.user = MagicMock(id=creator_id)
        i2.type = discord.InteractionType.component
        i2.data = {"custom_id": f"ticket_rate:{channel_id}:5"}
        i2.response.is_done.return_value = False
        i2.response.send_message = AsyncMock()
        i2.response.edit_message = AsyncMock()
        i2.followup.send = AsyncMock()

        s2 = await handle_ticket_rating_interaction(i2, bot=bot)
        assert s2 is False

        # Verify rating in database is STILL 4 (never overwritten)
        row = await mgr.fetchone("SELECT rating FROM tickets WHERE channel_id = ?", (channel_id,))
        assert row["rating"] == 4
        i2.response.send_message.assert_awaited_once()
        assert "already been rated" in i2.response.send_message.call_args[0][0]
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_sqlite_real_feedback_persistence(tmp_path):
    """Real SQLite integration: Rating and optional textual feedback persist atomically."""
    mgr, repo, bot = await _create_real_sqlite_env(tmp_path)
    try:
        channel_id = 10004
        creator_id = 50004

        await repo.create_ticket(guild_id=999, channel_id=channel_id, creator_id=creator_id)
        updated = await repo.set_rating(channel_id, 5, feedback="Outstanding support staff!")
        assert updated is True

        row = await mgr.fetchone("SELECT rating, rating_feedback FROM tickets WHERE channel_id = ?", (channel_id,))
        assert row["rating"] == 5
        assert row["rating_feedback"] == "Outstanding support staff!"

        # A second update must fail atomically because rating is already set
        second_update = await repo.set_rating(channel_id, 1, feedback="Overwriting!")
        assert second_update is False

        # Database remains 5
        row2 = await mgr.fetchone("SELECT rating, rating_feedback FROM tickets WHERE channel_id = ?", (channel_id,))
        assert row2["rating"] == 5
        assert row2["rating_feedback"] == "Outstanding support staff!"
    finally:
        await mgr.close()


# =========================================================================
# CONCURRENT SUBMISSION TESTS (Simultaneous asyncio.gather)
# =========================================================================

@pytest.mark.asyncio
async def test_concurrent_two_simultaneous_rating_submissions(tmp_path):
    """Two simultaneous rating submissions against unrated ticket: exactly ONE wins, stored rating matches winner."""
    mgr, repo, bot = await _create_real_sqlite_env(tmp_path)
    try:
        channel_id = 20001
        creator_id = 60001

        await repo.create_ticket(guild_id=999, channel_id=channel_id, creator_id=creator_id)

        # Interaction A: 3 stars
        ia = MagicMock(spec=discord.Interaction)
        ia.client = bot
        ia.user = MagicMock(id=creator_id)
        ia.type = discord.InteractionType.component
        ia.data = {"custom_id": f"ticket_rate:{channel_id}:3"}
        ia.response.is_done.return_value = False
        ia.response.send_message = AsyncMock()
        ia.response.edit_message = AsyncMock()
        ia.followup.send = AsyncMock()

        # Interaction B: 5 stars
        ib = MagicMock(spec=discord.Interaction)
        ib.client = bot
        ib.user = MagicMock(id=creator_id)
        ib.type = discord.InteractionType.component
        ib.data = {"custom_id": f"ticket_rate:{channel_id}:5"}
        ib.response.is_done.return_value = False
        ib.response.send_message = AsyncMock()
        ib.response.edit_message = AsyncMock()
        ib.followup.send = AsyncMock()

        # Execute both concurrently
        res_a, res_b = await asyncio.gather(
            handle_ticket_rating_interaction(ia, bot=bot),
            handle_ticket_rating_interaction(ib, bot=bot),
        )

        # Invariant: EXACTLY one succeeds, exactly one fails
        results = [res_a, res_b]
        assert results.count(True) == 1
        assert results.count(False) == 1

        # Verify SQLite row matches the winner
        row = await mgr.fetchone("SELECT rating FROM tickets WHERE channel_id = ?", (channel_id,))
        assert row["rating"] in (3, 5)

        if res_a is True:
            assert row["rating"] == 3
            ia.response.edit_message.assert_awaited_once()
            ib.response.send_message.assert_awaited_once()
            assert "already been rated" in ib.response.send_message.call_args[0][0]
        else:
            assert row["rating"] == 5
            ib.response.edit_message.assert_awaited_once()
            ia.response.send_message.assert_awaited_once()
            assert "already been rated" in ia.response.send_message.call_args[0][0]
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_concurrent_five_simultaneous_rating_submissions(tmp_path):
    """Five simultaneous rating submissions with different star values: exactly ONE wins, four receive duplicate rejection."""
    mgr, repo, bot = await _create_real_sqlite_env(tmp_path)
    try:
        channel_id = 20002
        creator_id = 60002

        await repo.create_ticket(guild_id=999, channel_id=channel_id, creator_id=creator_id)

        interactions = []
        for stars in range(1, 6):
            inter = MagicMock(spec=discord.Interaction)
            inter.client = bot
            inter.user = MagicMock(id=creator_id)
            inter.type = discord.InteractionType.component
            inter.data = {"custom_id": f"ticket_rate:{channel_id}:{stars}"}
            inter.response.is_done.return_value = False
            inter.response.send_message = AsyncMock()
            inter.response.edit_message = AsyncMock()
            inter.followup.send = AsyncMock()
            interactions.append((stars, inter))

        # Launch all 5 simultaneously
        outcomes = await asyncio.gather(
            *(handle_ticket_rating_interaction(inter, bot=bot) for _, inter in interactions)
        )

        # Invariant: EXACTLY 1 succeeds, EXACTLY 4 fail
        assert outcomes.count(True) == 1
        assert outcomes.count(False) == 4

        winner_idx = outcomes.index(True)
        winner_stars, winner_inter = interactions[winner_idx]

        # Verify SQLite stored rating matches winner
        row = await mgr.fetchone("SELECT rating FROM tickets WHERE channel_id = ?", (channel_id,))
        assert row["rating"] == winner_stars
        winner_inter.response.edit_message.assert_awaited_once()

        # Verify all 4 losers received 'already been rated'
        for idx, (_, inter) in enumerate(interactions):
            if idx != winner_idx:
                inter.response.send_message.assert_awaited_once()
                assert "already been rated" in inter.response.send_message.call_args[0][0]
    finally:
        await mgr.close()


