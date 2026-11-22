import re

files_targets = [
    ("bot/cogs/ownervc/cog.py", [
        "vckick", "vcban", "vcunban", "vckickall", "vcbanall", "vcunbanall",
        "vcmute", "vcunmute", "vcmuteall", "vcunmuteall", "vcdeafen", "vcundeafen",
        "vcdeafenall", "vcundeafenall", "vclock", "vcunlock", "vchide", "vcshow",
        "vclimit", "vcbitrate", "vcregion", "vcdrag", "vcmoveall", "vcinfo", "vcstats"
    ]),
    ("bot/cogs/security/cog.py", [
        "securitystatus", "securitylogchannel", "securitylogs", "securitywhitelist",
        "securitypunish", "securityreset", "securitywindow", "securityaudit"
    ]),
    ("bot/cogs/logging/cog.py", [
        "logstatus", "logtest", "logclear", "logtoggle", "logfilter", "loghistory",
        "logchannels", "logroles", "logvoice", "logserver", "logmsgdelete", "logmsgedit",
        "logbulkdelete", "logmemberjoin", "logmemberleave", "logignorechannel", "logignorerole"
    ]),
    ("bot/cogs/welcome/cog.py", [
        "welcomestatus", "welcometest", "welcomesetup", "welcomemessage", "welcomeembed",
        "welcomecolor", "welcomeimage", "welcomedm", "welcomeautorole", "welcomereset"
    ]),
    ("bot/cogs/automod/cog.py", [
        "automod", "automodrules", "automodstats", "automodlogs", "automodexempt",
        "automodruleadd", "automodruleedit", "automodruleremove"
    ]),
    ("bot/cogs/reactionroles/cog.py", [
        "rrcreate", "rrdelete", "rredit", "rrlist", "rrbuttonpanel", "rrbuttonadd",
        "rrbuttonremove", "rrmenucreate", "rrmenuadd", "rrmenuremove", "rrexclusive",
        "rrlimit", "rrlogs", "rrrefresh", "rrremove", "rrrequiredrole"
    ]),
    ("bot/cogs/music/cog.py", [
        "musicstatus", "musicsettings"
    ]),
    ("bot/cogs/fun/ratings.py", [
        "simprate", "brainrate"
    ])
]

total = 0
for fpath, targets in files_targets:
    total += len(targets)
    with open(fpath, "r", encoding="utf-8") as fp:
        content = fp.read()
    found = []
    missing = []
    for t in targets:
        # Check if @app_commands.command(name="t" or .command(name="t" is present
        pattern = rf'name=["\']{t}["\']'
        if re.search(pattern, content):
            found.append(t)
        else:
            missing.append(t)
    print(f"File: {fpath} -> Targets: {len(targets)}, Found: {len(found)}, Missing: {len(missing)}")
    if missing:
        print(f"  MISSING: {missing}")

print(f"\nTotal targets: {total}")
