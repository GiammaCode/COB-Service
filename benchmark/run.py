import subprocess
import sys
import time
import json
import os
from datetime import datetime

# List of tests to run
TESTS = [
    {"script": "test_load_balancing.py"},
    {"script": "test_fault_tolerance.py"},
    {"script": "test_persistence.py"},
    {"script": "test_rolling_update.py"}
]

OUTPUT_FILE = "benchmark_results.json"


def run_test(script_name):
    """Run a test script and capture its JSON output from stdout"""
    try:
        # Run the script, capturing stdout (JSON) and letting stderr (logs) flow to console
        process = subprocess.run(
            [sys.executable, script_name],
            capture_output=True,
            text=True,
            timeout=300
        )

        # Print logs to stderr so user sees progress
        print(process.stderr, file=sys.stderr)

        if process.returncode != 0:
            return {"test_name": script_name, "status": "error", "error": "Script crashed"}

        # Parse the last line of stdout as JSON
        output_lines = process.stdout.strip().split('\n')
        if not output_lines:
            return {"test_name": script_name, "status": "error", "error": "No output received"}

        try:
            # We assume the script prints ONLY valid JSON at the very end
            return json.loads(output_lines[-1])
        except json.JSONDecodeError:
            return {
                "test_name": script_name,
                "status": "error",
                "error": "Invalid JSON output",
                "raw_output": output_lines[-1]
            }

    except subprocess.TimeoutExpired:
        return {"test_name": script_name, "status": "timeout", "error": "Test timed out"}
    except Exception as e:
        return {"test_name": script_name, "status": "error", "error": str(e)}


def main():
    print(f"Starting Benchmark Suite...", file=sys.stderr)

    suite_start = datetime.utcnow().isoformat()
    collected_results = []

    for test in TESTS:
        print(f"Running {test['script']}...", file=sys.stderr)
        result = run_test(test['script'])
        collected_results.append(result)

        # Simple visual feedback on stderr
        status = result.get("status", "unknown")
        print(f"Finished {test['script']}: {status.upper()}\n", file=sys.stderr)

        time.sleep(2)

    # Construct final report
    final_report = {
        "suite_name": "COB-Service Swarm Benchmark",
        "start_time": suite_start,
        "end_time": datetime.utcnow().isoformat(),
        "total_tests": len(TESTS),
        "results": collected_results
    }

    # Save to JSON file
    with open(OUTPUT_FILE, "w") as f:
        json.dump(final_report, f, indent=2)

    print(f"Benchmark complete.", file=sys.stderr)
    print(f"Results saved to: {os.path.abspath(OUTPUT_FILE)}", file=sys.stderr)


if __name__ == "__main__":
    main()