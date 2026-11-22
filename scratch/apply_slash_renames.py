import re

def replace_in_file(fpath, replacements):
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content
    count = 0
    for old_pattern, new_text in replacements:
        if callable(new_text):
            content, n = re.subn(old_pattern, new_text, content)
        else:
            content, n = re.subn(old_pattern, new_text, content)
        count += n
        if n == 0:
            print(f"WARNING: pattern '{old_pattern}' not found in {fpath}!")

    if content != original:
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated {fpath}: {count} replacements made.")
    else:
        print(f"No changes in {fpath}.")

def main():
    # 1. ownervc/cog.py
    vc_cmds = [
        "kick", "ban", "unban", "kickall", "banall", "unbanall", "mute", "unmute",
        "muteall", "unmuteall", "deafen", "undeafen", "deafenall", "undeafenall",
        "lock", "unlock", "hide", "show", "limit", "bitrate", "region", "drag",
        "moveall", "info", "stats"
    ]
    vc_replacements = [
        (rf'@app_commands\.command\(name=["\']vc{cmd}["\']', f'@app_commands.command(name="{cmd}"')
        for cmd in vc_cmds
    ]
    replace_in_file("bot/cogs/ownervc/cog.py", vc_replacements)

    # 2. security/cog.py
    sec_cmds = {
        "securitystatus": "status",
        "securitywindow": "window",
        "securitypunish": "punish",
        "securitylogchannel": "logchannel",
        "securityreset": "reset",
        "securitylogs": "logs",
        "securityaudit": "audit",
        "securitywhitelist": "whitelist"
    }
    sec_replacements = [
        (rf'@app_commands\.command\(name=["\']{old}["\']', f'@app_commands.command(name="{new}"')
        for old, new in sec_cmds.items()
    ]
    replace_in_file("bot/cogs/security/cog.py", sec_replacements)

    # 3. logging/cog.py
    log_cmds = {
        "logstatus": "status",
        "logtoggle": "toggle",
        "logignorechannel": "ignorechannel",
        "logignorerole": "ignorerole",
        "logfilter": "filter",
        "loghistory": "history",
        "logclear": "clear",
        "logmsgdelete": "msgdelete",
        "logmsgedit": "msgedit",
        "logbulkdelete": "bulkdelete",
        "logmemberjoin": "memberjoin",
        "logmemberleave": "memberleave",
        "logvoice": "voice",
        "logroles": "roles",
        "logserver": "server",
        "logchannels": "channels",
        "logtest": "test"
    }
    log_replacements = [
        (rf'@app_commands\.command\(name=["\']{old}["\']', f'@app_commands.command(name="{new}"')
        for old, new in log_cmds.items()
    ]
    replace_in_file("bot/cogs/logging/cog.py", log_replacements)

    # 4. welcome/cog.py
    welcome_cmds = {
        "welcomestatus": "status",
        "welcometest": "test",
        "welcomesetup": "setup",
        "welcomemessage": "message",
        "welcomeembed": "embed",
        "welcomecolor": "color",
        "welcomeimage": "image",
        "welcomedm": "dm",
        "welcomeautorole": "autorole",
        "welcomereset": "reset"
    }
    welcome_replacements = [
        (rf'@app_commands\.command\(name=["\']{old}["\']', f'@app_commands.command(name="{new}"')
        for old, new in welcome_cmds.items()
    ]
    replace_in_file("bot/cogs/welcome/cog.py", welcome_replacements)

    # 5. automod/cog.py
    automod_cmds = {
        "automod": "status",
        "automodrules": "rules",
        "automodstats": "stats",
        "automodruleadd": "ruleadd",
        "automodruleremove": "ruleremove",
        "automodruleedit": "ruleedit",
        "automodexempt": "exempt",
        "automodlogs": "logs"
    }
    automod_replacements = [
        (rf'@app_commands\.command\(name=["\']{old}["\']', f'@app_commands.command(name="{new}"')
        for old, new in automod_cmds.items()
    ]
    replace_in_file("bot/cogs/automod/cog.py", automod_replacements)

    # 6. reactionroles/cog.py
    rr_cmds = {
        "rrcreate": "create",
        "rrremove": "remove",
        "rrbuttonpanel": "buttonpanel",
        "rrbuttonadd": "buttonadd",
        "rrbuttonremove": "buttonremove",
        "rrmenucreate": "menucreate",
        "rrmenuadd": "menuadd",
        "rrmenuremove": "menuremove",
        "rrlist": "list",
        "rrdelete": "delete",
        "rredit": "edit",
        "rrlimit": "limit",
        "rrexclusive": "exclusive",
        "rrrequiredrole": "requiredrole",
        "rrrefresh": "refresh",
        "rrlogs": "logs"
    }
    rr_replacements = [
        (rf'@app_commands\.command\(name=["\']{old}["\']', f'@app_commands.command(name="{new}"')
        for old, new in rr_cmds.items()
    ]
    replace_in_file("bot/cogs/reactionroles/cog.py", rr_replacements)

    # 7. music/cog.py
    music_replacements = [
        (r'@music\.command\(name=["\']musicstatus["\']', '@music.command(name="status"'),
        (r'@music\.command\(name=["\']musicsettings["\']', '@music.command(name="settings"')
    ]
    replace_in_file("bot/cogs/music/cog.py", music_replacements)

    # 8. fun/ratings.py
    # Update meter_actions and action_to_metric
    ratings_path = "bot/cogs/fun/ratings.py"
    with open(ratings_path, "r", encoding="utf-8") as f:
        rcontent = f.read()
    
    rcontent = rcontent.replace('("simprate", "Calculate simp percentage")', '("simp", "Calculate simp percentage")')
    rcontent = rcontent.replace('("brainrate", "Calculate brain cell activity score")', '("brain", "Calculate brain cell activity score")')
    
    old_dict = '''    action_to_metric = {
        "rainbow": "gay",
        "harmony": "lesbian",
        "mischief": "horny",
        "flirt": "tharki",
        "goofy": "chutiya",
    }'''
    new_dict = '''    action_to_metric = {
        "rainbow": "gay",
        "harmony": "lesbian",
        "mischief": "horny",
        "flirt": "tharki",
        "goofy": "chutiya",
        "simp": "simprate",
        "brain": "brainrate",
    }'''
    rcontent = rcontent.replace(old_dict, new_dict)
    with open(ratings_path, "w", encoding="utf-8") as f:
        f.write(rcontent)
    print(f"Updated {ratings_path}: simp and brain mappings applied.")

if __name__ == "__main__":
    main()
