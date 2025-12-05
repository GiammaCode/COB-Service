"""
Test: Load Balancing
Taxonomy Category: System Objectives -> High Availability / High Throughput

Measures Swarm's ingress load balancing:
1. Distribution fairness across replicas
2. Latency consistency
3. Behavior under increasing load
4. Session affinity (if any)

This test verifies that traffic is properly distributed across all backend replicas.
"""

import subprocess
import time
import json
import sys
import statistics
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict

# Configuration
STACK_NAME = "cob-service"
SERVICE_NAME = f"{STACK_NAME}_backend"
BACKEND_URL = "http://localhost:5001/"
WARMUP_REQUESTS = 50
TEST_REQUESTS = 500
CONCURRENT_WORKERS = 20


def log(message):
    """Output to stderr to not interfere with final JSON"""
    print(f"[LB] {message}", file=sys.stderr)


def get_expected_replicas():
    """Get expected number of replicas from service config"""
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


def send_request(request_id):
    """Send a request and capture response details"""
    try:
        start = time.time()
        resp = requests.get(BACKEND_URL, timeout=10)
        latency = time.time() - start

        if resp.status_code == 200:
            data = resp.json()
            return {
                "success": True,
                "request_id": request_id,
                "container_id": data.get("container_id", "unknown"),
                "latency": latency,
                "timestamp": start
            }
        else:
            return {
                "success": False,
                "request_id": request_id,
                "error": f"HTTP {resp.status_code}",
                "latency": latency
            }
    except Exception as e:
        return {
            "success": False,
            "request_id": request_id,
            "error": str(e),
            "latency": 0
        }


def run_warmup():
    """Run warmup requests to prime connections"""
    log(f"Running {WARMUP_REQUESTS} warmup requests...")

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(send_request, i) for i in range(WARMUP_REQUESTS)]
        results = [f.result() for f in as_completed(futures)]

    successful = sum(1 for r in results if r.get("success"))
    log(f"  Warmup complete: {successful}/{WARMUP_REQUESTS} successful")

    return successful > WARMUP_REQUESTS * 0.8


def run_load_test():
    """Run main load balancing test"""
    log(f"Running {TEST_REQUESTS} test requests with {CONCURRENT_WORKERS} workers...")

    results = []
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = [executor.submit(send_request, i) for i in range(TEST_REQUESTS)]
        for future in as_completed(futures):
            results.append(future.result())

    duration = time.time() - start_time

    return results, duration


def analyze_distribution(results, expected_replicas):
    """Analyze how well requests were distributed"""
    successful = [r for r in results if r.get("success")]

    if not successful:
        return {"error": "No successful requests"}

    # Count requests per container
    container_counts = Counter(r["container_id"] for r in successful)

    # Calculate fairness metrics
    counts = list(container_counts.values())
    total = sum(counts)
    num_containers = len(counts)

    # Expected count per container (perfect balance)
    expected_per_container = total / num_containers if num_containers > 0 else 0

    # Standard deviation of distribution
    stdev = statistics.stdev(counts) if len(counts) > 1 else 0

    # Coefficient of variation (lower is more balanced)
    cv = stdev / statistics.mean(counts) if counts else 0

    # Min/max ratio (closer to 1 is more balanced)
    min_max_ratio = min(counts) / max(counts) if counts and max(counts) > 0 else 0

    # Calculate fairness index (Jain's fairness index)
    # F = (sum(xi))^2 / (n * sum(xi^2))
    # F = 1 means perfectly fair, F = 1/n means completely unfair
    sum_counts = sum(counts)
    sum_counts_sq = sum(c * c for c in counts)
    jains_fairness = (sum_counts * sum_counts) / (num_containers * sum_counts_sq) if sum_counts_sq > 0 else 0

    return {
        "containers_responding": num_containers,
        "expected_replicas": expected_replicas,
        "all_replicas_responding": num_containers >= expected_replicas,
        "distribution": dict(container_counts),
        "requests_per_container": {
            "min": min(counts),
            "max": max(counts),
            "mean": round(statistics.mean(counts), 2),
            "stdev": round(stdev, 2),
            "expected": round(expected_per_container, 2)
        },
        "fairness_metrics": {
            "coefficient_of_variation": round(cv, 4),
            "min_max_ratio": round(min_max_ratio, 4),
            "jains_fairness_index": round(jains_fairness, 4),
            "is_balanced": cv < 0.2 and min_max_ratio > 0.7
        }
    }


def analyze_latency(results):
    """Analyze latency characteristics"""
    successful = [r for r in results if r.get("success")]

    if not successful:
        return {"error": "No successful requests"}

    latencies = [r["latency"] for r in successful]

    # Per-container latency
    container_latencies = defaultdict(list)
    for r in successful:
        container_latencies[r["container_id"]].append(r["latency"])

    per_container = {}
    for cid, lats in container_latencies.items():
        per_container[cid] = {
            "count": len(lats),
            "mean_ms": round(statistics.mean(lats) * 1000, 2),
            "stdev_ms": round(statistics.stdev(lats) * 1000, 2) if len(lats) > 1 else 0
        }

    # Check if any container has significantly higher latency
    means = [v["mean_ms"] for v in per_container.values()]
    overall_mean = statistics.mean(means) if means else 0
    outliers = [cid for cid, v in per_container.items() if v["mean_ms"] > overall_mean * 1.5]

    sorted_latencies = sorted(latencies)

    return {
        "overall": {
            "min_ms": round(min(latencies) * 1000, 2),
            "max_ms": round(max(latencies) * 1000, 2),
            "mean_ms": round(statistics.mean(latencies) * 1000, 2),
            "median_ms": round(statistics.median(latencies) * 1000, 2),
            "p95_ms": round(sorted_latencies[int(len(sorted_latencies) * 0.95)] * 1000, 2),
            "p99_ms": round(sorted_latencies[int(len(sorted_latencies) * 0.99)] * 1000, 2),
            "stdev_ms": round(statistics.stdev(latencies) * 1000, 2) if len(latencies) > 1 else 0
        },
        "per_container": per_container,
        "latency_outlier_containers": outliers,
        "consistent_latency": len(outliers) == 0
    }


