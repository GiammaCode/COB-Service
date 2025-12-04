"""
Test: Concurrent Deployments
Taxonomy Category: Scheduler Architecture

Measures scheduler behavior under concurrent load:
- Does scheduling time degrade with more simultaneous requests?
- Is there a saturation point?
- How is the request queue handled?

This test reveals the limits of the centralized scheduler architecture.
"""

import subprocess
import time
import json
import sys
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
STACK_NAME = "cob-service"
TEST_SERVICE_PREFIX = "concurrent-test"
REGISTRY = "192.168.15.9:5000"
TEST_IMAGE = f"{REGISTRY}/cob-service-backend:latest"
NETWORK_NAME = "cob-service_cob-service"
CONCURRENCY_LEVELS = [1, 3, 5, 10]  # Number of simultaneous deployments to test
TIMEOUT_SECONDS = 120
ITERATIONS_PER_LEVEL = 3  # Repetitions for each concurrency level


def log(message):
    """Output to stderr to not interfere with final JSON"""
    print(f"[CONC] {message}", file=sys.stderr)


def cleanup_all_test_services():
    """Remove all test services"""
    cmd = f"docker service ls --filter name={TEST_SERVICE_PREFIX} -q"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    service_ids = result.stdout.strip().split('\n')

    for sid in service_ids:
        if sid:
            subprocess.run(
                f"docker service rm {sid}",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

    time.sleep(3)  # Wait for complete cleanup


def wait_for_service_running(service_name, timeout):
    """
    Wait for a service to be running.
    Returns (success, time_to_running, final_state)
    """
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            return False, elapsed, "timeout"

        try:
            cmd = f"docker service ps {service_name} --format '{{{{.CurrentState}}}}' --filter 'desired-state=running' 2>/dev/null"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

            if result.stdout:
                state = result.stdout.strip().split('\n')[0].lower()
                if state.startswith('running'):
                    return True, time.time() - start_time, "running"
                elif 'failed' in state or 'rejected' in state:
                    return False, time.time() - start_time, "failed"
        except Exception:
            pass

        time.sleep(0.1)


def deploy_single_service(service_id, start_barrier, results_lock, results_list):
    """
    Function executed by each thread to deploy a single service.
    Uses a barrier to synchronize simultaneous start.
    """
    service_name = f"{TEST_SERVICE_PREFIX}-{service_id}"

    result = {
        "service_id": service_id,
        "service_name": service_name,
        "success": False,
        "command_time": None,
        "total_time": None,
        "node_assigned": None,
        "error": None
    }

    # Wait for all threads to be ready
    start_barrier.wait()

    # Start timestamp (synchronized across all threads)
    deploy_start = time.time()

    # Create the service
    create_cmd = f"""docker service create \
        --name {service_name} \
        --replicas 1 \
        --restart-condition none \
        --network {NETWORK_NAME} \
        --quiet \
        {TEST_IMAGE}"""

    proc = subprocess.run(create_cmd, shell=True, capture_output=True, text=True)
    command_time = time.time() - deploy_start
    result["command_time"] = round(command_time, 4)

    if proc.returncode != 0:
        result["error"] = proc.stderr.strip()
        with results_lock:
            results_list.append(result)
        return

    # Wait for service to be running
    success, time_to_running, final_state = wait_for_service_running(
        service_name,
        TIMEOUT_SECONDS - command_time
    )

    result["success"] = success
    result["total_time"] = round(command_time + time_to_running, 4) if success else None
    result["final_state"] = final_state

    # Get assigned node
    if success:
        node_cmd = f"docker service ps {service_name} --format '{{{{.Node}}}}' --filter 'desired-state=running'"
        node_result = subprocess.run(node_cmd, shell=True, capture_output=True, text=True)
        result["node_assigned"] = node_result.stdout.strip()

    with results_lock:
        results_list.append(result)


def run_concurrent_deployment(num_concurrent):
    """
    Run a concurrent deployment test with N simultaneous services.
    Returns aggregated metrics.
    """
    log(f"  Deploying {num_concurrent} services simultaneously...")

    cleanup_all_test_services()

    results_list = []
    results_lock = threading.Lock()

    # Barrier to synchronize all threads start
    start_barrier = threading.Barrier(num_concurrent)

    threads = []
    batch_start = time.time()

    # Start all threads
    for i in range(num_concurrent):
        t = threading.Thread(
            target=deploy_single_service,
            args=(i, start_barrier, results_lock, results_list)
        )
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join(timeout=TIMEOUT_SECONDS + 10)

    batch_total_time = time.time() - batch_start

    # Analyze results
    successful = [r for r in results_list if r["success"]]
    failed = [r for r in results_list if not r["success"]]

    metrics = {
        "concurrency_level": num_concurrent,
        "batch_total_time": round(batch_total_time, 4),
        "successful_deployments": len(successful),
        "failed_deployments": len(failed),
        "success_rate": round(len(successful) / num_concurrent * 100, 2)
    }

    if successful:
        times = [r["total_time"] for r in successful]
        command_times = [r["command_time"] for r in successful]

        metrics["scheduling_times"] = {
            "min": round(min(times), 4),
            "max": round(max(times), 4),
            "mean": round(statistics.mean(times), 4),
            "spread": round(max(times) - min(times), 4),  # Difference between first and last
        }

        metrics["command_times"] = {
            "mean": round(statistics.mean(command_times), 4),
            "max": round(max(command_times), 4)
        }

        # Throughput: deployed services per second
        metrics["throughput"] = round(len(successful) / batch_total_time, 4)

        # Node distribution
        nodes = {}
        for r in successful:
            node = r.get("node_assigned", "unknown")
            nodes[node] = nodes.get(node, 0) + 1
        metrics["node_distribution"] = nodes

    if failed:
        metrics["failure_reasons"] = [r.get("error", "unknown") for r in failed]

    # Cleanup
    cleanup_all_test_services()

    return metrics, results_list


def run_concurrent_deployments_test():
    """Run complete test on all concurrency levels"""
    log("Starting Concurrent Deployments test")
    log(f"Concurrency levels: {CONCURRENCY_LEVELS}")
    log(f"Iterations per level: {ITERATIONS_PER_LEVEL}")

    # Pre-cleanup
    cleanup_all_test_services()

    all_results = {}

    for level in CONCURRENCY_LEVELS:
        log(f"\n--- Testing concurrency level: {level} ---")

        level_results = []

        for iteration in range(ITERATIONS_PER_LEVEL):
            log(f"Iteration {iteration + 1}/{ITERATIONS_PER_LEVEL}")
            metrics, raw = run_concurrent_deployment(level)
            level_results.append(metrics)
            time.sleep(5)  # Pause between iterations

        # Aggregate iteration results
        if level_results:
            successful_results = [r for r in level_results if r["successful_deployments"] > 0]

            if successful_results:
                avg_mean_time = statistics.mean([
                    r["scheduling_times"]["mean"]
                    for r in successful_results
                    if "scheduling_times" in r
                ])
                avg_throughput = statistics.mean([
                    r["throughput"]
                    for r in successful_results
                    if "throughput" in r
                ])

                all_results[f"concurrency_{level}"] = {
                    "iterations": level_results,
                    "aggregated": {
                        "avg_scheduling_time": round(avg_mean_time, 4),
                        "avg_throughput": round(avg_throughput, 4),
                        "total_success_rate": round(
                            sum(r["successful_deployments"] for r in level_results) /
                            (level * ITERATIONS_PER_LEVEL) * 100, 2
                        )
                    }
                }
            else:
                all_results[f"concurrency_{level}"] = {
                    "iterations": level_results,
                    "aggregated": {"error": "All iterations failed"}
                }

    # Calculate scaling efficiency
    scaling_analysis = analyze_scaling(all_results)

    # Build final result
    result = {
        "test_name": "concurrent_deployments",
        "category": "scheduler_architecture",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "concurrency_levels": CONCURRENCY_LEVELS,
            "iterations_per_level": ITERATIONS_PER_LEVEL,
            "test_image": TEST_IMAGE,
            "timeout_seconds": TIMEOUT_SECONDS
        },
        "status": determine_status(all_results),
        "results_by_concurrency": all_results,
        "scaling_analysis": scaling_analysis
    }

    # Output JSON
    print(json.dumps(result, indent=2))


