import subprocess
import sys
import time
import json
import os
import argparse
from datetime import datetime

# Test definitions organized by taxonomy category
TESTS = {
    "scheduler_architecture": [
        {"script": "test_scheduling_overhead.py", "description": "Measures scheduler decision time"},
        {"script": "test_concurrent_deployments.py", "description": "Tests scheduler under concurrent load"},
    ],
    "fault_tolerance": [
        {"script": "test_fault_tolerance.py", "description": "Container failure recovery"},
        #{"script": "test_leader_election.py", "description": "Control plane failover"},
    ],
    "scalability": [
        {"script": "test_scalability.py", "description": "Horizontal scaling efficiency"},
        {"script": "test_load_balancing.py", "description": "Load distribution fairness"},
        {"script": "test_rolling_update.py", "description": "Zero-downtime deployments"},
    ],
    #"resource_management": [
        #{"script": "test_resource_contention.py", "description": "Resource limits behavior"},
    #],
    "network": [
        {"script": "test_network_latency.py", "description": "Overlay network performance"},
        {"script": "test_service_discovery.py", "description": "DNS and service discovery"},
    ],
    "data": [
        {"script": "test_persistence.py", "description": "Data persistence across restarts"},
    ],
}

# Quick test subset for fast validation
QUICK_TESTS = [
    "test_load_balancing.py",
    "test_fault_tolerance.py",
    "test_scheduling_overhead.py",
]

OUTPUT_DIR = "results"
DEFAULT_TIMEOUT = 300  # 5 minutes per test


