"""Phase 3 Master Test Suite: Moderation & AutoMod Ecosystem (P3-TC01 to P3-TC10).

This suite verifies:
- P3-TC01: Ban and unban lifecycle & case logging
- P3-TC02: Kick execution, case logging & permission enforcement
- P3-TC03: Timeout and untimeout lifecycle, bounds & duration
- P3-TC04: Warn system, active count, warnings history & clearwarns
- P3-TC05: Moderator role hierarchy enforcement
- P3-TC06: Bot role hierarchy enforcement
- P3-TC07: Sovereign and bot owner immunity (Moderation & AutoMod)
- P3-TC08: Channel lock, unlock, and slowmode bounds
- P3-TC09: Channel purge bulk deletion bounds & permissions
- P3-TC10: AutoMod pipeline, regex, exemptions & 24h punishment escalation ladder
"""

import asyncio
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.cogs.moderation.cog import Moderation
from bot.services.automod_service import AutoModService
from bot.core.context import UnifiedContext
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.database.repositories.sqlite_repos import ModerationRepository


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 10001
    guild.name = "Phase3 Test Guild"
    guild.owner_id = 90001
    guild.default_role = MagicMock(spec=discord.Role)
    guild.ban = AsyncMock()
    guild.unban = AsyncMock()
    return guild


@pytest.fixture
def mock_bot(tmp_path: Path):
    bot = MagicMock()
    bot.config = MagicMock()
    bot.config.owner_ids = [99901, 99902]
    bot.owner_ids = [99901, 99902]
    return bot


def test_p3_tc01_ban_and_unban_lifecycle(tmp_path: Path, mock_guild, mock_bot):
    """P3-TC01: Ban and unban lifecycle with reason, delete_days, and case logging."""
    async def _test():
        db_file = tmp_path / "test_p3_tc01.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = ModerationRepository(db)
            mock_bot.db = db
            mock_bot.moderation_repo = repo
            cog = Moderation(mock_bot)

            bot_member = MagicMock(spec=discord.Member)
            bot_member.id = 80001
            bot_member.guild_permissions.ban_members = True
            bot_member.top_role = MagicMock(position=50)
            mock_guild.me = bot_member

            mod = MagicMock(spec=discord.Member)
            mod.id = 70001
            mod.guild = mock_guild
            mod.guild_permissions.ban_members = True
            mod.top_role = MagicMock(position=40)

            target = MagicMock(spec=discord.Member)
            target.id = 60001
            target.guild = mock_guild
            target.top_role = MagicMock(position=10)

            # 1. Ban Execution
            ctx_ban = MagicMock(spec=UnifiedContext)
            ctx_ban.guild = mock_guild
            ctx_ban.author = mod
            ctx_ban.reply = AsyncMock()

            await cog._execute_ban(ctx_ban, target, "Griefing channels", delete_days=1)
            mock_guild.ban.assert_awaited_once_with(
                target,
                reason=f"Griefing channels (Executor: {mod})",
                delete_message_seconds=86400,
            )
            assert ctx_ban.reply.called

            # Verify Case Log
            cases = await repo.get_user_cases(mock_guild.id, target.id)
            assert len(cases) == 1
            assert cases[0].action == "BAN"
            assert cases[0].reason == "Griefing channels"

            # 2. Unban Execution
            unban_user = MagicMock(spec=discord.User)
            unban_user.id = target.id
            unban_user.name = "UnbannedUser"
            mock_bot.fetch_user = AsyncMock(return_value=unban_user)

            ctx_unban = MagicMock(spec=UnifiedContext)
            ctx_unban.guild = mock_guild
            ctx_unban.author = mod
            ctx_unban.reply = AsyncMock()

            await cog._execute_unban(ctx_unban, str(target.id), "Appeal approved")
            mock_guild.unban.assert_awaited_once_with(
                unban_user,
                reason=f"Appeal approved (Executor: {mod})",
            )
            assert ctx_unban.reply.called

            cases_after_unban = await repo.get_user_cases(mock_guild.id, target.id)
            assert len(cases_after_unban) == 2
            assert cases_after_unban[0].action == "UNBAN"

            # 3. Invalid User ID handling
            ctx_err = MagicMock(spec=UnifiedContext)
            ctx_err.guild = mock_guild
            ctx_err.author = mod
            ctx_err.send_error = AsyncMock()
            await cog._execute_unban(ctx_err, "not-a-number", "reason")
            ctx_err.send_error.assert_awaited_once_with(
                "Invalid ID", "Please specify a valid numeric User ID."
            )
        finally:
            await db.close()

    run_async(_test())


