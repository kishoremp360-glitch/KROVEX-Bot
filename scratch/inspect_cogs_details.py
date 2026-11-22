def inspect_file(fpath, targets):
    print(f"\n=== {fpath} ===")
    with open(fpath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        for t in targets:
            if f'name="{t}"' in line or f"name='{t}'" in line:
                print(f"Line {i+1}: {line.strip()}")

inspect_file("bot/cogs/security/cog.py", [
    "securitystatus", "securitylogchannel", "securitylogs", "securitywhitelist",
    "securitypunish", "securityreset", "securitywindow", "securityaudit"
])
inspect_file("bot/cogs/logging/cog.py", [
    "logstatus", "logtest", "logclear", "logtoggle", "logfilter", "loghistory",
    "logchannels", "logroles", "logvoice", "logserver", "logmsgdelete", "logmsgedit",
    "logbulkdelete", "logmemberjoin", "logmemberleave", "logignorechannel", "logignorerole"
])
inspect_file("bot/cogs/welcome/cog.py", [
    "welcomestatus", "welcometest", "welcomesetup", "welcomemessage", "welcomeembed",
    "welcomecolor", "welcomeimage", "welcomedm", "welcomeautorole", "welcomereset"
])
inspect_file("bot/cogs/automod/cog.py", [
    "automod", "automodrules", "automodstats", "automodlogs", "automodexempt",
    "automodruleadd", "automodruleedit", "automodruleremove"
])
inspect_file("bot/cogs/reactionroles/cog.py", [
    "rrcreate", "rrdelete", "rredit", "rrlist", "rrbuttonpanel", "rrbuttonadd",
    "rrbuttonremove", "rrmenucreate", "rrmenuadd", "rrmenuremove", "rrexclusive",
    "rrlimit", "rrlogs", "rrrefresh", "rrremove", "rrrequiredrole"
])
inspect_file("bot/cogs/music/cog.py", [
    "musicstatus", "musicsettings"
])
inspect_file("bot/cogs/fun/ratings.py", [
    "simprate", "brainrate"
])
