"""
Test: Scalability
Taxonomy Category: System Objectives -> Scalability

Measures how the system scales horizontally:
1. Throughput at different replica counts
2. Latency distribution under load
3. Scaling efficiency (throughput gained / resources added)
4. Time to scale up/down

This test finds the saturation point and calculates scaling efficiency.
"""

import subprocess
import time
import json
import sys
import statistics
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
STACK_NAME = "cob-service"
SERVICE_NAME = f"{STACK_NAME}_backend"
BACKEND_URL = "http://localhost:5001/"
REPLICA_LEVELS = [1, 2, 3, 5]  # Different replica counts to test
REQUESTS_PER_LEVEL = 200
CONCURRENT_WORKERS = 20
WARMUP_REQUESTS = 20
SCALE_TIMEOUT = 120


def log(message):
    """Output to stderr to not interfere with final JSON"""
    print(f"[SCALE] {message}", file=sys.stderr)


def get_current_replicas():
    """Get current replica count for the service"""
    cmd = f"docker service ls --filter name={SERVICE_NAME} --format '{{{{.Replicas}}}}'"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        output = result.stdout.strip()
        if '/' in output:
            current, desired = output.split('/')
            return int(current), int(desired)
        return 0, 0
    except:
        return 0, 0


def scale_service(target_replicas):
    """Scale service to target replicas and wait for completion"""
    log(f"  Scaling to {target_replicas} replicas...")

    cmd = f"docker service scale {SERVICE_NAME}={target_replicas}"
    start_time = time.time()

    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Wait for scaling to complete
    while time.time() - start_time < SCALE_TIMEOUT:
        current, desired = get_current_replicas()
        if current == desired == target_replicas:
            scale_time = time.time() - start_time
            log(f"  Scaled to {target_replicas} in {scale_time:.2f}s")
            return True, scale_time
        time.sleep(1)

    return False, SCALE_TIMEOUT


def send_request(request_id):
    """Send a single request and measure latency"""
    try:
        start = time.time()
        resp = requests.get(BACKEND_URL, timeout=10)
        latency = time.time() - start

        if resp.status_code == 200:
            data = resp.json()
            container_id = data.get('container_id', 'unknown')
            return {
                "success": True,
                "latency": latency,
                "container_id": container_id
            }
        else:
            return {
                "success": False,
                "latency": latency,
                "error": f"HTTP {resp.status_code}"
            }
    except Exception as e:
        return {
            "success": False,
            "latency": 0,
            "error": str(e)
        }


def run_load_test(num_requests, num_workers):
    """Run load test and collect metrics"""
    results = []

    # Warmup
    log(f"  Warmup ({WARMUP_REQUESTS} requests)...")
    with ThreadPoolExecutor(max_workers=5) as executor:
        list(executor.map(send_request, range(WARMUP_REQUESTS)))

    time.sleep(1)

    # Actual test
    log(f"  Running {num_requests} requests with {num_workers} workers...")
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(send_request, i) for i in range(num_requests)]
        for future in as_completed(futures):
            results.append(future.result())

    duration = time.time() - start_time

    # Calculate metrics
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    latencies = [r["latency"] for r in successful]

    # Container distribution
    containers = {}
    for r in successful:
        cid = r.get("container_id", "unknown")
        containers[cid] = containers.get(cid, 0) + 1

    metrics = {
        "total_requests": num_requests,
        "successful": len(successful),
        "failed": len(failed),
        "success_rate": round(len(successful) / num_requests * 100, 2),
        "duration_seconds": round(duration, 4),
        "throughput_rps": round(len(successful) / duration, 2),
        "latency": {
            "min": round(min(latencies) * 1000, 2) if latencies else None,
            "max": round(max(latencies) * 1000, 2) if latencies else None,
            "mean": round(statistics.mean(latencies) * 1000, 2) if latencies else None,
            "median": round(statistics.median(latencies) * 1000, 2) if latencies else None,
            "p95": round(sorted(latencies)[int(len(latencies) * 0.95)] * 1000, 2) if len(latencies) > 20 else None,
            "p99": round(sorted(latencies)[int(len(latencies) * 0.99)] * 1000, 2) if len(latencies) > 100 else None,
            "stdev": round(statistics.stdev(latencies) * 1000, 2) if len(latencies) > 1 else 0
        },
        "container_distribution": containers
    }

    return metrics