def test_p3_tc02_kick_execution_and_cases(tmp_path: Path, mock_guild, mock_bot):
    """P3-TC02: Kick execution, audit case logging, and permission validation."""
    async def _test():
        db_file = tmp_path / "test_p3_tc02.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = ModerationRepository(db)
            mock_bot.db = db
            mock_bot.moderation_repo = repo
            cog = Moderation(mock_bot)

            bot_member = MagicMock(spec=discord.Member)
            bot_member.id = 80001
            bot_member.guild_permissions.kick_members = True
            bot_member.top_role = MagicMock(position=50)
            mock_guild.me = bot_member

            mod = MagicMock(spec=discord.Member)
            mod.id = 70001
            mod.guild = mock_guild
            mod.guild_permissions.kick_members = True
            mod.top_role = MagicMock(position=40)

            target = MagicMock(spec=discord.Member)
            target.id = 60002
            target.guild = mock_guild
            target.top_role = MagicMock(position=10)
            target.kick = AsyncMock()

            # 1. Successful Kick
            ctx = MagicMock(spec=UnifiedContext)
            ctx.guild = mock_guild
            ctx.author = mod
            ctx.reply = AsyncMock()

            await cog._execute_kick(ctx, target, "Insubordination")
            target.kick.assert_awaited_once_with(reason=f"Insubordination (Executor: {mod})")
            cases = await repo.get_user_cases(mock_guild.id, target.id)
            assert len(cases) == 1
            assert cases[0].action == "KICK"
            assert cases[0].reason == "Insubordination"

            # 2. Permission Denied: Moderator lacks kick permission
            unauthorized_mod = MagicMock(spec=discord.Member)
            unauthorized_mod.id = 70002
            unauthorized_mod.guild = mock_guild
            unauthorized_mod.guild_permissions.kick_members = False
            ctx_denied = MagicMock(spec=UnifiedContext)
            ctx_denied.guild = mock_guild
            ctx_denied.author = unauthorized_mod
            ctx_denied.send_error = AsyncMock()

            await cog._execute_kick(ctx_denied, target, "test")
            ctx_denied.send_error.assert_awaited_with(
                "Access Denied", "You need the **Kick Members** permission."
            )

            # 3. Missing Permission: Bot lacks kick permission
            bot_member.guild_permissions.kick_members = False
            ctx_bot_denied = MagicMock(spec=UnifiedContext)
            ctx_bot_denied.guild = mock_guild
            ctx_bot_denied.author = mod
            ctx_bot_denied.send_error = AsyncMock()

            await cog._execute_kick(ctx_bot_denied, target, "test")
            ctx_bot_denied.send_error.assert_awaited_with(
                "Missing Permission", "I need the **Kick Members** permission."
            )
        finally:
            await db.close()

    run_async(_test())


