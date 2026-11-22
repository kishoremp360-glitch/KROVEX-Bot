import os
import re

test_dir = "tests"
files = [f for f in os.listdir(test_dir) if f.startswith("test_") and f.endswith(".py")]

targets = [
    "vckick", "vcban", "securitywhitelist", "securitystatus", "logvoice",
    "logstatus", "welcometest", "automodrules", "rrcreate", "musicstatus", "simprate"
]

found_in = {}
for f in files:
    with open(os.path.join(test_dir, f), "r", encoding="utf-8", errors="ignore") as fp:
        content = fp.read()
    for t in targets:
        # Check if looking for slash command or prefix command
        # e.g., app_cmd.name == "vckick" or get_command("vckick")
        matches = re.findall(rf'["\']{t}["\']', content)
        if matches:
            found_in.setdefault(f, []).append((t, len(matches)))

for f, matches in sorted(found_in.items()):
    print(f"File {f}: {matches}")
