"""Unit tests for Phase 4 Voice Channel Automation and Community Management."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import VCRepository
from bot.services.voice_service import VoiceService
from bot.cogs.voice.cog import Voice


def run_async(coro):
    return asyncio.run(coro)


def test_vc_repository_temp_channel_crud(tmp_path: Path):
    """Test registering, checking, listing and removing temporary voice channels in SQLite."""
    async def _test():
        db_file = tmp_path / "test_temp_vc.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = VCRepository(db)
            guild_id = 999
            ch_id = 888123
            owner_id = 777456

            # Initially false
            assert await repo.is_temp_channel(guild_id, ch_id) is False

            # Register
            await repo.register_temp_channel(guild_id, ch_id, owner_id)
            assert await repo.is_temp_channel(guild_id, ch_id) is True

            # Check ownership was set
            owner_rec = await repo.get_vc_owner(guild_id, ch_id)
            assert owner_rec is not None
            assert owner_rec["owner_id"] == owner_id

            # List
            temp_channels = await repo.get_temp_channels(guild_id)
            assert ch_id in temp_channels

            # Remove
            await repo.remove_temp_channel(guild_id, ch_id)
            assert await repo.is_temp_channel(guild_id, ch_id) is False
            assert await repo.get_vc_owner(guild_id, ch_id) is None
        finally:
            await db.close()

    run_async(_test())


def test_voice_service_cleanup_empty_temp_channel(tmp_path: Path):
    """Test VoiceService automatically deletes empty temporary channels."""
    async def _test():
        db_file = tmp_path / "test_voice_service.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            bot = MagicMock()
            bot.db = db
            bot.db_manager = db
            bot.vc_repo = VCRepository(db)

            voice_repo = MagicMock()
            service = VoiceService(bot, voice_repo)

            guild_id = 1000
            ch_id = 2000
            owner_id = 3000

            # Register as temp channel
            await bot.vc_repo.register_temp_channel(guild_id, ch_id, owner_id)

            # Mock empty channel
            mock_channel = MagicMock(spec=discord.VoiceChannel)
            mock_channel.id = ch_id
            mock_channel.guild = MagicMock()
            mock_channel.guild.id = guild_id
            mock_channel.guild.name = "Test Guild"
            mock_channel.name = "Temp VC #1"
            mock_channel.members = []
            mock_channel.delete = AsyncMock()

            # Trigger cleanup
            await service._check_and_cleanup_temp_channel(mock_channel)

            # Verify channel deletion was called
            mock_channel.delete.assert_awaited_once()

            # Verify temp channel record was removed from SQLite
            assert await bot.vc_repo.is_temp_channel(guild_id, ch_id) is False
        finally:
            await db.close()

    run_async(_test())


def test_voice_service_skips_cleanup_if_members_present(tmp_path: Path):
    """Test VoiceService does NOT delete a temp channel if members are still connected."""
    async def _test():
        db_file = tmp_path / "test_voice_service_skip.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            bot = MagicMock()
            bot.db = db
            bot.db_manager = db
            bot.vc_repo = VCRepository(db)

            voice_repo = MagicMock()
            service = VoiceService(bot, voice_repo)

            guild_id = 1000
            ch_id = 2001
            owner_id = 3000

            await bot.vc_repo.register_temp_channel(guild_id, ch_id, owner_id)

            # Mock non-empty channel
            mock_member = MagicMock(spec=discord.Member)
            mock_member.bot = False

            mock_channel = MagicMock(spec=discord.VoiceChannel)
            mock_channel.id = ch_id
            mock_channel.guild = MagicMock()
            mock_channel.guild.id = guild_id
            mock_channel.members = [mock_member]
            mock_channel.delete = AsyncMock()

            await service._check_and_cleanup_temp_channel(mock_channel)

            # Deletion should NOT be called
            mock_channel.delete.assert_not_called()
            assert await bot.vc_repo.is_temp_channel(guild_id, ch_id) is True
        finally:
            await db.close()

    run_async(_test())


def test_vc_claim_and_transfer_commands(tmp_path: Path):
    """Test vcclaim, vctransfer, and vcowner commands in Voice cog."""
    async def _test():
        db_file = tmp_path / "test_voice_commands.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            bot = MagicMock()
            bot.db = db
            bot.db_manager = db
            bot.vc_repo = VCRepository(db)

            cog = Voice(bot)
            guild_id = 1111
            ch_id = 2222
            original_owner_id = 3333
            new_claimer_id = 4444

            await bot.vc_repo.register_temp_channel(guild_id, ch_id, original_owner_id)

            # Mock voice channel
            mock_channel = MagicMock(spec=discord.VoiceChannel)
            mock_channel.id = ch_id
            mock_channel.mention = "<#2222>"
            mock_channel.members = []

            # 1. Claim when original owner is absent
            claimer = MagicMock(spec=discord.Member)
            claimer.id = new_claimer_id
            claimer.mention = f"<@{new_claimer_id}>"
            claimer.voice = MagicMock(channel=mock_channel)
            mock_channel.members.append(claimer)

            ctx_claim = MagicMock()
            ctx_claim.author = claimer
            ctx_claim.guild = MagicMock()
            ctx_claim.guild.id = guild_id
            ctx_claim.guild.owner_id = 99999
            ctx_claim.guild.get_member = MagicMock(return_value=None)
            ctx_claim.reply = AsyncMock()

            await cog._execute_vcclaim(ctx_claim)
            assert ctx_claim.reply.called
            owner_rec = await bot.vc_repo.get_vc_owner(guild_id, ch_id)
            assert owner_rec["owner_id"] == new_claimer_id

            # 2. Transfer to third member
            third_member = MagicMock(spec=discord.Member)
            third_member.id = 5555
            third_member.bot = False
            third_member.mention = "<@5555>"
            mock_channel.members.append(third_member)

            ctx_transfer = MagicMock()
            ctx_transfer.author = claimer  # Current owner
            ctx_transfer.guild = ctx_claim.guild
            ctx_transfer.reply = AsyncMock()

            await cog._execute_vctransfer(ctx_transfer, third_member)
            assert ctx_transfer.reply.called
            owner_rec_after = await bot.vc_repo.get_vc_owner(guild_id, ch_id)
            assert owner_rec_after["owner_id"] == 5555

            # 3. Owner command inspect
            ctx_owner = MagicMock()
            ctx_owner.author = claimer
            ctx_owner.guild = ctx_claim.guild
            ctx_owner.reply = AsyncMock()
            await cog._execute_vcowner(ctx_owner)
            assert ctx_owner.reply.called
        finally:
            await db.close()

    run_async(_test())