def analyze_scaling(results):
    """
    Analyze how performance scales with concurrency.
    Determines if degradation is linear, sublinear or superlinear.
    """
    analysis = {
        "scheduling_time_trend": [],
        "throughput_trend": [],
        "degradation_factor": None,
        "bottleneck_detected": False,
        "interpretation": ""
    }

    baseline_time = None
    baseline_throughput = None

    for level in CONCURRENCY_LEVELS:
        key = f"concurrency_{level}"
        if key in results and "aggregated" in results[key]:
            agg = results[key]["aggregated"]

            if "avg_scheduling_time" in agg:
                analysis["scheduling_time_trend"].append({
                    "concurrency": level,
                    "avg_time": agg["avg_scheduling_time"]
                })

                if baseline_time is None:
                    baseline_time = agg["avg_scheduling_time"]

            if "avg_throughput" in agg:
                analysis["throughput_trend"].append({
                    "concurrency": level,
                    "throughput": agg["avg_throughput"]
                })

                if baseline_throughput is None:
                    baseline_throughput = agg["avg_throughput"]

    # Calculate degradation factor
    if len(analysis["scheduling_time_trend"]) >= 2:
        first = analysis["scheduling_time_trend"][0]["avg_time"]
        last = analysis["scheduling_time_trend"][-1]["avg_time"]
        first_conc = analysis["scheduling_time_trend"][0]["concurrency"]
        last_conc = analysis["scheduling_time_trend"][-1]["concurrency"]

        if first > 0 and first_conc > 0:
            # How much time increases relative to concurrency increase
            time_increase = last / first
            conc_increase = last_conc / first_conc

            analysis["degradation_factor"] = round(time_increase / conc_increase, 4)

            if analysis["degradation_factor"] > 1.5:
                analysis["bottleneck_detected"] = True
                analysis["interpretation"] = (
                    f"Scheduler bottleneck detected: scheduling time increases "
                    f"{analysis['degradation_factor']:.2f}x faster than concurrency. "
                    "Centralized scheduler may be saturating."
                )
            elif analysis["degradation_factor"] > 1.0:
                analysis["interpretation"] = (
                    f"Moderate degradation: scheduling time increases proportionally "
                    f"to concurrency (factor: {analysis['degradation_factor']:.2f}). "
                    "This is expected for a centralized scheduler."
                )
            else:
                analysis["interpretation"] = (
                    f"Good scaling: scheduling time increases slower than concurrency "
                    f"(factor: {analysis['degradation_factor']:.2f}). "
                    "Scheduler handles concurrent load efficiently."
                )

    return analysis


def determine_status(results):
    """Determina lo status complessivo del test"""
    total_expected = sum(CONCURRENCY_LEVELS) * ITERATIONS_PER_LEVEL
    total_successful = 0

    for level in CONCURRENCY_LEVELS:
        key = f"concurrency_{level}"
        if key in results and "iterations" in results[key]:
            for iteration in results[key]["iterations"]:
                total_successful += iteration.get("successful_deployments", 0)

    success_rate = total_successful / total_expected if total_expected > 0 else 0

    if success_rate >= 0.9:
        return "passed"
    elif success_rate >= 0.7:
        return "passed_with_warnings"
    else:
        return "failed"


if __name__ == "__main__":
    run_concurrent_deployments_test()