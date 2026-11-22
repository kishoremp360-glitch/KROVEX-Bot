import json
from pathlib import Path

p = Path(r"F:\Death Bot\scratch\vault_server_inspection.json")
data = json.loads(p.read_text(encoding="utf-8"))

print(f"Server Name: {data['server']['name']}")
print(f"Server ID: {data['server']['id']}")
print(f"Owner ID: {data['server']['owner_id']}")
print(f"Member Count: {data['server']['member_count']}")
print("\n--- CATEGORIES & CHANNELS ---")
for cat in data['categories']:
    print(f"\n📂 [{cat['name']}] (ID: {cat['id']}, Pos: {cat['position']})")
    for ch in cat['channels']:
        print(f"   {ch['type']}: {ch['name']} (ID: {ch['id']})")