def test_p3_tc03_timeout_and_untimeout_lifecycle(tmp_path: Path, mock_guild, mock_bot):
    """P3-TC03: Timeout and untimeout lifecycle, duration bounds, and case logging."""
    async def _test():
        db_file = tmp_path / "test_p3_tc03.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = ModerationRepository(db)
            mock_bot.db = db
            mock_bot.moderation_repo = repo
            cog = Moderation(mock_bot)

            bot_member = MagicMock(spec=discord.Member)
            bot_member.id = 80001
            bot_member.guild_permissions.moderate_members = True
            bot_member.top_role = MagicMock(position=50)
            mock_guild.me = bot_member

            mod = MagicMock(spec=discord.Member)
            mod.id = 70001
            mod.guild = mock_guild
            mod.guild_permissions.moderate_members = True
            mod.top_role = MagicMock(position=40)

            target = MagicMock(spec=discord.Member)
            target.id = 60003
            target.guild = mock_guild
            target.top_role = MagicMock(position=10)
            target.timeout = AsyncMock()

            # 1. Bounds Validation: < 1 minute
            ctx_low = MagicMock(spec=UnifiedContext)
            ctx_low.guild = mock_guild
            ctx_low.author = mod
            ctx_low.send_error = AsyncMock()
            await cog._execute_timeout(ctx_low, target, 0, "Too short")
            ctx_low.send_error.assert_awaited_with(
                "Invalid Duration",
                "Timeout duration must be between 1 minute and 28 days (40,320 mins).",
            )

            # 2. Bounds Validation: > 40320 minutes (28 days)
            ctx_high = MagicMock(spec=UnifiedContext)
            ctx_high.guild = mock_guild
            ctx_high.author = mod
            ctx_high.send_error = AsyncMock()
            await cog._execute_timeout(ctx_high, target, 50000, "Too long")
            ctx_high.send_error.assert_awaited_with(
                "Invalid Duration",
                "Timeout duration must be between 1 minute and 28 days (40,320 mins).",
            )

            # 3. Valid Timeout (60 mins)
            ctx_valid = MagicMock(spec=UnifiedContext)
            ctx_valid.guild = mock_guild
            ctx_valid.author = mod
            ctx_valid.reply = AsyncMock()
            await cog._execute_timeout(ctx_valid, target, 60, "Excessive mic spam")
            target.timeout.assert_awaited_once()
            timeout_arg = target.timeout.await_args[0][0]
            assert isinstance(timeout_arg, datetime)
            assert timeout_arg > datetime.now(timezone.utc)

            cases = await repo.get_user_cases(mock_guild.id, target.id)
            assert len(cases) == 1
            assert cases[0].action == "TIMEOUT"
            assert cases[0].duration_seconds == 3600

            # 4. Untimeout
            ctx_untimeout = MagicMock(spec=UnifiedContext)
            ctx_untimeout.guild = mock_guild
            ctx_untimeout.author = mod
            ctx_untimeout.reply = AsyncMock()
            target.timeout.reset_mock()
            await cog._execute_untimeout(ctx_untimeout, target, "Cooldown elapsed")
            target.timeout.assert_awaited_once_with(
                None, reason=f"Untimeout: Cooldown elapsed (Executor: {mod})"
            )
            cases_untimeout = await repo.get_user_cases(mock_guild.id, target.id)
            assert len(cases_untimeout) == 2
            assert cases_untimeout[0].action == "UNTIMEOUT"
        finally:
            await db.close()

    run_async(_test())


