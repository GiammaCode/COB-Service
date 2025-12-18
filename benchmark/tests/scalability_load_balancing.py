import time
import subprocess
import sys
import os
import json
import csv

# Setup path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

import config
#from drivers.swarm_driver import SwarmDriver
from drivers.k8s_driver import K8sDriver

def run_locust_test(replicas, duration=30, users=50, spawn_rate=10):
    """
    Run locust test e return CSV raw data
    """
    print(f"[TEST] Starting Load Test with Locust (Replicas: {replicas})...")
    results_dir = os.path.join(parent_dir, "results")
    csv_dir = os.path.join(results_dir, "csv_raw")
    os.makedirs(csv_dir, exist_ok=True)
    csv_prefix = os.path.join(csv_dir, f"locust_rep_{replicas}")

    host_url = config.API_URL

    # Comando Locust
    cmd = [
        "locust",
        "-f", os.path.join(parent_dir, "locustfile.py"),
        "--headless",
        "-u", str(users),
        "-r", str(spawn_rate),
        "-t", f"{duration}s",
        "--host", host_url,
        "--csv", csv_prefix
    ]

    try:
        subprocess.run(cmd, check=False, cwd=parent_dir, stdout=subprocess.DEVNULL)
    except Exception as e:
        print(f"[CRITICAL ERROR] Locust failed to start: {e}")
        return None

    stats_file = f"{csv_prefix}_stats.csv"
    result = {}

    if os.path.exists(stats_file):
        try:
            with open(stats_file, mode='r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row['Name'] == 'Aggregated':
                        result = {
                            "replicas": replicas,
                            "requests": int(row['Request Count']),
                            "failures": int(row['Failure Count']),
                            "rps": float(row['Requests/s']),
                            "avg_latency": float(row['Average Response Time']),
                            "p95_latency": float(row['95%']),
                            "p99_latency": float(row['99%'])
                        }
        except Exception as e:
            print(f"[ERROR] Reading CSV: {e}")
            return None
        print(f"-> CSV saved to: {stats_file}")
    else:
        print(f"[ERROR] Stats file not found at: {stats_file}")
        return None

    return result


def test_scalability():
    #driver = SwarmDriver(config.STACK_NAME)
    driver = K8sDriver()

    levels = [1, 3, 5]

    output = {
        "test_name": "scalability_stress_test",
        "description": "Stress test using Locust to find saturation point",
        "results": []
    }

    print("--- Scalability & Load Balancing Stress Test (Locust) ---")

    # Reset iniziale per pulizia
    driver.reset_cluster()

    for replicas in levels:
        service_name = "backend"
        driver.scale_service(service_name, replicas)

        print(f"[TEST] Waiting for {replicas} replicas to be ready...")
        time.sleep(2)
        max_wait = 120
        start_wait = time.time()
        while True:
            current, desired = driver.get_replica_count(service_name)
            if current == replicas and desired == replicas:
                print(f"[TEST] Convergence reached: {current}/{replicas}")
                break
            if time.time() - start_wait > max_wait:
                print(f"[WARNING] Timeout waiting for convergence ({current}/{replicas}).")
                break
            time.sleep(2)

        print("[TEST] Stabilizing (5s)...")
        time.sleep(5)

        data = run_locust_test(replicas, duration=20, users=500, spawn_rate=50)

        if data:
            print(f"-> Result: {data['rps']} RPS | {data['avg_latency']}ms avg | Failures: {data['failures']}")
            output["results"].append(data)
        else:
            print(f"[ERROR] No data collected for {replicas} replicas")

    os.makedirs("results", exist_ok=True)
    outfile = "results/scalability_load_balancing.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n[TEST] Completed. JSON saved to {outfile}")
    print(f"[TEST] Raw CSVs saved in results/csv_raw/")


if __name__ == "__main__":
    test_scalability()