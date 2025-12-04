"""
Test: Scheduling Overhead
Taxonomy Category: Scheduler Architecture

Measures the time required for the orchestrator to:
1. Receive the deployment request
2. Decide which node to place the container on (scheduling decision)
3. Create and start the container

This test reveals the efficiency of Swarm's centralized scheduler.
"""

import subprocess
import time
import json
import sys
import statistics

# Configuration
STACK_NAME = "cob-service"
TEST_SERVICE_NAME = "scheduling-test"
REGISTRY = "192.168.15.9:5000"
TEST_IMAGE = f"{REGISTRY}/cob-service-backend:latest"  # Full path with registry
NETWORK_NAME = "cob-service_cob-service"  # Actual overlay network name
NUM_ITERATIONS = 10  # Number of iterations for reliable statistics
TIMEOUT_SECONDS = 60


def log(message):
    """Output to stderr to not interfere with final JSON"""
    print(f"[SCHED] {message}", file=sys.stderr)


def cleanup_test_service():
    """Remove test service if it exists"""
    subprocess.run(
        f"docker service rm {TEST_SERVICE_NAME}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    # Attendi che sia effettivamente rimosso
    time.sleep(2)


def get_service_state(service_name):
    """
    Returns the service state.
    Possible states: 'not_found', 'pending', 'running', 'failed'
    """
    try:
        # Verifica se il servizio esiste
        cmd = f"docker service inspect {service_name} --format '{{{{.ID}}}}'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            return "not_found", None

        # Verifica lo stato dei task
        cmd = f"docker service ps {service_name} --format '{{{{.CurrentState}}}}' --filter 'desired-state=running'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        states = result.stdout.strip().split('\n')

        for state in states:
            if state.lower().startswith('running'):
                return "running", state
            elif 'pending' in state.lower() or 'preparing' in state.lower():
                return "pending", state
            elif 'failed' in state.lower() or 'rejected' in state.lower():
                return "failed", state

        return "pending", states[0] if states else None

    except Exception as e:
        return "error", str(e)


def measure_single_scheduling():
    """
    Measures scheduling time for a single service creation.

    Returns a dictionary with:
    - total_time: total time from command sent to container running
    - phases: breakdown of phases (if measurable)
    - success: boolean
    """
    cleanup_test_service()

    result = {
        "success": False,
        "total_time": None,
        "phases": {
            "command_accepted": None,  # Time until docker responds
            "scheduling_to_running": None  # Time from accepted to running
        },
        "final_state": None,
        "node_assigned": None
    }

    # Phase 1: Send command and wait for response
    create_cmd = f"""docker service create \
        --name {TEST_SERVICE_NAME} \
        --replicas 1 \
        --restart-condition none \
        --network {NETWORK_NAME} \
        {TEST_IMAGE}"""

    start_time = time.time()

    proc = subprocess.run(
        create_cmd,
        shell=True,
        capture_output=True,
        text=True
    )

    command_accepted_time = time.time()
    result["phases"]["command_accepted"] = round(command_accepted_time - start_time, 4)

    if proc.returncode != 0:
        result["error"] = proc.stderr
        cleanup_test_service()
        return result

    # Phase 2: Poll until running state
    while True:
        elapsed = time.time() - start_time
        if elapsed > TIMEOUT_SECONDS:
            result["error"] = "Timeout waiting for container to start"
            result["final_state"] = "timeout"
            break

        state, details = get_service_state(TEST_SERVICE_NAME)

        if state == "running":
            total_time = time.time() - start_time
            result["success"] = True
            result["total_time"] = round(total_time, 4)
            result["phases"]["scheduling_to_running"] = round(
                total_time - result["phases"]["command_accepted"], 4
            )
            result["final_state"] = "running"

            # Recupera il nodo assegnato
            node_cmd = f"docker service ps {TEST_SERVICE_NAME} --format '{{{{.Node}}}}' --filter 'desired-state=running'"
            node_result = subprocess.run(node_cmd, shell=True, capture_output=True, text=True)
            result["node_assigned"] = node_result.stdout.strip()
            break

        elif state == "failed":
            result["error"] = f"Service failed: {details}"
            result["final_state"] = "failed"
            break

        time.sleep(0.1)  # Polling ogni 100ms per precisione

    cleanup_test_service()
    return result


def run_scheduling_overhead_test():
    """Run complete test with multiple iterations"""
    log(f"Starting Scheduling Overhead test ({NUM_ITERATIONS} iterations)")
    log(f"Test image: {TEST_IMAGE}")

    # Pre-cleanup
    cleanup_test_service()

    measurements = []
    successful_runs = 0
    failed_runs = 0
    nodes_used = {}

    for i in range(NUM_ITERATIONS):
        log(f"Iteration {i + 1}/{NUM_ITERATIONS}...")

        measurement = measure_single_scheduling()
        measurements.append(measurement)

        if measurement["success"]:
            successful_runs += 1
            log(f"  -> OK: {measurement['total_time']}s (node: {measurement['node_assigned']})")

            # Track node distribution
            node = measurement.get("node_assigned", "unknown")
            nodes_used[node] = nodes_used.get(node, 0) + 1
        else:
            failed_runs += 1
            log(f"  -> FAILED: {measurement.get('error', 'unknown error')}")

        # Pause between iterations to avoid overload
        time.sleep(1)

    # Calculate statistics
    successful_times = [m["total_time"] for m in measurements if m["success"]]
    command_times = [m["phases"]["command_accepted"] for m in measurements if m["success"]]
    scheduling_times = [m["phases"]["scheduling_to_running"] for m in measurements if m["success"]]

    stats = {}
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

    # Build final result
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

    # Output JSON
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run_scheduling_overhead_test()