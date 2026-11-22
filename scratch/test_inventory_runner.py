import os
import sys
import subprocess
import json
import time

def main():
    test_dir = "tests"
    files = sorted([f for f in os.listdir(test_dir) if f.startswith("test_") and f.endswith(".py")])
    
    results = {}
    print(f"Discovered {len(files)} test files in {test_dir}/")
    
    for f in files:
        filepath = os.path.join(test_dir, f)
        t0 = time.time()
        res = subprocess.run(
            [sys.executable, "-m", "pytest", filepath, "-q", "-W", "default"],
            capture_output=True,
            text=True
        )
        elapsed = round(time.time() - t0, 2)
        stdout = res.stdout
        stderr = res.stderr
        returncode = res.returncode
        
        # Parse output line, usually e.g. "17 passed, 1 warning in 1.23s" or failures
        summary_line = ""
        for line in stdout.splitlines()[::-1]:
            if "passed" in line or "failed" in line or "error" in line:
                summary_line = line.strip()
                break
        if not summary_line and stdout:
            summary_line = stdout.splitlines()[-1].strip()
            
        results[f] = {
            "file": f,
            "returncode": returncode,
            "status": "PASSED" if returncode == 0 else "FAILED",
            "summary": summary_line,
            "elapsed": elapsed,
            "stdout_preview": stdout[-500:] if stdout else "",
            "stderr_preview": stderr[-500:] if stderr else ""
        }
        print(f"[{'PASS' if returncode == 0 else 'FAIL'}] {f} ({elapsed}s) -> {summary_line}")
        
    with open("scratch/test_inventory_raw.json", "w", encoding="utf-8") as out:
        json.dump(results, out, indent=2)

if __name__ == "__main__":
    main()