def test_p3_tc04_warn_system_and_history(tmp_path: Path, mock_guild, mock_bot):
    """P3-TC04: Warn system, active warnings count, history retrieval, and clearwarns."""
    async def _test():
        db_file = tmp_path / "test_p3_tc04.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            repo = ModerationRepository(db)
            mock_bot.db = db
            mock_bot.moderation_repo = repo
            cog = Moderation(mock_bot)

            bot_member = MagicMock(spec=discord.Member)
            bot_member.id = 80001
            bot_member.top_role = MagicMock(position=50)
            mock_guild.me = bot_member

            mod = MagicMock(spec=discord.Member)
            mod.id = 70001
            mod.guild = mock_guild
            mod.guild_permissions.manage_messages = True
            mod.guild_permissions.manage_guild = True
            mod.top_role = MagicMock(position=40)

            target = MagicMock(spec=discord.Member)
            target.id = 60004
            target.guild = mock_guild
            target.top_role = MagicMock(position=10)
            target.display_avatar.url = "http://avatar.example.com"

            # 1. Warn 1
            ctx_w1 = MagicMock(spec=UnifiedContext)
            ctx_w1.guild = mock_guild
            ctx_w1.author = mod
            ctx_w1.reply = AsyncMock()
            await cog._execute_warn(ctx_w1, target, "Disrespectful conduct")
            assert ctx_w1.reply.called

            # 2. Warn 2
            ctx_w2 = MagicMock(spec=UnifiedContext)
            ctx_w2.guild = mock_guild
            ctx_w2.author = mod
            ctx_w2.reply = AsyncMock()
            await cog._execute_warn(ctx_w2, target, "Posting self-promo")
            assert ctx_w2.reply.called

            # Check warning records
            warns = await repo.get_warnings(mock_guild.id, target.id)
            assert len(warns) == 2
            assert warns[0]["reason"] == "Posting self-promo"

            # 3. Warnings History Command
            ctx_history = MagicMock(spec=UnifiedContext)
            ctx_history.guild = mock_guild
            ctx_history.author = mod
            ctx_history.reply = AsyncMock()
            await cog._execute_warnings(ctx_history, target)
            assert ctx_history.reply.called
            embed_arg = ctx_history.reply.call_args[1]["embed"]
            assert "Warn #" in embed_arg.description

            # 4. Clear Warnings
            ctx_clear = MagicMock(spec=UnifiedContext)
            ctx_clear.guild = mock_guild
            ctx_clear.author = mod
            ctx_clear.reply = AsyncMock()
            await cog._execute_clearwarns(ctx_clear, target)
            assert ctx_clear.reply.called

            remaining_warns = await repo.get_warnings(mock_guild.id, target.id)
            assert len(remaining_warns) == 0
        finally:
            await db.close()

    run_async(_test())


def test_p3_tc05_moderator_role_hierarchy_enforced(mock_guild, mock_bot):
    """P3-TC05: Target top role >= moderator top role blocks moderation action."""
    cog = Moderation(mock_bot)

    bot_member = MagicMock(spec=discord.Member)
    bot_member.id = 80001
    bot_member.top_role = MagicMock(position=50)

    mod = MagicMock(spec=discord.Member)
    mod.id = 70001
    mod.guild = mock_guild
    mod.top_role = MagicMock(position=30)

    # Higher role
    high_target = MagicMock(spec=discord.Member)
    high_target.id = 60005
    high_target.guild = mock_guild
    high_target.top_role = MagicMock(position=35)

    err = cog._check_hierarchy(mod, bot_member, high_target)
    assert err is not None
    assert "their highest role is equal to or higher than yours" in err

    # Equal role
    equal_target = MagicMock(spec=discord.Member)
    equal_target.id = 60006
    equal_target.guild = mock_guild
    equal_target.top_role = MagicMock(position=30)

    err2 = cog._check_hierarchy(mod, bot_member, equal_target)
    assert err2 is not None
    assert "their highest role is equal to or higher than yours" in err2


def test_p3_tc06_bot_role_hierarchy_enforced(mock_guild, mock_bot):
    """P3-TC06: Target top role >= bot top role blocks moderation action safely."""
    cog = Moderation(mock_bot)

    bot_member = MagicMock(spec=discord.Member)
    bot_member.id = 80001
    bot_member.top_role = MagicMock(position=40)

    mod = MagicMock(spec=discord.Member)
    mod.id = 70001
    mod.guild = mock_guild
    mod.top_role = MagicMock(position=60)

    # Target higher than bot
    target = MagicMock(spec=discord.Member)
    target.id = 60007
    target.guild = mock_guild
    target.top_role = MagicMock(position=45)

    err = cog._check_hierarchy(mod, bot_member, target)
    assert err is not None
    assert "my role is not high enough" in err

    # Target equal to bot
    target_eq = MagicMock(spec=discord.Member)
    target_eq.id = 60008
    target_eq.guild = mock_guild
    target_eq.top_role = MagicMock(position=40)

    err_eq = cog._check_hierarchy(mod, bot_member, target_eq)
    assert err_eq is not None
    assert "my role is not high enough" in err_eq


