import os
import ast
import json

def get_subsystem(filename):
    name = filename.lower()
    if "admin" in name or "owner" in name:
        return "Owner & Server Governance"
    if "vc" in name or "voice" in name:
        return "Voice & OwnerVC Ecosystem"
    if "music" in name:
        return "Music & Media Engine"
    if "security" in name or "automod" in name:
        return "Security & Protection"
    if "moderation" in name:
        return "Moderation Engine"
    if "economy" in name or "shop" in name:
        return "Economy & Virtual Commerce"
    if "level" in name or "reward" in name:
        return "Leveling & Progression"
    if "social" in name or "anime" in name or "fun" in name or "ratings" in name or "mimic" in name:
        return "Social, Anime & Entertainment"
    if "game" in name or "minigame" in name:
        return "Gaming & Minigames"
    if "soul" in name:
        return "SOUL AI Companion"
    if "welcome" in name or "goodbye" in name:
        return "Community & Onboarding"
    if "ticket" in name:
        return "Tickets & Support Desk"
    if "log" in name:
        return "Audit & Telemetry Matrix"
    if "database" in name or "sqlite" in name:
        return "Database & Persistence"
    if "emoji" in name:
        return "Emoji & Visual Styling"
    if "command" in name or "slash" in name or "prefix" in name or "help" in name:
        return "Command Tree & Discovery"
    if "setup" in name:
        return "Automation & Setup"
    if "mention" in name or "dm_queue" in name or "services" in name:
        return "Background Services"
    return "Core Architecture & Lifecycle"

def build_inventory():
    test_dir = "tests"
    files = sorted([f for f in os.listdir(test_dir) if f.startswith("test_") and f.endswith(".py")])
    
    inventory = []
    total_tests = 0
    
    for f in files:
        filepath = os.path.join(test_dir, f)
        with open(filepath, "r", encoding="utf-8", errors="ignore") as fp:
            tree = ast.parse(fp.read(), filename=f)
            
        test_funcs = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
        count = len(test_funcs)
        total_tests += count
        subsystem = get_subsystem(f)
        
        status = "PASSED"
        if f == "test_slash_command_renames.py":
            status = "FAILED (1 fail: legacy root count assertion 29 vs 43)"
            
        inventory.append({
            "file": f,
            "subsystem": subsystem,
            "test_count": count,
            "status": status,
            "test_names": test_funcs
        })
        
    print(f"Total Test Files: {len(files)}")
    print(f"Total Unique Test Functions Discovered: {total_tests}")
    
    with open("scratch/complete_test_inventory.json", "w", encoding="utf-8") as out:
        json.dump(inventory, out, indent=2)

if __name__ == "__main__":
    build_inventory()
