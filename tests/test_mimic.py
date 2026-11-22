"""Automated tests for Death Bot Mimic Per-Server Bot Identity System."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.core.context import UnifiedContext
from bot.cogs.mimic.cog import Mimic
from bot.database.repositories.sqlite_repos import MimicRepository


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 1570428426974662718
    bot.user.name = "Death Bot"
    bot.mimic_repo = MagicMock(spec=MimicRepository)
    bot.mimic_repo.get_profile = AsyncMock(return_value={
        "guild_id": 999888,
        "nickname": "Server Persona",
        "avatar_url": "https://example.com/avatar.png",
    })
    bot.mimic_repo.set_nickname = AsyncMock()
    bot.mimic_repo.set_avatar = AsyncMock()
    bot.mimic_repo.reset_profile = AsyncMock(return_value=True)
    return bot


def _make_ctx(guild_id: int = 999888):
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = MagicMock(spec=discord.Guild)
    ctx.guild.id = guild_id
    ctx.guild.name = "Mimic Guild"
    ctx.guild.me = MagicMock(spec=discord.Member)
    ctx.guild.me.name = "Death Bot"
    ctx.guild.me.display_name = "Death Bot"
    ctx.guild.me.nick = None
    ctx.guild.me.guild_permissions.change_nickname = True
    ctx.guild.me.guild_permissions.manage_nicknames = True
    ctx.guild.me.edit = AsyncMock()
    ctx.guild.me.display_avatar.url = "https://cdn.discordapp.com/avatars/default.png"
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.name = "AdminUser"
    ctx.reply = AsyncMock()
    ctx.send_success = AsyncMock()
    ctx.send_error = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_mimic_nick_success(mock_bot):
    """Test setting custom server nickname."""
    cog = Mimic(mock_bot)
    ctx = _make_ctx()

    await cog._execute_nick(ctx, "Death Reaper")

    ctx.guild.me.edit.assert_awaited_with(nick="Death Reaper", reason="Death Bot Mimic Persona updated by AdminUser")
    mock_bot.mimic_repo.set_nickname.assert_awaited_with(999888, "Death Reaper", original_name="Death Bot")
    ctx.reply.assert_awaited()


@pytest.mark.asyncio
async def test_mimic_nick_too_long(mock_bot):
    """Test nickname length validation (Max 32 chars)."""
    cog = Mimic(mock_bot)
    ctx = _make_ctx()

    too_long = "A" * 35
    await cog._execute_nick(ctx, too_long)

    ctx.send_error.assert_awaited_with("Too Long", "Discord nicknames cannot exceed 32 characters.")
    ctx.guild.me.edit.assert_not_called()


@pytest.mark.asyncio
async def test_mimic_avatar_validation(mock_bot):
    """Test avatar format rejection for non-image URLs."""
    cog = Mimic(mock_bot)
    ctx = _make_ctx()

    await cog._execute_avatar(ctx, "https://example.com/malicious.exe")
    ctx.send_error.assert_awaited()
    mock_bot.mimic_repo.set_avatar.assert_not_called()


@pytest.mark.asyncio
async def test_mimic_preview(mock_bot):
    """Test profile preview rendering."""
    cog = Mimic(mock_bot)
    ctx = _make_ctx()

    await cog._execute_preview(ctx)

    ctx.reply.assert_awaited()
    sent_embed = ctx.reply.call_args[1]["embed"]
    assert "Mimic Identity Profile" in sent_embed.title
    assert "Server Persona" in sent_embed.description
    assert "Server-specific banners are not supported" in sent_embed.description


@pytest.mark.asyncio
async def test_mimic_reset(mock_bot):
    """Test resetting mimic persona back to global defaults."""
    cog = Mimic(mock_bot)
    ctx = _make_ctx()

    await cog._execute_reset(ctx)

    ctx.guild.me.edit.assert_awaited_with(nick=None, reason="Death Bot Mimic Persona reset by AdminUser")
    mock_bot.mimic_repo.reset_profile.assert_awaited_with(999888)
    ctx.reply.assert_awaited()


@pytest.mark.asyncio
async def test_mimic_sqlite_guild_isolation():
    """Verify in real SQLite that changing Guild A identity leaves Guild B untouched."""
    from bot.database.sqlite_manager import SQLiteDatabaseManager
    from pathlib import Path

    db_path = Path("db/test_mimic_isolation.sqlite")
    if db_path.exists():
        db_path.unlink()

    db = SQLiteDatabaseManager(db_path)
    await db.connect()
    repo = MimicRepository(db)

    guild_a = 1111
    guild_b = 2222

    # Set Guild A
    await repo.set_nickname(guild_a, "Guild A Bot")
    await repo.set_avatar(guild_a, "https://example.com/a.png")

    # Set Guild B
    await repo.set_nickname(guild_b, "Guild B Bot")
    await repo.set_avatar(guild_b, "https://example.com/b.png")

    prof_a = await repo.get_profile(guild_a)
    prof_b = await repo.get_profile(guild_b)

    assert prof_a["nickname"] == "Guild A Bot"
    assert prof_a["avatar_url"] == "https://example.com/a.png"
    assert prof_b["nickname"] == "Guild B Bot"
    assert prof_b["avatar_url"] == "https://example.com/b.png"

    # Reset Guild A
    await repo.reset_profile(guild_a)
    assert await repo.get_profile(guild_a) == {}
    # Guild B must remain intact
    prof_b_after = await repo.get_profile(guild_b)
    assert prof_b_after["nickname"] == "Guild B Bot"

    await db.close()
    if db_path.exists():
        db_path.unlink()


@pytest.mark.asyncio
async def test_mimic_avatar_api_rejection_leaves_sqlite_untouched(mock_bot):
    """D-02: If Discord API rejects the avatar update, SQLite must remain untouched."""
    cog = Mimic(mock_bot)
    ctx = _make_ctx()

    # Discord rejects with HTTPException
    ctx.guild.me.edit.side_effect = discord.HTTPException(
        response=MagicMock(status=400),
        message="400 Bad Request: Missing Server Avatar Entitlement"
    )

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.read = AsyncMock(return_value=b"fake_image_bytes")
    mock_resp.headers = {"Content-Type": "image/png"}

    mock_session_inst = MagicMock()
    mock_session_inst.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session_inst.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
    mock_session_inst.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session_inst):
        await cog._execute_avatar(ctx, "https://example.com/avatar.png")

    # Verify Discord API was attempted
    ctx.guild.me.edit.assert_awaited()
    # Verify error message sent to user
    ctx.send_error.assert_awaited()
    err_args = ctx.send_error.call_args[0]
    assert "Discord API Restriction" in err_args[0]
    # SQLite repository must NOT have been called
    mock_bot.mimic_repo.set_avatar.assert_not_called()


@pytest.mark.asyncio
async def test_mimic_avatar_api_success_persists_to_sqlite(mock_bot):
    """D-02: If Discord API confirms success, SQLite is updated and success embed sent."""
    cog = Mimic(mock_bot)
    ctx = _make_ctx()

    ctx.guild.me.edit.side_effect = None
    ctx.guild.me.edit.return_value = None

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.read = AsyncMock(return_value=b"fake_image_bytes")
    mock_resp.headers = {"Content-Type": "image/png"}

    mock_session_inst = MagicMock()
    mock_session_inst.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session_inst.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
    mock_session_inst.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session_inst):
        await cog._execute_avatar(ctx, "https://example.com/avatar.png")

    ctx.guild.me.edit.assert_awaited()
    mock_bot.mimic_repo.set_avatar.assert_awaited_with(999888, "https://example.com/avatar.png")
    ctx.reply.assert_awaited()
    sent_embed = ctx.reply.call_args[1]["embed"]
    assert "Mimic Avatar Updated" in sent_embed.title
    assert "Discord API confirmed" in sent_embed.description


@pytest.mark.asyncio
async def test_mimic_avatar_db_failure_transparent_warning(mock_bot):
    """D-02: If Discord API succeeds but SQLite save fails, user receives a transparent warning."""
    cog = Mimic(mock_bot)
    ctx = _make_ctx()

    ctx.guild.me.edit.side_effect = None
    mock_bot.mimic_repo.set_avatar.side_effect = Exception("Disk I/O failure")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.read = AsyncMock(return_value=b"fake_image_bytes")
    mock_resp.headers = {"Content-Type": "image/png"}

    mock_session_inst = MagicMock()
    mock_session_inst.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session_inst.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
    mock_session_inst.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session_inst):
        await cog._execute_avatar(ctx, "https://example.com/avatar.png")

    ctx.guild.me.edit.assert_awaited()
    mock_bot.mimic_repo.set_avatar.assert_awaited()
    ctx.reply.assert_awaited()
    sent_embed = ctx.reply.call_args[1]["embed"]
    assert "Avatar Applied (Storage Warning)" in sent_embed.title
    assert "Database Warning" in sent_embed.description