def test_p3_tc07_sovereign_and_bot_owner_immunity(mock_guild, mock_bot):
    """P3-TC07: Server Owner and Bot Owner immunity in Moderation and AutoMod."""
    cog = Moderation(mock_bot)

    bot_member = MagicMock(spec=discord.Member)
    bot_member.id = 80001
    bot_member.top_role = MagicMock(position=100)

    mod = MagicMock(spec=discord.Member)
    mod.id = 70001
    mod.guild = mock_guild
    mod.top_role = MagicMock(position=90)

    # 1. Server Owner is immune
    server_owner = MagicMock(spec=discord.Member)
    server_owner.id = mock_guild.owner_id
    server_owner.top_role = MagicMock(position=1)
    err_sovereign = cog._check_hierarchy(mod, bot_member, server_owner)
    assert "Server Sovereign" in err_sovereign

    # 2. Bot Owner is immune
    bot_owner = MagicMock(spec=discord.Member)
    bot_owner.id = 99901
    bot_owner.top_role = MagicMock(position=1)
    err_bot_owner = cog._check_hierarchy(mod, bot_member, bot_owner)
    assert "Cannot execute moderation actions on a KROVEX Bot Owner" in err_bot_owner

    # 3. AutoMod Immunity
    automod = AutoModService(mock_bot)
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 5555

    # Server Owner exempt from AutoMod
    owner_member = MagicMock(spec=discord.Member)
    owner_member.id = mock_guild.owner_id
    owner_member.guild = mock_guild
    owner_member.guild_permissions.administrator = False
    owner_member.roles = []
    assert automod._is_exempt(owner_member, channel, [], []) is True

    # Bot Owner exempt from AutoMod
    bot_owner_member = MagicMock(spec=discord.Member)
    bot_owner_member.id = 99901
    bot_owner_member.guild = mock_guild
    bot_owner_member.guild_permissions.administrator = False
    bot_owner_member.roles = []
    assert automod._is_exempt(bot_owner_member, channel, [], []) is True

    # Regular non-admin user is not exempt
    regular_member = MagicMock(spec=discord.Member)
    regular_member.id = 12345
    regular_member.guild = mock_guild
    regular_member.guild_permissions.administrator = False
    regular_member.roles = []
    assert automod._is_exempt(regular_member, channel, [], []) is False


def test_p3_tc08_channel_lock_unlock_slowmode(mock_guild, mock_bot):
    """P3-TC08: Channel lock, unlock, and slowmode delay bounds (0-21600s)."""
    async def _test():
        cog = Moderation(mock_bot)

        bot_member = MagicMock(spec=discord.Member)
        bot_member.guild_permissions.manage_channels = True
        mock_guild.me = bot_member

        mod = MagicMock(spec=discord.Member)
        mod.id = 70001
        mod.guild = mock_guild
        mod.guild_permissions.manage_channels = True

        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = mock_guild
        channel.mention = "<#12345>"
        channel.set_permissions = AsyncMock()
        channel.edit = AsyncMock()

        ctx = MagicMock(spec=UnifiedContext)
        ctx.guild = mock_guild
        ctx.channel = channel
        ctx.author = mod
        ctx.reply = AsyncMock()
        ctx.send_success = AsyncMock()
        ctx.send_error = AsyncMock()

        # 1. Lock channel
        await cog._execute_lock(ctx, channel)
        channel.set_permissions.assert_awaited_with(
            mock_guild.default_role, send_messages=False, reason=f"Channel Lock by {mod}"
        )
        assert ctx.reply.called

        # 2. Unlock channel
        channel.set_permissions.reset_mock()
        ctx.reply.reset_mock()
        await cog._execute_unlock(ctx, channel)
        channel.set_permissions.assert_awaited_with(
            mock_guild.default_role, send_messages=None, reason=f"Channel Unlock by {mod}"
        )
        assert ctx.reply.called

        # 3. Slowmode valid (15s)
        await cog._execute_slowmode(ctx, 15)
        channel.edit.assert_awaited_with(slowmode_delay=15, reason=f"Slowmode updated by {mod}")
        ctx.send_success.assert_awaited_with("Slowmode Configured", f"Slowmode in {channel.mention} is now set to **15s**.")

        # 4. Slowmode disabled (0s)
        channel.edit.reset_mock()
        ctx.send_success.reset_mock()
        await cog._execute_slowmode(ctx, 0)
        channel.edit.assert_awaited_with(slowmode_delay=0, reason=f"Slowmode updated by {mod}")
        ctx.send_success.assert_awaited_with("Slowmode Disabled", f"Slowmode has been removed from {channel.mention}.")

        # 5. Slowmode out of bounds (> 21600s)
        await cog._execute_slowmode(ctx, 25000)
        ctx.send_error.assert_awaited_with(
            "Invalid Range", "Slowmode duration must be between 0 and 21,600 seconds (6 hours)."
        )

        # 6. Slowmode negative (< 0)
        ctx.send_error.reset_mock()
        await cog._execute_slowmode(ctx, -5)
        ctx.send_error.assert_awaited_with(
            "Invalid Range", "Slowmode duration must be between 0 and 21,600 seconds (6 hours)."
        )

    run_async(_test())


