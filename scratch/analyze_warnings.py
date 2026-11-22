import subprocess
import sys
import re
from collections import defaultdict

def analyze_warnings():
    # Run pytest capturing warning summary
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--disable-warnings", "-W", "error"],
        capture_output=True,
        text=True
    )
    # Now run pytest with warning summary to collect all warnings
    res2 = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        capture_output=True,
        text=True
    )
    
    warning_counts = defaultdict(int)
    warning_files = defaultdict(set)
    warning_examples = {}

    lines = res2.stdout.splitlines()
    in_warnings = False
    current_loc = ""
    current_count = 1
    
    for line in lines:
        if "=== warnings summary ===" in line:
            in_warnings = True
            continue
        if in_warnings and ("=== short test summary info ===" in line or "=== 1 failed" in line):
            break
        if in_warnings:
            # Check for location line like "tests/test_foo.py: 12 warnings" or "C:\path\to\file.py:123: 381 warnings"
            m = re.match(r'^(.*?):(?: (\d+) warnings|(\d+): (?:(\d+) warnings)?)', line.strip())
            if m:
                current_loc = m.group(1)
            # Check for warning text
            m_warn = re.search(r'([A-Za-z0-9_]+Warning): (.*)', line)
            if m_warn:
                wtype = m_warn.group(1)
                wmsg = m_warn.group(2).strip()
                key = f"{wtype}: {wmsg}"
                warning_counts[key] += 1
                if current_loc:
                    warning_files[key].add(current_loc)
                if key not in warning_examples:
                    warning_examples[key] = line.strip()

    print(f"Total Unique Warning Categories: {len(warning_counts)}")
    for key, count in sorted(warning_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"\n--- {key} ---")
        print(f"Occurrences recorded in summary: {count}")
        print(f"Sample line: {warning_examples[key]}")
        files = list(warning_files[key])[:5]
        print(f"Affected files ({len(warning_files[key])}): {', '.join(files)}")

if __name__ == "__main__":
    analyze_warnings()
