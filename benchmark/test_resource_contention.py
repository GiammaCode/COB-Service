"""
Test: Resource Contention
Taxonomy Category: Resource Management -> Oversubscription

Measures how Swarm behaves when resources are constrained:
1. What happens when containers exceed memory limits?
2. How does CPU throttling affect performance?
3. Does Swarm evict containers properly?

This test creates containers with resource limits and pushes them to their limits.
"""

import subprocess
import time
import json
import sys
import threading
import requests

# Configuration
STACK_NAME = "cob-service"
SERVICE_NAME = f"{STACK_NAME}_backend"
REGISTRY = "192.168.15.9:5000"
TEST_SERVICE_PREFIX = "contention-test"
TEST_IMAGE = f"{REGISTRY}/cob-service-backend:latest"
NETWORK_NAME = "cob-service_cob-service"
BACKEND_URL = "http://localhost:5001/"
TIMEOUT_SECONDS = 60


def log(message):
    """Output to stderr to not interfere with final JSON"""
    print(f"[CONTENTION] {message}", file=sys.stderr)


def cleanup_test_services():
    """Remove all test services"""
    cmd = f"docker service ls --filter name={TEST_SERVICE_PREFIX} -q"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    for sid in result.stdout.strip().split('\n'):
        if sid:
            subprocess.run(f"docker service rm {sid}", shell=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)


def get_service_resource_config():
    """Get current resource configuration of the backend service"""
    cmd = f"docker service inspect {SERVICE_NAME} --format '{{{{json .Spec.TaskTemplate.Resources}}}}'"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.stdout.strip():
            return json.loads(result.stdout.strip())
    except:
        pass
    return None


def get_container_stats(container_id):
    """Get resource usage stats for a container"""
    cmd = f"docker stats {container_id} --no-stream --format '{{{{json .}}}}'"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        if result.stdout.strip():
            return json.loads(result.stdout.strip())
    except:
        pass
    return None


def get_backend_containers():
    """Get list of backend container IDs"""
    cmd = f"docker ps --filter name={STACK_NAME}_backend --format '{{{{.ID}}}}'"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return [c.strip() for c in result.stdout.strip().split('\n') if c.strip()]
    except:
        return []


def measure_baseline_performance():
    """Measure baseline performance of the service"""
    log("Measuring baseline performance...")

    latencies = []
    errors = 0

    for i in range(50):
        try:
            start = time.time()
            resp = requests.get(BACKEND_URL, timeout=5)
            latency = time.time() - start
            if resp.status_code == 200:
                latencies.append(latency)
            else:
                errors += 1
        except:
            errors += 1
        time.sleep(0.05)

    if latencies:
        return {
            "requests": 50,
            "successful": len(latencies),
            "errors": errors,
            "avg_latency_ms": round(sum(latencies) / len(latencies) * 1000, 2),
            "max_latency_ms": round(max(latencies) * 1000, 2)
        }
    return {"error": "No successful requests"}


def create_resource_hungry_service(cpu_limit, memory_limit):
    """Create a service with specific resource limits"""
    service_name = f"{TEST_SERVICE_PREFIX}-hungry"
    cleanup_test_services()

    cmd = f"""docker service create \
        --name {service_name} \
        --replicas 3 \
        --network {NETWORK_NAME} \
        --limit-cpu {cpu_limit} \
        --limit-memory {memory_limit} \
        --reserve-cpu {cpu_limit} \
        --reserve-memory {memory_limit} \
        --quiet \
        {TEST_IMAGE}"""

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0:
        # Wait for services to start
        time.sleep(10)
        return True, service_name
    else:
        return False, result.stderr


def test_cpu_throttling():
    """Test behavior under CPU constraints"""
    log("\n--- Testing CPU Throttling ---")

    result = {
        "test": "cpu_throttling",
        "success": False,
        "baseline": None,
        "under_load": None,
        "throttling_detected": False
    }

    # Get baseline
    result["baseline"] = measure_baseline_performance()

    # Get current container stats
    containers = get_backend_containers()
    if not containers:
        result["error"] = "No containers found"
        return result

    log(f"  Monitoring {len(containers)} containers...")

    # Generate heavy load
    log("  Generating CPU load...")

    stop_load = threading.Event()
    latencies = []
    errors = 0

    def generate_load():
        nonlocal errors
        while not stop_load.is_set():
            try:
                start = time.time()
                resp = requests.get(BACKEND_URL, timeout=5)
                if resp.status_code == 200:
                    latencies.append(time.time() - start)
                else:
                    errors += 1
            except:
                errors += 1
            time.sleep(0.01)

    # Start multiple load threads
    threads = []
    for _ in range(10):
        t = threading.Thread(target=generate_load)
        t.start()
        threads.append(t)

    # Let it run for a while
    time.sleep(15)

    # Collect stats during load
    stats_during_load = []
    for cid in containers[:3]:  # Check first 3 containers
        stats = get_container_stats(cid)
        if stats:
            stats_during_load.append(stats)

    # Stop load
    stop_load.set()
    for t in threads:
        t.join()

    # Analyze results
    if latencies:
        result["under_load"] = {
            "requests": len(latencies) + errors,
            "successful": len(latencies),
            "errors": errors,
            "avg_latency_ms": round(sum(latencies) / len(latencies) * 1000, 2),
            "max_latency_ms": round(max(latencies) * 1000, 2)
        }

        # Check if latency increased significantly (throttling indicator)
        if result["baseline"] and result["baseline"].get("avg_latency_ms"):
            latency_increase = result["under_load"]["avg_latency_ms"] / result["baseline"]["avg_latency_ms"]
            result["latency_increase_factor"] = round(latency_increase, 2)
            result["throttling_detected"] = latency_increase > 2.0

    result["container_stats"] = stats_during_load
    result["success"] = True

    return result