def test_sequential_affinity():
    """Test if sequential requests from same client go to same container"""
    log("Testing session affinity (sequential requests)...")

    results = []
    for i in range(20):
        result = send_request(i)
        results.append(result)
        time.sleep(0.1)

    successful = [r for r in results if r.get("success")]
    if not successful:
        return {"error": "No successful requests"}

    containers = [r["container_id"] for r in successful]
    unique = len(set(containers))

    # Check for patterns
    same_container_streak = 1
    max_streak = 1
    for i in range(1, len(containers)):
        if containers[i] == containers[i - 1]:
            same_container_streak += 1
            max_streak = max(max_streak, same_container_streak)
        else:
            same_container_streak = 1

    return {
        "total_requests": len(successful),
        "unique_containers": unique,
        "max_same_container_streak": max_streak,
        "has_affinity": max_streak > 5,  # If >5 consecutive to same container, might have affinity
        "distribution": dict(Counter(containers))
    }


def run_load_balancing_test():
    """Run complete load balancing test"""
    log("Starting Load Balancing test")
    log(f"Service: {SERVICE_NAME}")

    # Get expected replicas
    current, expected = get_expected_replicas()
    log(f"Replicas: {current}/{expected}")

    if current == 0:
        log("ERROR: No replicas running")
        print(json.dumps({"error": "No replicas running", "status": "failed"}))
        return

    # Warmup
    if not run_warmup():
        log("WARNING: Warmup had issues, continuing anyway...")

    time.sleep(2)

    # Main load test
    results, duration = run_load_test()

    # Analyze results
    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]

    log(f"Results: {len(successful)}/{TEST_REQUESTS} successful in {duration:.2f}s")

    # Distribution analysis
    distribution = analyze_distribution(results, expected)

    # Latency analysis
    latency = analyze_latency(results)

    # Affinity test
    affinity = test_sequential_affinity()

    # Determine status
    status = "passed"
    issues = []

    if not distribution.get("all_replicas_responding"):
        issues.append(f"Only {distribution['containers_responding']}/{expected} replicas responding")
        status = "partial"

    if not distribution.get("fairness_metrics", {}).get("is_balanced"):
        issues.append("Load distribution is unbalanced")
        status = "partial"

    if len(failed) > TEST_REQUESTS * 0.01:  # More than 1% failures
        issues.append(f"{len(failed)} requests failed ({len(failed) / TEST_REQUESTS * 100:.1f}%)")
        status = "failed" if len(failed) > TEST_REQUESTS * 0.05 else "partial"

    output = {
        "test_name": "load_balancing",
        "category": "system_objectives",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "service": SERVICE_NAME,
            "expected_replicas": expected,
            "test_requests": TEST_REQUESTS,
            "concurrent_workers": CONCURRENT_WORKERS
        },
        "status": status,
        "summary": {
            "total_requests": TEST_REQUESTS,
            "successful": len(successful),
            "failed": len(failed),
            "success_rate": round(len(successful) / TEST_REQUESTS * 100, 2),
            "throughput_rps": round(len(successful) / duration, 2),
            "duration_seconds": round(duration, 2),
            "replicas_responding": distribution.get("containers_responding", 0),
            "load_balanced": distribution.get("fairness_metrics", {}).get("is_balanced", False)
        },
        "distribution_analysis": distribution,
        "latency_analysis": latency,
        "affinity_test": affinity,
        "issues": issues if issues else None,
        "interpretation": generate_interpretation(distribution, latency, affinity)
    }

    print(json.dumps(output, indent=2))


def generate_interpretation(distribution, latency, affinity):
    """Generate human-readable interpretation"""
    points = []

    # Distribution
    fairness = distribution.get("fairness_metrics", {})
    if fairness.get("jains_fairness_index", 0) > 0.95:
        points.append("Load is evenly distributed across all replicas (excellent)")
    elif fairness.get("jains_fairness_index", 0) > 0.8:
        points.append("Load distribution is reasonably balanced")
    else:
        points.append("Load distribution is uneven - some replicas receive significantly more traffic")

    # Latency
    if latency.get("consistent_latency"):
        points.append("Latency is consistent across all containers")
    else:
        outliers = latency.get("latency_outlier_containers", [])
        points.append(f"Containers {outliers} show higher latency than average")

    # Affinity
    if affinity.get("has_affinity"):
        points.append("Possible session affinity detected - sequential requests tend to hit same container")
    else:
        points.append("No session affinity - Swarm uses round-robin or random distribution")

    return points


if __name__ == "__main__":
    run_load_balancing_test()