def test_replica_level(replicas):
    """Test performance at a specific replica count"""
    log(f"\n--- Testing with {replicas} replica(s) ---")

    result = {
        "replicas": replicas,
        "scale_success": False,
        "scale_time": None,
        "load_test": None
    }

    # Scale to target
    success, scale_time = scale_service(replicas)
    result["scale_success"] = success
    result["scale_time"] = round(scale_time, 4)

    if not success:
        result["error"] = "Failed to scale"
        return result

    # Wait for containers to stabilize
    time.sleep(3)

    # Run load test
    result["load_test"] = run_load_test(REQUESTS_PER_LEVEL, CONCURRENT_WORKERS)

    log(f"  Throughput: {result['load_test']['throughput_rps']} rps")
    log(f"  Latency (mean): {result['load_test']['latency']['mean']} ms")
    log(f"  Success rate: {result['load_test']['success_rate']}%")

    return result


def calculate_scaling_efficiency(results):
    """Calculate how efficiently the system scales"""
    analysis = {
        "throughput_scaling": [],
        "latency_impact": [],
        "efficiency_ratio": None,
        "saturation_point": None,
        "interpretation": ""
    }

    baseline_throughput = None
    baseline_latency = None
    baseline_replicas = None

    for r in results:
        if not r.get("load_test"):
            continue

        replicas = r["replicas"]
        throughput = r["load_test"]["throughput_rps"]
        latency = r["load_test"]["latency"]["mean"]

        if baseline_throughput is None:
            baseline_throughput = throughput
            baseline_latency = latency
            baseline_replicas = replicas

        # Calculate relative improvement
        throughput_factor = throughput / baseline_throughput if baseline_throughput else 0
        replica_factor = replicas / baseline_replicas if baseline_replicas else 1
        efficiency = throughput_factor / replica_factor if replica_factor else 0

        analysis["throughput_scaling"].append({
            "replicas": replicas,
            "throughput_rps": throughput,
            "throughput_factor": round(throughput_factor, 2),
            "efficiency": round(efficiency, 2)
        })

        analysis["latency_impact"].append({
            "replicas": replicas,
            "latency_ms": latency,
            "latency_change": round((latency - baseline_latency) / baseline_latency * 100, 2) if baseline_latency else 0
        })

    # Find saturation point (where efficiency drops below 0.5)
    for entry in analysis["throughput_scaling"]:
        if entry["efficiency"] < 0.5 and entry["replicas"] > 1:
            analysis["saturation_point"] = entry["replicas"]
            break

    # Calculate overall efficiency
    if len(analysis["throughput_scaling"]) >= 2:
        first = analysis["throughput_scaling"][0]
        last = analysis["throughput_scaling"][-1]

        total_throughput_gain = last["throughput_factor"]
        total_replica_increase = last["replicas"] / first["replicas"]

        analysis["efficiency_ratio"] = round(total_throughput_gain / total_replica_increase, 2)

        if analysis["efficiency_ratio"] >= 0.8:
            analysis["interpretation"] = "Excellent scaling: near-linear throughput increase with replicas"
        elif analysis["efficiency_ratio"] >= 0.5:
            analysis["interpretation"] = "Good scaling: reasonable throughput gains with additional replicas"
        elif analysis["efficiency_ratio"] >= 0.3:
            analysis[
                "interpretation"] = "Moderate scaling: diminishing returns on additional replicas (possible bottleneck)"
        else:
            analysis[
                "interpretation"] = "Poor scaling: adding replicas provides minimal benefit (likely bottleneck in DB or network)"

    return analysis


def run_scalability_test():
    """Run complete scalability test"""
    log("Starting Scalability test")
    log(f"Service: {SERVICE_NAME}")
    log(f"Replica levels: {REPLICA_LEVELS}")
    log(f"Requests per level: {REQUESTS_PER_LEVEL}")

    # Store initial replica count to restore later
    initial_current, initial_desired = get_current_replicas()
    log(f"Initial replicas: {initial_current}/{initial_desired}")

    results = []

    for replicas in REPLICA_LEVELS:
        result = test_replica_level(replicas)
        results.append(result)
        time.sleep(3)  # Pause between levels

    # Calculate scaling efficiency
    scaling_analysis = calculate_scaling_efficiency(results)

    # Restore initial replica count
    log(f"\nRestoring to {initial_desired} replicas...")
    scale_service(initial_desired)

    # Build output
    output = {
        "test_name": "scalability",
        "category": "system_objectives",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "service": SERVICE_NAME,
            "replica_levels": REPLICA_LEVELS,
            "requests_per_level": REQUESTS_PER_LEVEL,
            "concurrent_workers": CONCURRENT_WORKERS
        },
        "status": "passed" if all(r.get("scale_success") for r in results) else "partial",
        "results_by_replicas": results,
        "scaling_analysis": scaling_analysis,
        "summary": {
            "max_throughput": max(r["load_test"]["throughput_rps"] for r in results if r.get("load_test")),
            "optimal_replicas":
                max(results, key=lambda r: r["load_test"]["throughput_rps"] if r.get("load_test") else 0)["replicas"],
            "scaling_efficiency": scaling_analysis.get("efficiency_ratio")
        }
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    run_scalability_test()