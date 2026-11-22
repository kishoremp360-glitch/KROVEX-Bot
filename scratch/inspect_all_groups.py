import json

with open("scratch/slash_inventory.json", "r", encoding="utf-8") as f:
    inv = json.load(f)

by_root = {}
for item in inv:
    root = item["root"]
    by_root.setdefault(root, []).append(item)

for root, items in sorted(by_root.items()):
    print(f"\n==================== {root} ({len(items)} commands) ====================")
    for it in items:
        sub = it['subcommand'] or ''
        subgrp = f"[{it['sub_group']}] " if it['sub_group'] else ""
        print(f"  {subgrp}{sub:<24} | perms: {it['permissions']:<10} | desc: {it['description'][:45]}")
