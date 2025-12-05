"""
Test: Rolling Update
Taxonomy Category: Application Model -> Rescheduling

Measures zero-downtime deployment capability:
1. Error rate during update
2. Latency impact during update
3. Time in mixed state (old + new versions)
4. Update completion time

This test performs a real update while generating traffic.
"""

import subprocess
import time
import json
import sys
import threading
import requests
from collections import defaultdict

# Configuration
STACK_NAME = "cob-service"
SERVICE_NAME = f"{STACK_NAME}_backend"
BACKEND_URL = "http://localhost:5001/"
TIMEOUT_SECONDS = 120
TRAFFIC_INTERVAL = 0.05  # 20 requests/second


def log(message):
    """Output to stderr to not interfere with final JSON"""
    print(f"[UPDATE] {message}", file=sys.stderr)


def get_service_info():
    """Get current service info including update status"""
    info = {
        "replicas": None,
        "image": None,
        "update_state": None
    }

    try:
        # Get replicas
        cmd = f"docker service ls --filter name={SERVICE_NAME} --format '{{{{.Replicas}}}}'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        info["replicas"] = result.stdout.strip()

        # Get image
        cmd = f"docker service inspect {SERVICE_NAME} --format '{{{{.Spec.TaskTemplate.ContainerSpec.Image}}}}'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        info["image"] = result.stdout.strip()

        # Get update state
        cmd = f"docker service inspect {SERVICE_NAME} --format '{{{{.UpdateStatus.State}}}}'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        info["update_state"] = result.stdout.strip()

    except Exception as e:
        info["error"] = str(e)

    return info


def get_container_versions():
    """Get list of container IDs currently serving requests"""
    cmd = f"docker service ps {SERVICE_NAME} --filter 'desired-state=running' --format '{{{{.ID}}}} {{{{.CurrentState}}}}'"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        containers = []
        for line in result.stdout.strip().split('\n'):
            if line and 'Running' in line:
                parts = line.split()
                containers.append(parts[0][:8])
        return containers
    except:
        return []


class UpdateTrafficMonitor:
    """Monitor traffic during update process"""

    def __init__(self, url):
        self.url = url
        self.running = False
        self.lock = threading.Lock()

        # Metrics
        self.total_requests = 0
        self.successful = 0
        self.failed = 0
        self.latencies = []
        self.errors = []
        self.containers_seen = defaultdict(int)

        # Time series data
        self.time_series = []
        self.start_time = None

    def send_request(self):
        """Send single request and record metrics"""
        try:
            start = time.time()
            resp = requests.get(self.url, timeout=5)
            latency = time.time() - start

            with self.lock:
                self.total_requests += 1
                elapsed = time.time() - self.start_time if self.start_time else 0

                if resp.status_code == 200:
                    self.successful += 1
                    self.latencies.append(latency)

                    try:
                        data = resp.json()
                        container_id = data.get('container_id', 'unknown')
                        self.containers_seen[container_id] += 1
                    except:
                        pass

                    self.time_series.append({
                        "time": round(elapsed, 2),
                        "success": True,
                        "latency_ms": round(latency * 1000, 2)
                    })
                else:
                    self.failed += 1
                    self.errors.append({
                        "time": round(elapsed, 2),
                        "status": resp.status_code
                    })
                    self.time_series.append({
                        "time": round(elapsed, 2),
                        "success": False,
                        "error": f"HTTP {resp.status_code}"
                    })

        except Exception as e:
            with self.lock:
                self.total_requests += 1
                self.failed += 1
                elapsed = time.time() - self.start_time if self.start_time else 0
                self.errors.append({
                    "time": round(elapsed, 2),
                    "error": str(e)
                })
                self.time_series.append({
                    "time": round(elapsed, 2),
                    "success": False,
                    "error": str(e)[:50]
                })

    def run(self):
        """Generate continuous traffic"""
        self.running = True
        self.start_time = time.time()

        while self.running:
            self.send_request()
            time.sleep(TRAFFIC_INTERVAL)

    def stop(self):
        self.running = False

    def get_metrics(self):
        with self.lock:
            avg_latency = sum(self.latencies) / len(self.latencies) if self.latencies else 0

            # Find error windows (consecutive errors)
            error_windows = []
            current_window = None

            for entry in self.time_series:
                if not entry.get("success"):
                    if current_window is None:
                        current_window = {"start": entry["time"], "count": 1}
                    else:
                        current_window["count"] += 1
                else:
                    if current_window is not None:
                        current_window["end"] = entry["time"]
                        current_window["duration"] = round(current_window["end"] - current_window["start"], 2)
                        error_windows.append(current_window)
                        current_window = None

            return {
                "total_requests": self.total_requests,
                "successful": self.successful,
                "failed": self.failed,
                "success_rate": round(self.successful / self.total_requests * 100, 2) if self.total_requests > 0 else 0,
                "error_rate": round(self.failed / self.total_requests * 100, 2) if self.total_requests > 0 else 0,
                "avg_latency_ms": round(avg_latency * 1000, 2),
                "max_latency_ms": round(max(self.latencies) * 1000, 2) if self.latencies else 0,
                "containers_seen": dict(self.containers_seen),
                "error_windows": error_windows,
                "total_error_duration": sum(w.get("duration", 0) for w in error_windows)
            }


def perform_rolling_update():
    """Trigger a rolling update using --force"""
    log("  Triggering rolling update...")

    cmd = f"docker service update --force {SERVICE_NAME}"
    start_time = time.time()

    # Start update (non-blocking)
    subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return start_time