def test_memory_pressure():
    """Test behavior when approaching memory limits"""
    log("\n--- Testing Memory Pressure ---")

    result = {
        "test": "memory_pressure",
        "success": False,
        "service_config": None,
        "observations": []
    }

    # Get resource config
    config = get_service_resource_config()
    result["service_config"] = config

    # Monitor memory usage
    containers = get_backend_containers()
    if not containers:
        result["error"] = "No containers found"
        return result

    log(f"  Monitoring memory on {len(containers)} containers...")

    # Collect memory stats over time
    memory_samples = []
    for _ in range(10):
        sample = {"timestamp": time.time(), "containers": []}
        for cid in containers[:3]:
            stats = get_container_stats(cid)
            if stats:
                sample["containers"].append({
                    "id": cid[:12],
                    "memory": stats.get("MemUsage", "N/A"),
                    "memory_percent": stats.get("MemPerc", "N/A")
                })
        memory_samples.append(sample)
        time.sleep(2)

    result["memory_samples"] = memory_samples
    result["success"] = True

    # Analyze trend
    if memory_samples:
        result["observations"].append(f"Collected {len(memory_samples)} memory samples")

        # Check for containers near limit
        for sample in memory_samples:
            for container in sample.get("containers", []):
                mem_perc = container.get("memory_percent", "0%")
                if isinstance(mem_perc, str) and mem_perc.replace("%", "").replace(".", "").isdigit():
                    perc_val = float(mem_perc.replace("%", ""))
                    if perc_val > 80:
                        result["observations"].append(f"Container {container['id']} near memory limit: {mem_perc}")

    return result


def test_oversubscription_behavior():
    """Test what happens when we try to schedule more than available resources"""
    log("\n--- Testing Oversubscription ---")

    result = {
        "test": "oversubscription",
        "success": False,
        "can_oversubscribe": False,
        "rejection_behavior": None
    }

    # Try to create services that would exceed node capacity
    # Use very high resource requests
    service_name = f"{TEST_SERVICE_PREFIX}-oversub"

    log("  Attempting to schedule resource-heavy service...")

    cmd = f"""docker service create \
        --name {service_name} \
        --replicas 10 \
        --reserve-cpu 2.0 \
        --reserve-memory 2G \
        --quiet \
        {TEST_IMAGE}"""

    start_time = time.time()
    subprocess.run(cmd, shell=True, capture_output=True, text=True)

    # Wait and check status
    time.sleep(10)

    # Check how many actually got scheduled
    cmd = f"docker service ps {service_name} --format '{{{{.CurrentState}}}} {{{{.Error}}}}'"
    ps_result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    states = ps_result.stdout.strip().split('\n') if ps_result.stdout.strip() else []

    running = sum(1 for s in states if 'Running' in s)
    pending = sum(1 for s in states if 'Pending' in s)
    rejected = sum(1 for s in states if 'no suitable node' in s.lower() or 'insufficient' in s.lower())

    result["requested_replicas"] = 10
    result["running"] = running
    result["pending"] = pending
    result["rejected"] = rejected
    result["states"] = states[:5]  # First 5 states

    if rejected > 0:
        result["rejection_behavior"] = "Swarm correctly rejected tasks that couldn't be scheduled"
        result["can_oversubscribe"] = False
    elif pending > 0:
        result["rejection_behavior"] = "Tasks pending - waiting for resources"
        result["can_oversubscribe"] = False
    elif running == 10:
        result["rejection_behavior"] = "All tasks scheduled - resources available or oversubscription allowed"
        result["can_oversubscribe"] = True

    result["success"] = True

    # Cleanup
    subprocess.run(f"docker service rm {service_name}", shell=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return result


def run_resource_contention_test():
    """Run complete resource contention test"""
    log("Starting Resource Contention test")

    # Cleanup any previous test services
    cleanup_test_services()

    results = {
        "cpu_throttling": test_cpu_throttling(),
        "memory_pressure": test_memory_pressure(),
        "oversubscription": test_oversubscription_behavior()
    }

    # Final cleanup
    cleanup_test_services()

    # Build output
    output = {
        "test_name": "resource_contention",
        "category": "resource_management",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "service": SERVICE_NAME,
            "backend_url": BACKEND_URL
        },
        "status": "passed" if all(r.get("success") for r in results.values()) else "partial",
        "tests": results,
        "summary": {
            "cpu_throttling_detected": results["cpu_throttling"].get("throttling_detected", False),
            "memory_pressure_observed": len(results["memory_pressure"].get("observations", [])) > 1,
            "oversubscription_behavior": results["oversubscription"].get("rejection_behavior")
        }
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    run_resource_contention_test()