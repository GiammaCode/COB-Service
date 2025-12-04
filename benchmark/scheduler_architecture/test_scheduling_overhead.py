import subprocess
import time
import json
import sys
import statistics
from time import sleep

STACK_NAME = "cob-service"
TEST_SERVICE_NAME = "scheduling-test"
TEST_IMAGE = "cob-service-backend:latest"
NUM_ITERATIONS = 10
TIMEOUT_SECONDS = 60


def log(message):
    """Output on stderr"""
    print(f"[SCHED] {message}", file=sys.stderr)

def cleanup_test_service():
    subprocess.run(
        f"docker service rm {TEST_SERVICE_NAME}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def measure_single_scheduling():
    cleanup_test_service()

def run_scheduling_overhead_test():
    log(f"start scheduling overhead test, {NUM_ITERATIONS} iterations")
    log(f"test image: {TEST_IMAGE}")

    cleanup_test_service()

    measurements = []
    successful_runs = []
    failed_runs = 0
    nodes_used = 0

    for i in range(NUM_ITERATIONS):
        log(f"iteration {i+1}/{NUM_ITERATIONS}")

        measurement = measure_single_scheduling()
        measurements.append(measurement)

        if measurement["success"]:
            successful_runs += i
            log(f"  -> OK: {measurement['total_time']}s (node: {measurement['node_assigned']})")

            node = measurement.get("node_assigned", "unknown")
            nodes_used[node] = nodes_used.get(node, 0) + 1
        else:
            failed_runs += 1

        time.sleep(1)

    #stats
    successful_times = [m["total_time"] for m in measurements if m["success"]]
    command_times = [m["phases"]["command_accepted"] for m in measurements if m["success"]]
    scheduling_times = [m["phases"]["scheduling_to_running"] for m in measurements if m["success"]]

    stats = []
    if successful_times:
        stats = {
            "total_time": {
                "min": round(min(successful_times), 4),
                "max": round(max(successful_times), 4),
                "mean": round(statistics.mean(successful_times), 4),
                "median": round(statistics.median(successful_times), 4),
                "stdev": round(statistics.stdev(successful_times), 4) if len(successful_times) > 1 else 0
            },
            "command_acceptance": {
                "mean": round(statistics.mean(command_times), 4),
                "stdev": round(statistics.stdev(command_times), 4) if len(command_times) > 1 else 0
            },
            "scheduling_to_running": {
                "mean": round(statistics.mean(scheduling_times), 4),
                "stdev": round(statistics.stdev(scheduling_times), 4) if len(scheduling_times) > 1 else 0
            }
        }
        result = {
            "test_name": "scheduling_overhead",
            "category": "scheduler_architecture",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "config": {
                "iterations": NUM_ITERATIONS,
                "test_image": TEST_IMAGE,
                "timeout_seconds": TIMEOUT_SECONDS
            },
            "status": "passed" if successful_runs > NUM_ITERATIONS * 0.8 else "failed",
            "metrics": {
                "successful_runs": successful_runs,
                "failed_runs": failed_runs,
                "success_rate": round(successful_runs / NUM_ITERATIONS * 100, 2),
                "statistics": stats,
                "node_distribution": nodes_used
            },
            "raw_measurements": measurements
        }

        if failed_runs > 0:
            result["warnings"] = f"{failed_runs} iterations failed"

        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run_scheduling_overhead_test()