def log(message, level="INFO"):
    """Print log message to stderr"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}", file=sys.stderr)


def run_test(script_name, timeout=DEFAULT_TIMEOUT):
    """Run a test script and capture its JSON output"""
    result = {
        "script": script_name,
        "status": "unknown",
        "start_time": datetime.utcnow().isoformat(),
        "duration_seconds": 0,
    }

    start_time = time.time()

    try:
        process = subprocess.run(
            [sys.executable, script_name],
            capture_output=True,
            text=True,
            timeout=timeout
        )

        result["duration_seconds"] = round(time.time() - start_time, 2)

        # Print stderr (logs) for user visibility
        if process.stderr:
            print(process.stderr, file=sys.stderr)

        if process.returncode != 0:
            result["status"] = "error"
            result["error"] = f"Exit code: {process.returncode}"
            result["stderr"] = process.stderr[-500:] if process.stderr else None
            return result

        # Parse JSON output (last non-empty line)
        output_lines = [l for l in process.stdout.strip().split('\n') if l.strip()]

        if not output_lines:
            result["status"] = "error"
            result["error"] = "No output received"
            return result

        try:
            # Find the JSON output (might not be last line if there's trailing whitespace)
            json_output = None
            for line in reversed(output_lines):
                if line.strip().startswith('{'):
                    json_output = json.loads(line)
                    break

            if json_output:
                result.update(json_output)
                result["status"] = json_output.get("status", "completed")
            else:
                result["status"] = "error"
                result["error"] = "No JSON output found"
                result["raw_output"] = output_lines[-1][:200]

        except json.JSONDecodeError as e:
            result["status"] = "error"
            result["error"] = f"Invalid JSON: {str(e)}"
            result["raw_output"] = output_lines[-1][:200]

    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["error"] = f"Test exceeded {timeout}s timeout"
        result["duration_seconds"] = timeout

    except FileNotFoundError:
        result["status"] = "skipped"
        result["error"] = f"Script not found: {script_name}"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def get_tests_to_run(categories=None, quick=False, scripts=None):
    """Get list of tests based on filters"""
    if scripts:
        # Run specific scripts
        return [{"script": s, "description": "User specified"} for s in scripts]

    if quick:
        return [{"script": s, "description": "Quick test"} for s in QUICK_TESTS]

    tests = []
    for cat, cat_tests in TESTS.items():
        if categories is None or cat in categories:
            for test in cat_tests:
                test["category"] = cat
                tests.append(test)

    return tests


def print_summary(results):
    """Print a summary table of results"""
    log("=" * 60)
    log("SUMMARY")
    log("=" * 60)

    passed = sum(1 for r in results if r.get("status") == "passed")
    failed = sum(1 for r in results if r.get("status") in ["failed", "error"])
    skipped = sum(1 for r in results if r.get("status") == "skipped")
    partial = sum(1 for r in results if r.get("status") in ["partial", "passed_with_warnings"])

    for r in results:
        status = r.get("status", "unknown").upper()
        script = r.get("script", "unknown")
        duration = r.get("duration_seconds", 0)

        status_symbol = {
            "PASSED": "✓",
            "FAILED": "✗",
            "ERROR": "✗",
            "SKIPPED": "○",
            "PARTIAL": "◐",
            "TIMEOUT": "⏱",
        }.get(status, "?")

        log(f"  {status_symbol} {script:<40} {status:<10} ({duration}s)")

    log("-" * 60)
    log(f"  Total: {len(results)} | Passed: {passed} | Failed: {failed} | Partial: {partial} | Skipped: {skipped}")
    log("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Run Swarm Benchmark Suite")
    parser.add_argument("--category", "-c", nargs="+",
                        choices=list(TESTS.keys()),
                        help="Run only specific categories")
    parser.add_argument("--quick", "-q", action="store_true",
                        help="Run quick subset of tests")
    parser.add_argument("--script", "-s", nargs="+",
                        help="Run specific test scripts")
    parser.add_argument("--timeout", "-t", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Timeout per test in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--output", "-o", default=None,
                        help="Output file name (default: auto-generated)")
    parser.add_argument("--list", "-l", action="store_true",
                        help="List available tests and exit")

    args = parser.parse_args()

    # List mode
    if args.list:
        print("\nAvailable Tests:")
        print("=" * 60)
        for cat, tests in TESTS.items():
            print(f"\n{cat.upper()}:")
            for t in tests:
                print(f"  - {t['script']}: {t['description']}")
        print()
        return

    # Get tests to run
    tests = get_tests_to_run(
        categories=args.category,
        quick=args.quick,
        scripts=args.script
    )

    if not tests:
        log("No tests to run!", "ERROR")
        return 1

    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Generate output filename
    if args.output:
        output_file = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(OUTPUT_DIR, f"benchmark_{timestamp}.json")

    # Start
    log(f"Starting Benchmark Suite ({len(tests)} tests)")
    log(f"Output will be saved to: {output_file}")

    suite_start = datetime.utcnow().isoformat()
    results = []

    for i, test in enumerate(tests, 1):
        script = test["script"]
        category = test.get("category", "unknown")

        log(f"[{i}/{len(tests)}] Running {script} ({category})")

        result = run_test(script, timeout=args.timeout)
        result["category"] = category
        results.append(result)

        status = result.get("status", "unknown")
        duration = result.get("duration_seconds", 0)
        log(f"[{i}/{len(tests)}] Finished {script}: {status.upper()} ({duration}s)\n")

        # Brief pause between tests
        if i < len(tests):
            time.sleep(2)

    # Build report
    suite_end = datetime.utcnow().isoformat()

    report = {
        "suite_name": "Swarm Benchmark Suite",
        "platform": "Docker Swarm",
        "start_time": suite_start,
        "end_time": suite_end,
        "total_duration_seconds": sum(r.get("duration_seconds", 0) for r in results),
        "summary": {
            "total_tests": len(results),
            "passed": sum(1 for r in results if r.get("status") == "passed"),
            "failed": sum(1 for r in results if r.get("status") in ["failed", "error"]),
            "partial": sum(1 for r in results if r.get("status") in ["partial", "passed_with_warnings"]),
            "skipped": sum(1 for r in results if r.get("status") == "skipped"),
            "timeout": sum(1 for r in results if r.get("status") == "timeout"),
        },
        "results_by_category": {},
        "results": results
    }

    # Group by category
    for cat in TESTS.keys():
        cat_results = [r for r in results if r.get("category") == cat]
        if cat_results:
            report["results_by_category"][cat] = {
                "tests": len(cat_results),
                "passed": sum(1 for r in cat_results if r.get("status") == "passed"),
                "results": cat_results
            }

    # Save report
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2)

    # Print summary
    print_summary(results)

    log(f"Results saved to: {os.path.abspath(output_file)}")

    # Return exit code based on results
    if report["summary"]["failed"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)