def test_p3_tc09_channel_purge_bulk_delete(mock_guild, mock_bot):
    """P3-TC09: Channel purge bulk delete bounds (1-100) and permission validation."""
    async def _test():
        cog = Moderation(mock_bot)

        bot_member = MagicMock(spec=discord.Member)
        bot_member.guild_permissions.manage_messages = True
        mock_guild.me = bot_member

        mod = MagicMock(spec=discord.Member)
        mod.id = 70001
        mod.guild = mock_guild
        mod.guild_permissions.manage_messages = True

        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = mock_guild
        channel.purge = AsyncMock(return_value=[MagicMock() for _ in range(25)])

        ctx = MagicMock(spec=UnifiedContext)
        ctx.guild = mock_guild
        ctx.channel = channel
        ctx.author = mod
        ctx.reply = AsyncMock()
        ctx.send_error = AsyncMock()
        ctx._source = MagicMock()

        # 1. Valid purge (25 messages)
        await cog._execute_purge(ctx, 25)
        channel.purge.assert_awaited_once_with(limit=25)
        assert ctx.reply.called

        # 2. Out of bounds low (< 1)
        await cog._execute_purge(ctx, 0)
        ctx.send_error.assert_awaited_with(
            "Invalid Range", "Purge amount must be between 1 and 100."
        )

        # 3. Out of bounds high (> 100)
        ctx.send_error.reset_mock()
        await cog._execute_purge(ctx, 101)
        ctx.send_error.assert_awaited_with(
            "Invalid Range", "Purge amount must be between 1 and 100."
        )

        # 4. Moderator missing manage_messages permission
        mod.guild_permissions.manage_messages = False
        ctx_no_perm = MagicMock(spec=UnifiedContext)
        ctx_no_perm.guild = mock_guild
        ctx_no_perm.channel = channel
        ctx_no_perm.author = mod
        ctx_no_perm.send_error = AsyncMock()

        await cog._execute_purge(ctx_no_perm, 10)
        ctx_no_perm.send_error.assert_awaited_with(
            "Access Denied", "You need the **Manage Messages** permission."
        )
    run_async(_test())


