import time
import requests
import sys
import os
import json
import statistics
from collections import Counter
from concurrent.futures import ThreadPoolExecutor


current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
import config
from drivers.swarm_driver import SwarmDriver


def send_request(_):
    try:
        start = time.time()
        resp = requests.get(config.API_URL, timeout=2)
        latency = time.time() - start
        return {
            "success": resp.status_code == 200,
            "latency": latency,
            "container": resp.json().get("container_id") if resp.status_code == 200 else None
        }
    except:
        return {"success": False, "latency": 0, "container": None}


def test_scalability():
    driver = SwarmDriver(config.STACK_NAME)
    levels = [1, 3, 5]  # Puoi aggiungere 10 se i nodi reggono

    output = {
        "test_name": "scalability_and_lb",
        "results": []
    }

    print("--- Scalability & Load Balancing Test ---")

    for replicas in levels:
        print(f"\n[TEST] Scaling to {replicas} replicas...")
        driver.scale_service(config.SERVICE_NAME, replicas)
        time.sleep(10)  # Wait stabilization

        print(f"[TEST] Generating load (500 reqs)...")
        num_requests = 500
        start_bench = time.time()

        with ThreadPoolExecutor(max_workers=10) as executor:
            data = list(executor.map(send_request, range(num_requests)))

        duration = time.time() - start_bench

        # Analisi Dati
        successful = [d for d in data if d['success']]
        rps = len(successful) / duration
        latencies = [d['latency'] for d in successful]
        avg_lat = statistics.mean(latencies) if latencies else 0

        # Load Balancing Check
        containers = [d['container'] for d in successful if d['container']]
        unique_containers = len(set(containers))
        counts = Counter(containers).values()
        std_dev_balance = statistics.stdev(counts) if len(counts) > 1 else 0

        res = {
            "replicas": replicas,
            "throughput_rps": round(rps, 2),
            "avg_latency_ms": round(avg_lat * 1000, 2),
            "unique_responders": unique_containers,
            "balance_std_dev": round(std_dev_balance, 2)
        }
        output["results"].append(res)

        print(f"-> RPS: {rps:.2f} | Latency: {avg_lat * 1000:.2f}ms | Unique Containers: {unique_containers}")

    # Salva JSON
    with open("results_scalability.json", "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    test_scalability()