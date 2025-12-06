import time
import requests
import statistics
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from swarm_driver import SwarmDriver


def send_request(_):
    try:
        start = time.time()
        resp = requests.get("http://localhost:5001/", timeout=2)
        latency = time.time() - start
        return {
            "success": resp.status_code == 200,
            "latency": latency,
            "container": resp.json().get("container_id") if resp.status_code == 200 else None
        }
    except:
        return {"success": False, "latency": 0, "container": None}


def test_scalability():
    driver = SwarmDriver()
    levels = [1, 3, 5]
    results = {}

    print("--- Start Scalability Test ---")

    for replicas in levels:
        print(f"Testing {replicas} replicas...")
        driver.scale_service("backend", replicas)
        time.sleep(5 + replicas)  # Wait stabilization

        # Load Test
        num_requests = 500
        start_bench = time.time()

        with ThreadPoolExecutor(max_workers=10) as executor:
            data = list(executor.map(send_request, range(num_requests)))

        duration = time.time() - start_bench

        # Analyze
        successful = [d for d in data if d['success']]
        rps = len(successful) / duration
        latencies = [d['latency'] for d in successful]
        avg_lat = statistics.mean(latencies) if latencies else 0

        # Load Balancing Check
        containers = [d['container'] for d in successful if d['container']]
        counts = Counter(containers).values()
        std_dev_balance = statistics.stdev(counts) if len(counts) > 1 else 0

        results[replicas] = {
            "rps": rps,
            "latency": avg_lat,
            "balance_std_dev": std_dev_balance
        }
        print(f"-> {replicas} Replicas: {rps:.2f} RPS, {avg_lat * 1000:.2f}ms Latency")

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    test_scalability()