def test_p3_tc10_automod_pipeline_and_escalation(tmp_path: Path, mock_guild, mock_bot):
    """P3-TC10: AutoMod filters, regex rules, exemptions, and 24h punishment ladder escalation."""
    async def _test():
        db_file = tmp_path / "test_p3_tc10.sqlite"
        db = SQLiteDatabaseManager(db_path=db_file)
        await db.connect()
        try:
            mock_bot.db = db
            automod = AutoModService(mock_bot)

            # Seed automod settings
            await db.execute(
                """
                INSERT INTO automod_settings (
                    guild_id, enabled, bad_words_enabled, bad_words_list,
                    invites_blocked, links_blocked, caps_enabled, caps_percentage,
                    caps_min_chars, emojis_enabled, emoji_limit, mention_limit,
                    flood_interval_seconds
                ) VALUES (?, 1, 1, ?, 1, 1, 1, 70, 10, 1, 5, 3, 1.0)
                """,
                (mock_guild.id, json.dumps(["malware", "scamlink"])),
            )

            # Insert custom regex rule
            await db.execute(
                """
                INSERT INTO automod_rules (guild_id, name, rule_type, pattern, action, duration_seconds, enabled)
                VALUES (?, 'crypto-phish', 'regex', '(?i)free\\s+nitro', 'timeout', 300, 1)
                """,
                (mock_guild.id,),
            )

            channel = MagicMock(spec=discord.TextChannel)
            channel.id = 5001
            channel.send = AsyncMock()

            author = MagicMock(spec=discord.Member)
            author.id = 40001
            author.bot = False
            author.guild = mock_guild
            author.guild_permissions.administrator = False
            author.roles = []
            author.timeout = AsyncMock()

            # 1. Bad words trigger
            msg_bad = MagicMock(spec=discord.Message)
            msg_bad.guild = mock_guild
            msg_bad.channel = channel
            msg_bad.author = author
            msg_bad.content = "Check out this malware download"
            msg_bad.delete = AsyncMock()
            msg_bad.mentions = []
            msg_bad.role_mentions = []

            await automod.on_message(msg_bad)
            msg_bad.delete.assert_awaited_once()

            # Check violation recorded
            violations = await db.fetchall(
                "SELECT * FROM automod_violations WHERE guild_id=? AND user_id=?",
                (mock_guild.id, author.id),
            )
            assert len(violations) == 1
            assert violations[0]["rule_type"] == "bad_word"

            # 2. Custom Regex Rule Trigger
            msg_regex = MagicMock(spec=discord.Message)
            msg_regex.guild = mock_guild
            msg_regex.channel = channel
            msg_regex.author = author
            msg_regex.content = "Claim your free  nitro now!"
            msg_regex.delete = AsyncMock()
            msg_regex.mentions = []
            msg_regex.role_mentions = []

            await automod.on_message(msg_regex)
            msg_regex.delete.assert_awaited_once()

            # 3. Invite Filter Trigger
            msg_invite = MagicMock(spec=discord.Message)
            msg_invite.guild = mock_guild
            msg_invite.channel = channel
            msg_invite.author = author
            msg_invite.content = "Join my server at discord.gg/abcde"
            msg_invite.delete = AsyncMock()
            msg_invite.mentions = []
            msg_invite.role_mentions = []

            await automod.on_message(msg_invite)
            msg_invite.delete.assert_awaited_once()

            # 4. Link Filter Trigger
            msg_link = MagicMock(spec=discord.Message)
            msg_link.guild = mock_guild
            msg_link.channel = channel
            msg_link.author = author
            msg_link.content = "Visit https://suspicious-site.xyz/login"
            msg_link.delete = AsyncMock()
            msg_link.mentions = []
            msg_link.role_mentions = []

            await automod.on_message(msg_link)
            msg_link.delete.assert_awaited_once()

            # Now user has 4 violations in 24h.
            # Next violation should hit the 5+ escalation ladder -> 1-hour timeout (3600s).
            author.timeout.reset_mock()
            msg_escalate = MagicMock(spec=discord.Message)
            msg_escalate.guild = mock_guild
            msg_escalate.channel = channel
            msg_escalate.author = author
            msg_escalate.content = "Another scamlink here"
            msg_escalate.delete = AsyncMock()
            msg_escalate.mentions = []
            msg_escalate.role_mentions = []

            await automod.on_message(msg_escalate)
            msg_escalate.delete.assert_awaited_once()
            author.timeout.assert_awaited_once()

            # Check that the timeout applied was escalated to 1 hour (3600s)
            timeout_arg = author.timeout.await_args[0][0]
            reason_arg = author.timeout.await_args[1].get("reason", "")
            assert "Infraction #5 in 24h" in reason_arg
            assert (timeout_arg - datetime.now(timezone.utc)).total_seconds() > 3500
        finally:
            await db.close()

    run_async(_test())
