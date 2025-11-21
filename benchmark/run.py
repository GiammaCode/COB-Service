import subprocess
import sys
import time
from datetime import datetime

TESTS = [
    {
        "name": "Load Balancing",
        "script": "test_load_balancing.py",
        "description": "Tests distribution of requests across backend replicas"
    },
    {
        "name": "Fault Tolerance",
        "script": "test_fault_tolerance.py",
        "description": "Tests automatic recovery after container failure"
    },
    {
        "name": "Data Persistence",
        "script": "test_persistence.py",
        "description": "Tests data survival after database restart"
    },
    {
        "name": "Rolling Update",
        "script": "test_rolling_update.py",
        "description": "Tests zero-downtime deployment updates"
    }
    #,
    #{
    #    "name": "Scalability",
    #    "script": "test_scalability.py",
    #    "description": "Tests performance improvement with horizontal scaling"
    #}
]


def print_header(text):
    """Print a formatted header"""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70 + "\n")


def print_test_info(test_num, total, test):
    """Print test information"""
    print(f"\n{'─' * 70}")
    print(f"Test {test_num}/{total}: {test['name']}")
    print(f"Description: {test['description']}")
    print(f"Script: {test['script']}")
    print(f"{'─' * 70}\n")


def run_test(script_name):
    """Run a single test script"""
    try:
        result = subprocess.run(
            [sys.executable, script_name],
            capture_output=False,
            text=True,
            timeout=300  # 5 minutes timeout
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"❌ Test timeout after 5 minutes")
        return False
    except FileNotFoundError:
        print(f"❌ Test script not found: {script_name}")
        return False
    except Exception as e:
        print(f"❌ Error running test: {e}")
        return False


def main():
    """Main test runner"""
    print_header("COB-Service Docker Swarm Benchmark Suite")

    start_time = datetime.now()
    print(f"Started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    results = []

    # Run each test
    for idx, test in enumerate(TESTS, 1):
        print_test_info(idx, len(TESTS), test)

        test_start = time.time()
        success = run_test(test['script'])
        test_duration = time.time() - test_start

        results.append({
            'name': test['name'],
            'success': success,
            'duration': test_duration
        })

        # Wait between tests
        if idx < len(TESTS):
            print("\n⏳ Waiting 5 seconds before next test...")
            time.sleep(5)

    # Print summary
    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds()

    print_header("Test Results Summary")

    print(f"{'Test Name':<25} | {'Status':<10} | {'Duration':<12}")
    print("─" * 70)

    passed = 0
    failed = 0

    for result in results:
        status = "✅ PASSED" if result['success'] else "❌ FAILED"
        duration = f"{result['duration']:.2f}s"
        print(f"{result['name']:<25} | {status:<10} | {duration:<12}")

        if result['success']:
            passed += 1
        else:
            failed += 1

    print("─" * 70)
    print(f"\nTotal Tests: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success Rate: {(passed / len(results) * 100):.1f}%")
    print(f"\nTotal Duration: {total_duration:.2f} seconds")
    print(f"Completed at: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Exit with appropriate code
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Tests interrupted by user")
        sys.exit(1)