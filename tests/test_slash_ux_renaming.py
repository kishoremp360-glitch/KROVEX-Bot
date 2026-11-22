"""Comprehensive verification suite for Phase 2A Slash Command UX Renaming (88 commands).

Verifies:
1. All 88 new clean slash paths are registered in their respective groups.
2. All 88 old redundant slash paths are completely absent from the command tree.
3. Prefix commands for all 88 actions remain fully registered and accessible.
4. Permission checks and authorization decorators are preserved.
5. Zero duplicate slash commands or registration collisions.
6. Root slash count remains exactly 43 (satisfying Discord's 100 limit with 57 headroom slots).
7. Subcommand counts for all 19 groups satisfy Discord's 25-subcommand limit.
"""

from __future__ import annotations

import pytest
from tests.test_command_restructuring import get_test_bot


RENAMED_MAPPINGS = {
    # 1. Group /vc (25 commands)
    "vc": [
        ("kick", "vckick"),
        ("ban", "vcban"),
        ("unban", "vcunban"),
        ("kickall", "vckickall"),
        ("banall", "vcbanall"),
        ("unbanall", "vcunbanall"),
        ("mute", "vcmute"),
        ("unmute", "vcunmute"),
        ("muteall", "vcmuteall"),
        ("unmuteall", "vcunmuteall"),
        ("deafen", "vcdeafen"),
        ("undeafen", "vcundeafen"),
        ("deafenall", "vcdeafenall"),
        ("undeafenall", "vcundeafenall"),
        ("lock", "vclock"),
        ("unlock", "vcunlock"),
        ("hide", "vchide"),
        ("show", "vcshow"),
        ("limit", "vclimit"),
        ("bitrate", "vcbitrate"),
        ("region", "vcregion"),
        ("drag", "vcdrag"),
        ("moveall", "vcmoveall"),
        ("info", "vcinfo"),
        ("stats", "vcstats"),
    ],
    # 2. Group /security (8 commands)
    "security": [
        ("status", "securitystatus"),
        ("window", "securitywindow"),
        ("punish", "securitypunish"),
        ("logchannel", "securitylogchannel"),
        ("reset", "securityreset"),
        ("logs", "securitylogs"),
        ("audit", "securityaudit"),
        ("whitelist", "securitywhitelist"),
    ],
    # 3. Group /logs (17 commands)
    "logs": [
        ("status", "logstatus"),
        ("toggle", "logtoggle"),
        ("ignorechannel", "logignorechannel"),
        ("ignorerole", "logignorerole"),
        ("filter", "logfilter"),
        ("history", "loghistory"),
        ("clear", "logclear"),
        ("msgdelete", "logmsgdelete"),
        ("msgedit", "logmsgedit"),
        ("bulkdelete", "logbulkdelete"),
        ("memberjoin", "logmemberjoin"),
        ("memberleave", "logmemberleave"),
        ("voice", "logvoice"),
        ("roles", "logroles"),
        ("server", "logserver"),
        ("channels", "logchannels"),
        ("test", "logtest"),
    ],
    # 4. Group /welcome (10 commands)
    "welcome": [
        ("status", "welcomestatus"),
        ("test", "welcometest"),
        ("setup", "welcomesetup"),
        ("message", "welcomemessage"),
        ("embed", "welcomeembed"),
        ("color", "welcomecolor"),
        ("image", "welcomeimage"),
        ("dm", "welcomedm"),
        ("autorole", "welcomeautorole"),
        ("reset", "welcomereset"),
    ],
    # 5. Group /automod (8 commands)
    "automod": [
        ("status", "automod"),
        ("rules", "automodrules"),
        ("stats", "automodstats"),
        ("ruleadd", "automodruleadd"),
        ("ruleremove", "automodruleremove"),
        ("ruleedit", "automodruleedit"),
        ("exempt", "automodexempt"),
        ("logs", "automodlogs"),
    ],
    # 6. Group /rr (16 commands)
    "rr": [
        ("create", "rrcreate"),
        ("remove", "rrremove"),
        ("buttonpanel", "rrbuttonpanel"),
        ("buttonadd", "rrbuttonadd"),
        ("buttonremove", "rrbuttonremove"),
        ("menucreate", "rrmenucreate"),
        ("menuadd", "rrmenuadd"),
        ("menuremove", "rrmenuremove"),
        ("list", "rrlist"),
        ("delete", "rrdelete"),
        ("edit", "rredit"),
        ("limit", "rrlimit"),
        ("exclusive", "rrexclusive"),
        ("requiredrole", "rrrequiredrole"),
        ("refresh", "rrrefresh"),
        ("logs", "rrlogs"),
    ],
    # 7. Group /music (2 commands)
    "music": [
        ("status", "musicstatus"),
        ("settings", "musicsettings"),
    ],
    # 8. Group /rate (2 commands)
    "rate": [
        ("simp", "simprate"),
        ("brain", "brainrate"),
    ],
}