def wait_for_update_complete(start_time, timeout):
    """Wait for update to complete and track state changes"""
    states = []
    last_state = None

    while time.time() - start_time < timeout:
        info = get_service_info()
        current_state = info.get("update_state")

        if current_state != last_state:
            states.append({
                "time": round(time.time() - start_time, 2),
                "state": current_state,
                "replicas": info.get("replicas")
            })
            last_state = current_state
            log(f"  Update state: {current_state} (replicas: {info.get('replicas')})")

        if current_state == "completed":
            return True, time.time() - start_time, states
        elif current_state in ["paused", "rollback_completed"]:
            return False, time.time() - start_time, states

        time.sleep(0.5)

    return False, timeout, states


def run_single_update_test(iteration):
    """Run a single rolling update test"""
    log(f"\n--- Update Test {iteration} ---")

    result = {
        "iteration": iteration,
        "success": False,
        "update_time": None,
        "traffic_metrics": None,
        "state_transitions": None,
        "zero_downtime": False
    }

    # Get initial state
    initial_info = get_service_info()
    initial_containers = get_container_versions()
    log(f"  Initial state: {initial_info['replicas']} replicas")
    log(f"  Initial containers: {initial_containers}")

    # Start traffic monitor
    monitor = UpdateTrafficMonitor(BACKEND_URL)
    traffic_thread = threading.Thread(target=monitor.run)
    traffic_thread.start()

    # Wait for traffic to stabilize
    time.sleep(3)

    # Trigger update
    update_start = perform_rolling_update()

    # Wait for completion
    success, duration, states = wait_for_update_complete(update_start, TIMEOUT_SECONDS)

    # Stop traffic
    time.sleep(2)  # Extra time to catch post-update issues
    monitor.stop()
    traffic_thread.join()

    # Get final state
    final_containers = get_container_versions()

    # Collect metrics
    traffic_metrics = monitor.get_metrics()

    result["success"] = success
    result["update_time"] = round(duration, 2)
    result["traffic_metrics"] = traffic_metrics
    result["state_transitions"] = states
    result["initial_containers"] = initial_containers
    result["final_containers"] = final_containers
    result["containers_replaced"] = len(set(initial_containers) - set(final_containers))

    # Determine if zero-downtime
    result["zero_downtime"] = traffic_metrics["failed"] == 0

    # Criteria for success
    result["meets_sla"] = traffic_metrics["error_rate"] < 1.0  # Less than 1% errors

    log(f"  Update completed in {duration:.2f}s")
    log(f"  Traffic: {traffic_metrics['success_rate']}% success rate")
    log(f"  Zero downtime: {result['zero_downtime']}")

    return result


def run_rolling_update_test():
    """Run complete rolling update test"""
    log("Starting Rolling Update test")
    log(f"Service: {SERVICE_NAME}")

    # Verify service exists
    info = get_service_info()
    if not info.get("replicas"):
        log("ERROR: Service not found")
        print(json.dumps({"error": "Service not found", "status": "failed"}))
        return

    log(f"Current state: {info}")

    # Run multiple iterations
    iterations = 3
    results = []

    for i in range(iterations):
        result = run_single_update_test(i + 1)
        results.append(result)

        # Wait between iterations
        time.sleep(10)

    # Aggregate results
    successful = [r for r in results if r.get("success")]
    zero_downtime = [r for r in results if r.get("zero_downtime")]
    meets_sla = [r for r in results if r.get("meets_sla")]

    update_times = [r["update_time"] for r in successful if r.get("update_time")]
    error_rates = [r["traffic_metrics"]["error_rate"] for r in results if r.get("traffic_metrics")]

    output = {
        "test_name": "rolling_update",
        "category": "application_model",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "service": SERVICE_NAME,
            "iterations": iterations,
            "traffic_rate": f"{1 / TRAFFIC_INTERVAL:.0f} req/s"
        },
        "status": "passed" if len(meets_sla) == iterations else ("partial" if meets_sla else "failed"),
        "summary": {
            "successful_updates": len(successful),
            "zero_downtime_updates": len(zero_downtime),
            "meets_sla_updates": len(meets_sla),
            "avg_update_time": round(sum(update_times) / len(update_times), 2) if update_times else None,
            "avg_error_rate": round(sum(error_rates) / len(error_rates), 2) if error_rates else None
        },
        "iterations": results,
        "analysis": {
            "update_strategy": "start-first (from docker-stack.yml)",
            "zero_downtime_achieved": len(zero_downtime) == iterations,
            "recommendation": generate_recommendation(results)
        }
    }

    print(json.dumps(output, indent=2))


def generate_recommendation(results):
    """Generate recommendations based on results"""
    zero_dt = sum(1 for r in results if r.get("zero_downtime"))
    total = len(results)

    if zero_dt == total:
        return "Excellent: All updates achieved zero downtime"
    elif zero_dt > 0:
        error_rates = [r["traffic_metrics"]["error_rate"] for r in results if r.get("traffic_metrics")]
        avg_error = sum(error_rates) / len(error_rates) if error_rates else 0
        return f"Partial success: {zero_dt}/{total} zero-downtime. Avg error rate: {avg_error:.2f}%. Consider increasing replica count or adjusting update delay."
    else:
        return "Issues detected: No zero-downtime updates. Review health checks and update configuration."


if __name__ == "__main__":
    run_rolling_update_test()