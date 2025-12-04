import subprocess
import time
import json
import sys
import statistics

STACK_NAME = "cob-service"
TEST_SERVICE_NAME = "scheduling-test"
TEST_IMAGE = "cob-service-backend:latest"
NUM_ITERATIONS = 10
TIMEOUT_SECONDS = 60


def log(message):
    """Output on stderr"""
    print(f"[SCHED] {message}", file=sys.stderr)


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



if __name__ == "__main__":
    run_scheduling_overhead_test()