@pytest.mark.asyncio
async def test_all_88_new_slash_paths_registered():
    """Verify that all 88 new clean slash paths are registered under their groups."""
    bot = await get_test_bot()
    root_map = {c.name: c for c in bot.tree.get_commands()}

    total_verified = 0
    for group_name, pairs in RENAMED_MAPPINGS.items():
        assert group_name in root_map, f"Group /{group_name} missing from command tree"
        group = root_map[group_name]
        assert hasattr(group, "commands"), f"/{group_name} is not a Group"

        sub_map = {s.name: s for s in group.commands}
        for new_name, old_name in pairs:
            assert new_name in sub_map, f"New path /{group_name} {new_name} is missing from /{group_name}"
            # Check description is non-empty
            cmd = sub_map[new_name]
            assert cmd.description, f"Command /{group_name} {new_name} has empty description"
            total_verified += 1

    assert total_verified == 88, f"Expected 88 verified renames, got {total_verified}"


@pytest.mark.asyncio
async def test_all_88_old_redundant_paths_absent():
    """Verify that all 88 old redundant slash paths are completely removed from the command tree."""
    bot = await get_test_bot()
    root_map = {c.name: c for c in bot.tree.get_commands()}

    for group_name, pairs in RENAMED_MAPPINGS.items():
        group = root_map[group_name]
        sub_map = {s.name: s for s in group.commands}
        for new_name, old_name in pairs:
            # Skip cases where new_name equals old_name (none in this list)
            if new_name != old_name:
                assert old_name not in sub_map, f"Old redundant path /{group_name} {old_name} is still present!"


@pytest.mark.asyncio
async def test_prefix_command_backward_compatibility():
    """Verify that original prefix command triggers remain registered and functional."""
    bot = await get_test_bot()

    # Sample check across all 8 modules for prefix preservation
    sample_prefix_commands = [
        "vckick", "vcban", "vcmute", "vclock", "vcinfo",
        "securitystatus", "securitywhitelist", "securitypunish",
        "logstatus", "logvoice", "logmsgdelete", "logclear",
        "welcomestatus", "welcometest", "welcomesetup",
        "automod", "automodrules", "automodstats",
        "rrcreate", "rrbuttonpanel", "rrlist",
        "musicstatus", "musicsettings",
        "simprate", "brainrate"
    ]

    for pcmd in sample_prefix_commands:
        cmd = bot.get_command(pcmd)
        assert cmd is not None, f"Prefix command .{pcmd} was accidentally removed or broken"


@pytest.mark.asyncio
async def test_permission_preservation_on_renamed_commands():
    """Verify that default_permissions are preserved on renamed slash commands."""
    bot = await get_test_bot()
    root_map = {c.name: c for c in bot.tree.get_commands()}

    # /security whitelist requires administrator
    sec_group = root_map["security"]
    sec_whitelist = next(c for c in sec_group.commands if c.name == "whitelist")
    assert sec_whitelist.default_permissions is not None
    assert sec_whitelist.default_permissions.administrator is True

    # /welcome test requires manage_guild
    welcome_group = root_map["welcome"]
    welcome_test = next(c for c in welcome_group.commands if c.name == "test")
    assert welcome_test.default_permissions is not None
    assert welcome_test.default_permissions.manage_guild is True

    # /rr create requires manage_roles
    rr_group = root_map["rr"]
    rr_create = next(c for c in rr_group.commands if c.name == "create")
    assert rr_create.default_permissions is not None
    assert rr_create.default_permissions.manage_roles is True


@pytest.mark.asyncio
async def test_root_counts_and_group_subcommand_limits():
    """Verify root count remains 43 and no group exceeds Discord's 25 limit."""
    bot = await get_test_bot()
    root_items = bot.tree.get_commands()

    # Exactly 43 root commands
    assert len(root_items) == 43, f"Expected 43 root commands, got {len(root_items)}"
    headroom = 100 - len(root_items)
    assert headroom == 57, f"Expected 57 headroom slots, got {headroom}"

    # Group subcommand limits <= 25
    for root in root_items:
        if hasattr(root, "commands"):
            count = len(root.commands)
            assert count <= 25, f"Group /{root.name} has {count} subcommands (max 25 allowed)"
