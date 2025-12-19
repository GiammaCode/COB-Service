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
from drivers.swarm_driver import SwarmDriver


def run_locust_test(replicas, duration=30, users=50, spawn_rate=10):
    """
    Runs Locust in headless mode and returns statistics.
    Saves CSVs in results/csv_raw without deleting them.
    """
    print(f"[TEST] Starting Load Test with Locust (Replicas: {replicas})...")

    # 1. CSV paths configuration
    # results/csv_raw folder in the benchmark root
    results_dir = os.path.join(parent_dir, "results")
    csv_dir = os.path.join(results_dir, "csv_raw")
    os.makedirs(csv_dir, exist_ok=True)

    # File prefix (e.g., results/csv_raw/locust_rep_1)
    csv_prefix = os.path.join(csv_dir, f"locust_rep_{replicas}")

    # Locust Command
    cmd = [
        "locust",
        "-f", os.path.join(parent_dir, "locustfile.py"),
        "--headless",
        "-u", str(users),
        "-r", str(spawn_rate),
        "-t", f"{duration}s",
        "--host", config.API_URL.replace("/api", ""),
        "--csv", csv_prefix
    ]

    # 2. Locust Execution
    # check=False is CRITICAL: allows continuing even if Locust exits with error (e.g., too many 500s)
    try:
        subprocess.run(cmd, check=False, cwd=parent_dir, stdout=subprocess.DEVNULL)
    except Exception as e:
        print(f"[CRITICAL ERROR] Locust failed to start: {e}")
        return None

    # 3. Reading results from generated CSV
    # Locust adds "_stats.csv" to the prefix we passed
    stats_file = f"{csv_prefix}_stats.csv"
    result = {}

    if os.path.exists(stats_file):
        try:
            with open(stats_file, mode='r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # We take only the "Aggregated" row containing the summary
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

        # NOTE: We no longer delete files (os.remove removed)
        print(f"-> CSV saved to: {stats_file}")
    else:
        print(f"[ERROR] Stats file not found at: {stats_file}")
        return None

    return result


def test_scalability():
    driver = SwarmDriver(config.STACK_NAME)

    levels = [1, 3, 5]

    output = {
        "test_name": "scalability_stress_test",
        "description": "Stress test using Locust to find saturation point",
        "results": []
    }

    print("--- Scalability & Load Balancing Stress Test (Locust) ---")

    # Initial reset for cleanup
    driver.reset_cluster()

    for replicas in levels:
        # Scale
        driver.scale_service(config.SERVICE_NAME, replicas)

        # Waiting for convergence
        print(f"[TEST] Waiting for {replicas} replicas to be ready...")
        time.sleep(5)
        max_wait = 60
        start_wait = time.time()
        while True:
            current, desired = driver.get_replica_count(config.SERVICE_NAME)
            if current == replicas:
                print(f"[TEST] Convergence reached: {current}/{replicas}")
                break
            if time.time() - start_wait > max_wait:
                print("[WARNING] Timeout waiting for convergence.")
                break
            time.sleep(2)

        # Extra time for Flask stabilization
        time.sleep(5)

        # Run Test
        data = run_locust_test(replicas, duration=20, users=500, spawn_rate=50)

        # Add to report (even if failures > 0)
        if data:
            print(f"-> Result: {data['rps']} RPS | {data['avg_latency']}ms avg | Failures: {data['failures']}")
            output["results"].append(data)
        else:
            print(f"[ERROR] No data collected for {replicas} replicas")

    # Final JSON saving
    os.makedirs("results", exist_ok=True)
    outfile = "results/scalability_load_balancing.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n[TEST] Completed. JSON saved to {outfile}")
    print(f"[TEST] Raw CSVs saved in results/csv_raw/")


if __name__ == "__main__":
    test_scalability()