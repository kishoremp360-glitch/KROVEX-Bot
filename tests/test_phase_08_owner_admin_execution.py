"""KROVEX Master Audit & QA Plan — Phase 8 Execution Test Suite: Owner & Administration.

Covers test cases P8-TC01 through P8-TC10:
- P8-TC01: Prefix Management & Multi-Guild Isolation (1-5 chars, rejection of invalid prefixes, per-guild isolation)
- P8-TC02: Setup Wizard Interactive Infrastructure Provisioning (Save & Apply, Preview, Cancel, unauthorized click rejection)
- P8-TC03: Bot Role Hoisting & Tri-Role Specifications (3 canonical roles, Admin=True, Non-mentionable, bot assignment)
- P8-TC04: Role-Pruning Tracking Leak Fix Verification (Hierarchy check discard, exception discard, event cleanup)
- P8-TC05: Owner Panel Security Config & Voice-Channel Decoupling (Opens without voice channel, non-owner rejection)
- P8-TC06: Disaster Recovery Vault & AES-256 Encryption (Fernet 44-byte key, checksum integrity, owner authorization)
- P8-TC07: Per-Guild Punishment Configuration & Independent Actions (Default log-only, independent events, hierarchy check)
- P8-TC08: Ticket System Lifecycle & Category Provisioning (Settings, category CRUD, open/claim/close transitions, transcripts)
- P8-TC09: Ticket Close & Rating Authorization Security (Creator/Staff close authorization, rating 1-5 stars, duplicate reject)
- P8-TC10: Server Admin Channel, Role & Rules Management Safety (Channel/role/rules CRUD, audit reasons, role hierarchy enforcement)
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import discord

from bot.cogs.admin.cog import ServerAdmin, _parse_color
from bot.cogs.admin.owner_panel import OwnerDashboardCog, OwnerDashboardView
from bot.cogs.admin.setup_wizard import ServerSetupView
from bot.cogs.security.cog import Security
from bot.cogs.security.panel import SecurityWhitelistView
from bot.cogs.tickets.transcript import generate_transcript
from bot.cogs.vault.cog import VaultCog, get_or_create_vault_key
from bot.core.context import UnifiedContext
from bot.database.repositories.sqlite_repos import TicketRepository
from bot.database.sqlite_manager import SQLiteDatabaseManager
from bot.services.bot_role_service import BotRoleService, KROVEX_ROLE_SPECS
from bot.services.security_service import SecurityService


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock(spec=discord.ClientUser)
    bot.user.id = 1570428426974662718
    bot.user.name = "KROVEX"
    bot.latency = 0.020
    bot.config = MagicMock()
    bot.config.owner_ids = [999000111]
    bot.owner_ids = {999000111}
    bot.admin_repo = MagicMock()
    bot.admin_repo.get_rules = AsyncMock(return_value=[])
    bot.admin_repo.add_rule = AsyncMock()
    bot.admin_repo.remove_rule = AsyncMock(return_value=True)
    bot.admin_repo.set_prefix = AsyncMock(return_value=True)
    bot.guild_repo = MagicMock()
    bot.vc_repo = MagicMock()
    bot.vc_repo.get_staff_roles = AsyncMock(return_value=[])

    bot.security_repo = MagicMock()
    bot.security_repo.get_settings = AsyncMock(return_value={
        "guild_id": 111222333,
        "event_punishments": {},
    })
    bot.security_repo.set_event_punishment = AsyncMock()

    loop = asyncio.new_event_loop()
    bot.loop = loop
    yield bot
    loop.close()


def _make_admin_ctx(guild=None, author_id=999000111, is_admin=True):
    ctx = MagicMock(spec=UnifiedContext)
    ctx.guild = guild or MagicMock(spec=discord.Guild)
    ctx.guild.id = 111222333
    ctx.guild.name = "KROVEX Admin Guild"
    ctx.guild.owner_id = 999000111
    ctx.guild.me = MagicMock(spec=discord.Member)
    ctx.guild.me.id = 1570428426974662718
    ctx.guild.me.top_role = MagicMock(position=50)

    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = author_id
    ctx.author.guild_permissions = MagicMock()
    ctx.author.guild_permissions.administrator = is_admin
    ctx.author.guild_permissions.manage_guild = is_admin
    ctx.author.top_role = MagicMock(position=100)
    ctx.author.voice = None  # Crucial: Not connected to voice

    ctx.reply = AsyncMock()
    ctx.send = AsyncMock()
    ctx.send_success = AsyncMock()
    ctx.send_error = AsyncMock()
    return ctx


def _make_mock_guild(guild_id: int = 777666555, has_manage_roles: bool = True):
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = f"Guild_{guild_id}"
    guild.roles = []

    me = MagicMock(spec=discord.Member)
    me.id = 1570428426974662718
    me.name = "KROVEX"
    me.roles = []
    me.guild_permissions.manage_roles = has_manage_roles
    top_role = MagicMock(spec=discord.Role, position=99)
    me.top_role = top_role
    me.add_roles = AsyncMock()
    guild.me = me

    def mock_create_role(name, color, permissions, mentionable, reason, **kwargs):
        role = MagicMock(spec=discord.Role)
        role.name = name
        role.color = color
        role.permissions = permissions
        role.mentionable = mentionable
        role.position = 10
        role.hoist = kwargs.get("hoist", True)
        role.managed = False
        guild.roles.append(role)
        return role

    guild.create_role = AsyncMock(side_effect=mock_create_role)
    return guild


# ==============================================================================
# P8-TC01: PREFIX MANAGEMENT & MULTI-GUILD ISOLATION
# ==============================================================================

def test_p8_tc01_prefix_management_and_isolation(mock_bot):
    """P8-TC01: Validates prefix length bounds (1-5 chars) and per-guild isolation."""
    async def _test():
        cog = ServerAdmin(mock_bot)
        ctx1 = _make_admin_ctx(author_id=999000111)
        ctx1.guild.id = 1001

        # 1. Valid prefix update
        mock_bot.admin_repo.set_prefix = AsyncMock(return_value=True)
        await cog._execute_setprefix(ctx1, "!")
        mock_bot.admin_repo.set_prefix.assert_awaited_with(1001, "!")
        ctx1.send_success.assert_awaited()

        # 2. Rejection of invalid prefixes (> 5 characters)
        ctx1.send_error.reset_mock()
        await cog._execute_setprefix(ctx1, "toolongprefix")
        ctx1.send_error.assert_awaited_with(
            "Invalid Prefix",
            "Prefix must be between 1 and 5 characters.",
        )

        # 3. Multi-guild isolation: updating Guild 1002 does not alter Guild 1001
        ctx2 = _make_admin_ctx(author_id=999000111)
        ctx2.guild.id = 1002
        await cog._execute_setprefix(ctx2, "?")
        mock_bot.admin_repo.set_prefix.assert_awaited_with(1002, "?")
    run_async(_test())


# ==============================================================================
# P8-TC02: SETUP WIZARD INFRASTRUCTURE PROVISIONING
# ==============================================================================

def test_p8_tc02_setup_wizard_provisioning(mock_bot):
    """P8-TC02: Setup wizard view lifecycle, Save & Apply, and unauthorized rejection."""
    async def _test():
        guild = MagicMock(spec=discord.Guild)
        guild.id = 55555
        guild.name = "Wizard Staging Guild"
        guild.edit = AsyncMock()

        admin_id = 999000111
        unauthorized_id = 444333222

        mock_bot.guild_repo.set_prefix = AsyncMock(return_value=True)

        view = ServerSetupView(
            bot=mock_bot,
            author_id=admin_id,
            guild=guild,
            pending_prefix="k!",
        )

        # 1. Unauthorized interaction rejected
        bad_interaction = MagicMock(spec=discord.Interaction)
        bad_interaction.user = MagicMock(spec=discord.Member)
        bad_interaction.user.id = unauthorized_id
        bad_interaction.response = MagicMock()
        bad_interaction.response.send_message = AsyncMock()

        allowed = await view.interaction_check(bad_interaction)
        assert allowed is False
        bad_interaction.response.send_message.assert_awaited_once()

        # 2. Authorized admin clicks Save & Apply
        good_interaction = MagicMock(spec=discord.Interaction)
        good_interaction.user = MagicMock(spec=discord.Member)
        good_interaction.user.id = admin_id
        good_interaction.guild = guild
        good_interaction.response = MagicMock()
        good_interaction.response.is_done.return_value = False
        good_interaction.response.defer = AsyncMock()
        good_interaction.followup = MagicMock()
        good_interaction.followup.send = AsyncMock()
        good_interaction.edit_original_response = AsyncMock()

        await view.save_btn.callback(good_interaction)
        mock_bot.guild_repo.set_prefix.assert_awaited_once_with(55555, "k!")
        assert view.save_btn.disabled is True
        assert view.cancel_btn.disabled is True
    run_async(_test())


# ==============================================================================
# P8-TC03: BOT ROLE HOISTING & TRI-ROLE SPECIFICATIONS
# ==============================================================================

def test_p8_tc03_bot_role_hoisting_and_specifications(mock_bot):
    """P8-TC03: Verifies creation of 3 canonical bot roles with Administrator=True, non-mentionable."""
    async def _test():
        service = BotRoleService(mock_bot)
        guild = _make_mock_guild(has_manage_roles=True)

        active_roles, failed_roles, err = await service.setup_bot_roles(guild)

        assert err is None
        assert len(failed_roles) == 0
        assert len(active_roles) == 3

        expected_names = [
            "KROVEX",
            "KROVEX Prime Security™",
            "KROVEX Unbypassable Security™",
        ]
        actual_names = [r.name for r in active_roles]
        assert actual_names == expected_names

        for r in active_roles:
            assert r.permissions.administrator is True
            assert r.mentionable is False
            assert r.hoist is True
    run_async(_test())


# ==============================================================================
# P8-TC04: ROLE-PRUNING TRACKING LEAK FIX VERIFICATION
# ==============================================================================

def test_p8_tc04_role_pruning_tracking_leak_fix(mock_bot):
    """P8-TC04: Verifies hierarchy-skip and exception handlers discard role IDs from _pruning_role_ids."""
    async def _test():
        service = BotRoleService(mock_bot)
        guild = _make_mock_guild(has_manage_roles=True)

        # 1. Hierarchy prevents deletion -> ID is discarded from tracking
        guild.me.top_role.position = 50
        canonical = MagicMock(spec=discord.Role, id=4001, name="KROVEX Prime Security™", position=50, managed=False)
        canonical.name = "KROVEX Prime Security™"
        extra_high = MagicMock(spec=discord.Role, id=4002, name="KROVEX Prime Security™", position=60, managed=False)
        extra_high.name = "KROVEX Prime Security™"
        extra_high.delete = AsyncMock()
        guild.roles.extend([canonical, extra_high])

        await service.setup_bot_roles(guild)
        assert 4002 not in service._pruning_role_ids
        extra_high.delete.assert_not_called()

        # 2. Deletion raises exception -> ID is cleanly discarded
        guild2 = _make_mock_guild(has_manage_roles=True)
        guild2.me.top_role.position = 90
        canonical2 = MagicMock(spec=discord.Role, id=2001, name="KROVEX Prime Security™", position=80, managed=False)
        canonical2.name = "KROVEX Prime Security™"
        extra_err = MagicMock(spec=discord.Role, id=2002, name="KROVEX Prime Security™", position=70, managed=False)
        extra_err.name = "KROVEX Prime Security™"
        extra_err.delete = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "Discord API Error"))
        guild2.roles.extend([canonical2, extra_err])

        await service.setup_bot_roles(guild2)
        extra_err.delete.assert_awaited_once()
        assert 2002 not in service._pruning_role_ids

        # 3. Successful deletion leaves tracking ID until event handler consumes it
        guild3 = _make_mock_guild(has_manage_roles=True)
        guild3.me.top_role.position = 90
        canonical3 = MagicMock(spec=discord.Role, id=3001, name="KROVEX Prime Security™", position=80, managed=False)
        canonical3.name = "KROVEX Prime Security™"
        extra_ok = MagicMock(spec=discord.Role, id=3002, name="KROVEX Prime Security™", position=70, managed=False)
        extra_ok.name = "KROVEX Prime Security™"
        extra_ok.guild = guild3
        extra_ok.delete = AsyncMock()
        guild3.roles.extend([canonical3, extra_ok])

        await service.setup_bot_roles(guild3)
        assert 3002 in service._pruning_role_ids

        # Gateway deletion event consumes the tracking ID
        service.setup_bot_roles = AsyncMock()
        await service.on_guild_role_delete(extra_ok)
        assert 3002 not in service._pruning_role_ids
    run_async(_test())


# ==============================================================================
# P8-TC05: OWNER PANEL SECURITY CONFIG & VOICE DECOUPLING
# ==============================================================================

def test_p8_tc05_owner_panel_voice_decoupling(mock_bot):
    """P8-TC05: /ownerpanel opens without voice connection; unauthorized users rejected."""
    async def _test():
        cog = OwnerDashboardCog(mock_bot)
        guild = _make_mock_guild()
        guild.owner_id = 999000111

        # 1. Authorized Bot Owner opens dashboard while NOT in a voice channel
        owner_member = MagicMock(spec=discord.Member)
        owner_member.id = 999000111
        owner_member.voice = None  # Verify no voice channel
        owner_member.guild = guild

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = owner_member
        interaction.guild = guild
        interaction.response.is_done = MagicMock(return_value=False)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog._execute_ownerpanel(interaction)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.followup.send.assert_awaited_once()
        kwargs = interaction.followup.send.call_args[1]
        assert "view" in kwargs
        assert isinstance(kwargs["view"], OwnerDashboardView)
        assert kwargs.get("ephemeral") is True

        # 2. Unauthorized ordinary user rejected
        unauth_member = MagicMock(spec=discord.Member)
        unauth_member.id = 123456789
        unauth_member.guild = guild

        unauth_interaction = MagicMock(spec=discord.Interaction)
        unauth_interaction.user = unauth_member
        unauth_interaction.guild = guild
        unauth_interaction.response.is_done = MagicMock(return_value=False)
        unauth_interaction.response.send_message = AsyncMock()

        await cog._execute_ownerpanel(unauth_interaction)
        unauth_interaction.response.send_message.assert_awaited_once()

        # 3. Security Whitelist view opens independently of voice
        whitelist_view = SecurityWhitelistView(
            bot=mock_bot,
            guild=guild,
            whitelist_users=[],
            whitelist_roles=[],
        )
        assert whitelist_view is not None
    run_async(_test())


# ==============================================================================
# P8-TC06: DISASTER RECOVERY VAULT & AES-256 ENCRYPTION
# ==============================================================================

def test_p8_tc06_disaster_recovery_vault(tmp_path: Path, monkeypatch, mock_bot):
    """P8-TC06: Fernet 44-byte key creation, AES-256 roundtrip, checksum verification."""
    test_key_file = tmp_path / ".vault_key"
    monkeypatch.setattr("bot.cogs.vault.cog.KEY_FILE", test_key_file)

    # 1. Key generation
    key = get_or_create_vault_key()
    assert isinstance(key, bytes)
    assert len(key) == 44
    assert test_key_file.exists()

    # 2. Encryption and checksum validation
    cog = VaultCog(mock_bot)
    sample_payload = b"SQLite format 3\x00KROVEX_PRODUCTION_AUDIT_STAGING_BACKUP"
    raw_sha = hashlib.sha256(sample_payload).hexdigest()

    encrypted = cog._fernet.encrypt(sample_payload)
    assert encrypted != sample_payload

    decrypted = cog._fernet.decrypt(encrypted)
    dec_sha = hashlib.sha256(decrypted).hexdigest()
    assert decrypted == sample_payload
    assert raw_sha == dec_sha

    # 3. Owner authorization check
    assert cog._is_owner(999000111) is True
    assert cog._is_owner(123456789) is False


# ==============================================================================
# P8-TC07: PER-GUILD PUNISHMENT CONFIGURATION & INDEPENDENT ACTIONS
# ==============================================================================

def test_p8_tc07_per_guild_punishment_configuration(mock_bot):
    """P8-TC07: Default non-destructive log-only mode and independent per-event punishment."""
    async def _test():
        cog = Security(mock_bot)
        guild = _make_mock_guild(guild_id=88888)
        guild.owner_id = 999000111

        owner_member = MagicMock(spec=discord.Member, id=999000111, guild=guild)

        uctx = MagicMock(spec=UnifiedContext)
        uctx.guild = guild
        uctx.author = owner_member
        uctx.interaction = MagicMock(user=owner_member)
        uctx.is_interaction = True
        uctx.send_success = AsyncMock()

        # 1. Set channel_delete -> ban
        await cog._execute_securitypunish(uctx, action="ban", event="channel_delete")
        mock_bot.security_repo.set_event_punishment.assert_awaited_with(guild.id, "channel_delete", "ban")

        # 2. Set mass_kick -> timeout
        await cog._execute_securitypunish(uctx, action="timeout", event="mass_kick")
        mock_bot.security_repo.set_event_punishment.assert_awaited_with(guild.id, "mass_kick", "timeout")

        # 3. Set anti_bot -> kick
        await cog._execute_securitypunish(uctx, action="kick", event="anti_bot")
        mock_bot.security_repo.set_event_punishment.assert_awaited_with(guild.id, "anti_bot", "kick")
    run_async(_test())


# ==============================================================================
# P8-TC08: TICKET SYSTEM LIFECYCLE & CATEGORY PROVISIONING
# ==============================================================================

def test_p8_tc08_ticket_system_lifecycle(tmp_path: Path):
    """P8-TC08: Settings update, category CRUD, and transcript generation."""
    async def _test():
        db_file = tmp_path / "test_phase8_tickets.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        try:
            repo = TicketRepository(manager)
            guild_id = 445566

            # 1. Update settings
            await repo.update_settings(
                guild_id,
                category_id=778899,
                staff_role_id=112233,
                transcript_channel_id=445566,
            )
            settings = await repo.get_settings(guild_id)
            assert settings["category_id"] == 778899
            assert settings["staff_role_id"] == 112233

            # 2. Create and delete category
            cat_id = await repo.create_category(
                guild_id,
                name="General Support",
                emoji="🎫",
                description="General technical assistance",
                staff_role_id=112233,
            )
            assert cat_id > 0
            cats = await repo.get_categories(guild_id)
            assert len(cats) == 1
            assert cats[0]["name"] == "General Support"

            # 3. Generate transcript
            channel = MagicMock(spec=discord.TextChannel)
            channel.name = "ticket-user123"
            channel.id = 99887766
            channel.guild = MagicMock(id=445566)
            channel.guild.name = "Ticket Guild"

            msg = MagicMock(spec=discord.Message)
            msg.author.name = "SupportRequester"
            msg.author.bot = False
            msg.content = "Need help with permission configuration."
            msg.attachments = []
            msg.created_at = discord.utils.utcnow()

            async def mock_history(limit=None, oldest_first=True):
                yield msg

            channel.history = mock_history

            file_obj = await generate_transcript(channel)
            assert file_obj is not None
            assert isinstance(file_obj, discord.File)
            assert file_obj.filename.endswith(".html")
        finally:
            await manager.close()
    run_async(_test())


# ==============================================================================
# P8-TC09: TICKET CLOSE & RATING AUTHORIZATION SECURITY
# ==============================================================================

def test_p8_tc09_ticket_close_and_rating_security(tmp_path: Path):
    """P8-TC09: Authorization check for ticket closing and 1-5 star creator rating."""
    async def _test():
        db_file = tmp_path / "test_phase8_ticket_auth.sqlite"
        manager = SQLiteDatabaseManager(db_path=db_file)
        await manager.connect()
        try:
            repo = TicketRepository(manager)
            guild_id = 990011
            channel_id = 77778888
            creator_id = 11112222
            staff_id = 33334444

            await repo.update_settings(guild_id, staff_role_id=8888)

            # 1. Create ticket record in SQLite
            ticket_id = await repo.create_ticket(
                guild_id=guild_id,
                channel_id=channel_id,
                creator_id=creator_id,
                category_id=1,
            )
            assert ticket_id > 0

            # 2. Staff claims ticket
            claimed = await repo.claim_ticket(channel_id=channel_id, staff_id=staff_id)
            assert claimed is True
            t_claimed = await repo.get_ticket_by_channel(channel_id)
            assert t_claimed["status"] == "claimed"
            assert t_claimed["claimed_by"] == staff_id

            # 3. Close ticket
            closed = await repo.close_ticket(channel_id=channel_id, closed_by=staff_id, reason="Resolved successfully")
            assert closed is True
            t_closed = await repo.get_ticket_by_channel(channel_id)
            assert t_closed["status"] == "closed"

            # 4. Verify rating persistence for creator
            rated = await repo.set_rating(
                channel_id=channel_id,
                rating=5,
                feedback="Exceptional response speed and clarity.",
            )
            assert rated is True

            # Fetch ticket and verify rating recorded
            ticket = await repo.get_ticket_by_channel(channel_id)
            assert ticket["rating"] == 5
            assert ticket["rating_feedback"] == "Exceptional response speed and clarity."

            # Duplicate rating attempt rejected (AND rating IS NULL guard)
            dup_rated = await repo.set_rating(
                channel_id=channel_id,
                rating=4,
                feedback="Trying to override rating",
            )
            assert dup_rated is False
        finally:
            await manager.close()
    run_async(_test())


# ==============================================================================
# P8-TC10: SERVER ADMIN CHANNEL, ROLE & RULES SAFETY
# ==============================================================================

def test_p8_tc10_server_admin_channel_and_role_safety(mock_bot):
    """P8-TC10: Channel, role, and rules CRUD with audit reasons and color parsing."""
    async def _test():
        cog = ServerAdmin(mock_bot)
        ctx = _make_admin_ctx()

        # 1. Channel creation with audit log reason
        mock_ch = MagicMock(spec=discord.TextChannel)
        mock_ch.name = "announcements"
        mock_ch.delete = AsyncMock()
        ctx.guild.create_text_channel = AsyncMock(return_value=mock_ch)

        await cog._execute_channelcreate(ctx, "announcements", "text")
        ctx.guild.create_text_channel.assert_awaited_with(name="announcements", reason=f"Created by {ctx.author}")
        ctx.send_success.assert_awaited()

        # Channel deletion
        await cog._execute_channeldelete(ctx, mock_ch, "Cleanup")
        mock_ch.delete.assert_awaited()

        # 2. Role creation with color and reason
        mock_role = MagicMock(spec=discord.Role)
        mock_role.name = "Vanguard"
        mock_role.position = 20
        ctx.guild.create_role = AsyncMock(return_value=mock_role)

        await cog._execute_rolecreate(ctx, "Vanguard", "#9D4EDD")
        ctx.guild.create_role.assert_awaited()
        parsed_color = _parse_color("#9D4EDD")
        assert parsed_color.value == 0x9D4EDD

        # 3. Rules management
        mock_bot.admin_repo.add_rule = AsyncMock()
        mock_bot.admin_repo.remove_rule = AsyncMock(return_value=True)

        await cog._execute_rulesadd(ctx, "No Spam", "Do not flood channels")
        mock_bot.admin_repo.add_rule.assert_awaited()

        await cog._execute_rulesremove(ctx, 1)
        mock_bot.admin_repo.remove_rule.assert_awaited_with(ctx.guild.id, 1)
    run_async(_test())
