"""
Test: Fault Tolerance
Taxonomy Category: Resource Management -> Fault Tolerance

Measures how Swarm handles node failures (simulated via Drain):
1. Detection time: How fast does Swarm detect a node is unavailable?
2. Recovery time: How fast does Swarm schedule replacement tasks on other nodes?
3. Service availability: How many requests fail during the migration?

This test drains a node while generating traffic to measure real-world impact.
"""

import subprocess
import time
import json
import sys
import threading
import requests
from concurrent.futures import ThreadPoolExecutor

# Configuration
STACK_NAME = "cob-service"
SERVICE_NAME = f"{STACK_NAME}_backend"
BACKEND_URL = "http://localhost:5001/"
NUM_ITERATIONS = 5
TIMEOUT_SECONDS = 60
TRAFFIC_DURATION = 30  # seconds to generate traffic


def log(message):
    """Output to stderr to not interfere with final JSON"""
    print(f"[FAULT] {message}", file=sys.stderr)


def set_node_availability(node_hostname, availability):
    """
    Change the state of a node (active/drain/pause).
    Executes the command on the Manager node.
    """
    cmd = f"docker node update --availability {availability} {node_hostname}"
    subprocess.run(
        cmd,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def get_backend_containers():
    """Get list of backend container IDs and their nodes"""
    cmd = f"docker service ps {SERVICE_NAME} --filter 'desired-state=running' --format '{{{{.ID}}}} {{{{.Node}}}} {{{{.CurrentState}}}}'"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        containers = []
        for line in result.stdout.strip().split('\n'):
            if line and 'Running' in line:
                parts = line.split()
                if len(parts) >= 2:
                    containers.append({
                        "task_id": parts[0],
                        "node": parts[1],
                        "state": ' '.join(parts[2:])
                    })
        return containers
    except Exception as e:
        log(f"Error getting containers: {e}")
        return []


def get_container_id_from_task(task_id):
    """Get actual container ID from task ID"""
    cmd = f"docker inspect --format '{{{{.Status.ContainerStatus.ContainerID}}}}' {task_id}"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        container_id = result.stdout.strip()
        return container_id[:12] if container_id else None
    except:
        return None


class TrafficGenerator:
    """Generates traffic and tracks success/failure during test"""

    def __init__(self, url):
        self.url = url
        self.running = False
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.latencies = []
        self.errors_during_recovery = []
        self.lock = threading.Lock()

    def send_request(self):
        """Send single request and track result"""
        try:
            start = time.time()
            resp = requests.get(self.url, timeout=2)
            latency = time.time() - start

            with self.lock:
                self.total_requests += 1
                if resp.status_code == 200:
                    self.successful_requests += 1
                    self.latencies.append(latency)
                else:
                    self.failed_requests += 1
                    self.errors_during_recovery.append({
                        "time": time.time(),
                        "status": resp.status_code
                    })
        except Exception as e:
            with self.lock:
                self.total_requests += 1
                self.failed_requests += 1
                self.errors_during_recovery.append({
                    "time": time.time(),
                    "error": str(e)
                })

    def run(self, duration):
        """Generate traffic for specified duration"""
        self.running = True
        end_time = time.time() + duration

        with ThreadPoolExecutor(max_workers=5) as executor:
            while self.running and time.time() < end_time:
                executor.submit(self.send_request)
                time.sleep(0.05)  # ~20 requests/second

    def stop(self):
        self.running = False

    def get_stats(self):
        with self.lock:
            avg_latency = sum(self.latencies) / len(self.latencies) if self.latencies else 0
            return {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "success_rate": round(self.successful_requests / self.total_requests * 100,
                                      2) if self.total_requests > 0 else 0,
                "avg_latency_ms": round(avg_latency * 1000, 2),
                "errors_count": len(self.errors_during_recovery)
            }


def measure_recovery(kill_time, initial_count, initial_tasks):
    """
    Measure time until service is fully recovered.
    Returns dict with detection_time, scheduling_time, total_recovery_time
    """
    result = {
        "detection_time": None,
        "scheduling_time": None,
        "container_running_time": None,
        "total_recovery_time": None,
        "new_task_id": None,
        "new_node": None
    }

    initial_task_ids = {c["task_id"] for c in initial_tasks}
    detected = False
    scheduled = False

    start_time = kill_time
    timeout = time.time() + TIMEOUT_SECONDS

    while time.time() < timeout:
        containers = get_backend_containers()
        current_task_ids = {c["task_id"] for c in containers}

        # Check for new task (scheduled)
        new_tasks = current_task_ids - initial_task_ids

        if new_tasks and not scheduled:
            result["scheduling_time"] = round(time.time() - start_time, 4)
            result["new_task_id"] = list(new_tasks)[0]
            scheduled = True

            # Find which node got the new container
            for c in containers:
                if c["task_id"] in new_tasks:
                    result["new_node"] = c["node"]
                    break

        # Check if back to full count and running
        running_count = len([c for c in containers if 'Running' in c.get("state", "")])

        if running_count >= initial_count and scheduled:
            result["container_running_time"] = round(time.time() - start_time, 4)
            result["total_recovery_time"] = result["container_running_time"]
            break

        time.sleep(0.1)

    return result


def run_single_fault_test(iteration):
    """Run a single fault tolerance test iteration"""
    log(f"Iteration {iteration}: Getting initial state...")

    # Get initial state
    initial_containers = get_backend_containers()
    initial_count = len(initial_containers)

    if initial_count == 0:
        return {"success": False, "error": "No backend containers found"}

    log(f"  Initial containers: {initial_count}")

    # Select target (first container)
    target = initial_containers[0]
    node_to_fail = target['node']

    # Retrieve container ID before it gets killed/moved (for reporting)
    killed_container_id = get_container_id_from_task(target['task_id'])

    log(f"  Target: task {target['task_id'][:8]} on node {node_to_fail}")

    # Start traffic generator in background
    traffic = TrafficGenerator(BACKEND_URL)
    traffic_thread = threading.Thread(target=traffic.run, args=(TRAFFIC_DURATION,))
    traffic_thread.start()

    # Wait a bit for traffic to stabilize
    time.sleep(2)

    # Simulate node failure
    log(f"  Draining node {node_to_fail}...")
    kill_time = time.time()
    set_node_availability(node_to_fail, "drain")

    # Measure recovery
    recovery = measure_recovery(kill_time, initial_count, initial_containers)

    # Wait for traffic to complete
    time.sleep(2)
    traffic.stop()
    traffic_thread.join()

    # Restore node availability for next tests
    log(f"  Restoring node {node_to_fail}...")
    set_node_availability(node_to_fail, "active")

    # Wait for node to be fully ready
    time.sleep(10)

    # Get traffic stats
    traffic_stats = traffic.get_stats()

    result = {
        "success": recovery["total_recovery_time"] is not None,
        "killed_task": target["task_id"][:8],
        "killed_node": node_to_fail,
        "killed_container": killed_container_id,
        "recovery": recovery,
        "traffic_during_test": traffic_stats
    }

    if recovery["total_recovery_time"]:
        log(f"  Recovery complete in {recovery['total_recovery_time']}s")
        log(f"  Traffic: {traffic_stats['success_rate']}% success ({traffic_stats['failed_requests']} failed)")
    else:
        log(f"  Recovery FAILED (timeout)")

    return result


def run_fault_tolerance_test():
    """Run complete fault tolerance test suite"""
    log("Starting Fault Tolerance test")
    log(f"Target service: {SERVICE_NAME}")
    log(f"Iterations: {NUM_ITERATIONS}")

    # Verify service exists and has replicas
    initial = get_backend_containers()
    if len(initial) < 2:
        log("WARNING: Service has less than 2 replicas. Recovery testing may be limited.")

    results = []

    for i in range(NUM_ITERATIONS):
        log(f"\n--- Iteration {i + 1}/{NUM_ITERATIONS} ---")
        result = run_single_fault_test(i + 1)
        results.append(result)

        # Wait between iterations for system to stabilize
        time.sleep(5)

    # Aggregate results
    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]

    recovery_times = [r["recovery"]["total_recovery_time"] for r in successful if r["recovery"]["total_recovery_time"]]
    scheduling_times = [r["recovery"]["scheduling_time"] for r in successful if r["recovery"]["scheduling_time"]]

    # Traffic analysis
    total_traffic_requests = sum(r["traffic_during_test"]["total_requests"] for r in successful)
    total_traffic_failures = sum(r["traffic_during_test"]["failed_requests"] for r in successful)

    output = {
        "test_name": "fault_tolerance",
        "category": "fault_tolerance",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "service": SERVICE_NAME,
            "iterations": NUM_ITERATIONS,
            "timeout_seconds": TIMEOUT_SECONDS,
            "traffic_duration": TRAFFIC_DURATION
        },
        "status": "passed" if len(successful) >= NUM_ITERATIONS * 0.8 else "failed",
        "summary": {
            "successful_recoveries": len(successful),
            "failed_recoveries": len(failed),
            "recovery_success_rate": round(len(successful) / NUM_ITERATIONS * 100, 2)
        },
        "metrics": {
            "recovery_time": {
                "min": round(min(recovery_times), 4) if recovery_times else None,
                "max": round(max(recovery_times), 4) if recovery_times else None,
                "mean": round(sum(recovery_times) / len(recovery_times), 4) if recovery_times else None
            },
            "scheduling_time": {
                "min": round(min(scheduling_times), 4) if scheduling_times else None,
                "max": round(max(scheduling_times), 4) if scheduling_times else None,
                "mean": round(sum(scheduling_times) / len(scheduling_times), 4) if scheduling_times else None
            },
            "traffic_impact": {
                "total_requests_during_tests": total_traffic_requests,
                "total_failures": total_traffic_failures,
                "overall_success_rate": round(
                    (total_traffic_requests - total_traffic_failures) / total_traffic_requests * 100,
                    2) if total_traffic_requests > 0 else 0
            }
        },
        "iterations": results
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    run_fault_tolerance_test()