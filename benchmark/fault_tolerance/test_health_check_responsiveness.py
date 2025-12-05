"""
Test: Health Check Responsiveness
Taxonomy Category: Resource Management -> Fault Tolerance

Measures how quickly Swarm detects and responds to unhealthy containers.
Unlike fault_tolerance (which kills containers), this test makes containers
fail their health checks to measure the health monitoring system.

Key metrics:
1. Time from unhealthy state to container restart
2. Time from unhealthy to new container running
3. Behavior under different health check configurations
"""

import subprocess
import time
import json
import sys
import requests

# Configuration
STACK_NAME = "cob-service"
SERVICE_NAME = f"{STACK_NAME}_backend"
REGISTRY = "192.168.15.9:5000"
TEST_SERVICE_NAME = "healthcheck-test"
TEST_IMAGE = f"{REGISTRY}/cob-service-backend:latest"
NETWORK_NAME = "cob-service_cob-service"
NUM_ITERATIONS = 3
TIMEOUT_SECONDS = 120


def log(message):
    """Output to stderr to not interfere with final JSON"""
    print(f"[HEALTH] {message}", file=sys.stderr)


def cleanup_test_service():
    """Remove test service if exists"""
    subprocess.run(
        f"docker service rm {TEST_SERVICE_NAME}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)


def create_service_with_healthcheck(interval, timeout, retries, start_period):
    """
    Create a test service with specific health check parameters.
    The health check will curl the backend endpoint.
    """
    cleanup_test_service()

    cmd = f"""docker service create \
        --name {TEST_SERVICE_NAME} \
        --replicas 1 \
        --network {NETWORK_NAME} \
        --health-cmd "curl -f http://localhost:5000/ || exit 1" \
        --health-interval {interval}s \
        --health-timeout {timeout}s \
        --health-retries {retries} \
        --health-start-period {start_period}s \
        --restart-condition on-failure \
        --quiet \
        {TEST_IMAGE}"""

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0


def get_service_health_status():
    """Get current health status of test service containers"""
    cmd = f"docker service ps {TEST_SERVICE_NAME} --format '{{{{.ID}}}} {{{{.CurrentState}}}} {{{{.Error}}}}' --no-trunc"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip()
    except:
        return ""


def get_container_health():
    """Get container-level health status"""
    # First get container ID
    cmd = f"docker service ps {TEST_SERVICE_NAME} --filter 'desired-state=running' --format '{{{{.ID}}}}'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    task_id = result.stdout.strip().split('\n')[0] if result.stdout.strip() else None

    if not task_id:
        return None, None

    # Get container ID from task
    cmd = f"docker inspect --format '{{{{.Status.ContainerStatus.ContainerID}}}}' {task_id}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    container_id = result.stdout.strip()[:12] if result.stdout.strip() else None

    if not container_id:
        return task_id, None

    # Get health status
    cmd = f"docker inspect --format '{{{{.State.Health.Status}}}}' {container_id}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    health = result.stdout.strip()

    return task_id, health


def wait_for_healthy(timeout):
    """Wait for service to become healthy"""
    start = time.time()
    while time.time() - start < timeout:
        task_id, health = get_container_health()
        if health == "healthy":
            return True, time.time() - start
        time.sleep(0.5)
    return False, timeout


def simulate_unhealthy_container():
    """
    Make container unhealthy by stopping its internal process.
    We'll use docker exec to kill the Flask process inside.
    """
    # Get container ID
    cmd = f"docker service ps {TEST_SERVICE_NAME} --filter 'desired-state=running' --format '{{{{.ID}}}}'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    task_id = result.stdout.strip().split('\n')[0] if result.stdout.strip() else None

    if not task_id:
        return None, "No task found"

    # Get container ID
    cmd = f"docker inspect --format '{{{{.Status.ContainerStatus.ContainerID}}}}' {task_id}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    container_id = result.stdout.strip()[:12] if result.stdout.strip() else None

    if not container_id:
        return None, "No container found"

    # Kill the Flask process inside (makes health check fail)
    cmd = f"docker exec {container_id} pkill -f flask || docker exec {container_id} pkill -f python"
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return container_id, None


def measure_health_check_response(config):
    """
    Measure how quickly Swarm responds to health check failures.

    Returns:
    - time_to_unhealthy: time from killing process to unhealthy state
    - time_to_restart: time from unhealthy to new container starting
    - total_recovery: total time to healthy state again
    """
    interval, timeout, retries, start_period = config

    log(f"  Config: interval={interval}s, timeout={timeout}s, retries={retries}")

    # Create service with health check
    if not create_service_with_healthcheck(interval, timeout, retries, start_period):
        return {"success": False, "error": "Failed to create service"}

    # Wait for initial healthy state
    log("  Waiting for initial healthy state...")
    healthy, wait_time = wait_for_healthy(60)
    if not healthy:
        cleanup_test_service()
        return {"success": False, "error": "Service never became healthy"}

    log(f"  Service healthy after {wait_time:.2f}s")

    initial_task, _ = get_container_health()

    # Make container unhealthy
    log("  Making container unhealthy...")
    unhealthy_start = time.time()
    container_id, error = simulate_unhealthy_container()

    if error:
        cleanup_test_service()
        return {"success": False, "error": error}

    # Track state changes
    result = {
        "success": False,
        "config": {
            "interval": interval,
            "timeout": timeout,
            "retries": retries,
            "start_period": start_period
        },
        "initial_task": initial_task,
        "killed_container": container_id,
        "time_to_unhealthy_detected": None,
        "time_to_new_task": None,
        "time_to_healthy": None,
        "expected_detection_time": interval * retries + timeout * retries,
        "states_observed": []
    }

    # Monitor until recovery or timeout
    new_task_detected = False
    last_state = None

    while time.time() - unhealthy_start < TIMEOUT_SECONDS:
        task_id, health = get_container_health()
        service_status = get_service_health_status()

        current_state = f"{task_id}:{health}"
        if current_state != last_state:
            elapsed = round(time.time() - unhealthy_start, 2)
            result["states_observed"].append({
                "time": elapsed,
                "task": task_id[:8] if task_id else None,
                "health": health,
                "status": service_status[:50] if service_status else None
            })
            last_state = current_state

        # Detect new task (Swarm reacted)
        if task_id and task_id != initial_task and not new_task_detected:
            result["time_to_new_task"] = round(time.time() - unhealthy_start, 4)
            new_task_detected = True
            log(f"  New task detected at {result['time_to_new_task']}s")

        # Detect full recovery
        if new_task_detected and health == "healthy":
            result["time_to_healthy"] = round(time.time() - unhealthy_start, 4)
            result["success"] = True
            log(f"  Fully recovered at {result['time_to_healthy']}s")
            break

        time.sleep(0.5)

    cleanup_test_service()
    return result


def run_health_check_test():
    """Run complete health check responsiveness test"""
    log("Starting Health Check Responsiveness test")

    # Different health check configurations to test
    # Format: (interval, timeout, retries, start_period)
    configs = [
        (5, 3, 3, 10),  # Default-ish: 5s interval, 3 retries = ~15s detection
        (2, 2, 2, 5),  # Aggressive: 2s interval, 2 retries = ~4s detection
        (10, 5, 3, 15),  # Conservative: 10s interval, 3 retries = ~30s detection
    ]

    all_results = []

    for config in configs:
        log(f"\n--- Testing config: interval={config[0]}s, retries={config[2]} ---")

        config_results = []
        for i in range(NUM_ITERATIONS):
            log(f"\nIteration {i + 1}/{NUM_ITERATIONS}")
            result = measure_health_check_response(config)
            config_results.append(result)
            time.sleep(3)

        # Aggregate for this config
        successful = [r for r in config_results if r.get("success")]

        if successful:
            detection_times = [r["time_to_new_task"] for r in successful if r.get("time_to_new_task")]
            recovery_times = [r["time_to_healthy"] for r in successful if r.get("time_to_healthy")]

            all_results.append({
                "config": config_results[0]["config"],
                "expected_detection_time": config_results[0].get("expected_detection_time"),
                "iterations": config_results,
                "aggregated": {
                    "success_rate": round(len(successful) / NUM_ITERATIONS * 100, 2),
                    "avg_detection_time": round(sum(detection_times) / len(detection_times),
                                                4) if detection_times else None,
                    "avg_recovery_time": round(sum(recovery_times) / len(recovery_times), 4) if recovery_times else None
                }
            })
        else:
            all_results.append({
                "config": configs[0] if not config_results else config_results[0].get("config"),
                "iterations": config_results,
                "aggregated": {"error": "All iterations failed"}
            })

    # Final output
    output = {
        "test_name": "health_check_responsiveness",
        "category": "fault_tolerance",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "test_image": TEST_IMAGE,
            "iterations_per_config": NUM_ITERATIONS,
            "timeout_seconds": TIMEOUT_SECONDS
        },
        "status": "passed" if any(
            r.get("aggregated", {}).get("success_rate", 0) > 50 for r in all_results) else "failed",
        "results_by_config": all_results,
        "analysis": {
            "conclusion": analyze_results(all_results)
        }
    }

    print(json.dumps(output, indent=2))


def analyze_results(results):
    """Analyze results and provide interpretation"""
    conclusions = []

    for r in results:
        if "aggregated" in r and "avg_detection_time" in r["aggregated"]:
            config = r["config"]
            expected = r.get("expected_detection_time", 0)
            actual = r["aggregated"]["avg_detection_time"]

            if actual and expected:
                ratio = actual / expected
                if ratio < 1.5:
                    conclusions.append(
                        f"Config (interval={config['interval']}s, retries={config['retries']}): Detection time ({actual:.1f}s) close to expected ({expected}s)")
                else:
                    conclusions.append(
                        f"Config (interval={config['interval']}s, retries={config['retries']}): Detection slower than expected ({actual:.1f}s vs {expected}s)")

    return conclusions if conclusions else ["Insufficient data for analysis"]


if __name__ == "__main__":
    run_health_check_test()