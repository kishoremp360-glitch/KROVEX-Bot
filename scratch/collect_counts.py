import subprocess
import sys
import json
from collections import defaultdict

def collect_pytest_counts():
    res = subprocess.run([sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"], capture_output=True, text=True)
    counts = defaultdict(int)
    for line in res.stdout.splitlines():
        if "::" in line:
            f = line.split("::")[0].replace("\\", "/").replace("tests/", "")
            counts[f] += 1
            
    total = sum(counts.values())
    print(f"Total pytest test items collected in tests/: {total} across {len(counts)} files")
    
    with open("scratch/pytest_counts.json", "w", encoding="utf-8") as out:
        json.dump(counts, out, indent=2)

if __name__ == "__main__":
    collect_pytest_counts()
