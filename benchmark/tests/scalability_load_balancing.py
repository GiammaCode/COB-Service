import time
import subprocess
import sys
import os
import json
import csv

# --- Setup Paths ---
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# --- Local Imports ---
import config
#from drivers.swarm_driver import SwarmDriver
#from drivers.k8s_driver import K8sDriver
from drivers.nomad_driver import NomadDriver

# --- Constants ---
LOCUST_USERS = 500
LOCUST_SPAWN_RATE = 50
TEST_DURATION = 30
CONVERGENCE_TIMEOUT = 120  # Seconds to wait for pods to be ready
STABILIZATION_TIME = 5  # Seconds to wait after convergence


def run_locust_test(replicas, duration=TEST_DURATION, users=LOCUST_USERS, spawn_rate=LOCUST_SPAWN_RATE):
    """
    Executes a Locust load test in headless mode.
    """
    print(f"[TEST] Starting Load Test with Locust (Replicas: {replicas})...")

    # Setup results directory
    results_dir = os.path.join(parent_dir, "results")
    csv_dir = os.path.join(results_dir, "csv_raw")
    os.makedirs(csv_dir, exist_ok=True)

    # Define CSV prefix for Locust output
    csv_prefix = os.path.join(csv_dir, f"locust_rep_{replicas}")

    host_url = config.API_URL.replace("/api", "")
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
        # Run Locust and suppress standard output to keep console clean
        subprocess.run(cmd, check=False, cwd=parent_dir, stdout=subprocess.DEVNULL)
    except Exception as e:
        print(f"[CRITICAL ERROR] Locust failed to start: {e}")
        return None

    # Parse the generated stats file
    stats_file = f"{csv_prefix}_stats.csv"
    result = {}

    if os.path.exists(stats_file):
        try:
            with open(stats_file, mode='r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # We are interested in the 'Aggregated' row for total stats
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
            print(f"[ERROR] Failed reading CSV: {e}")
            return None
        print(f"-> CSV saved to: {stats_file}")
    else:
        print(f"[ERROR] Stats file not found at: {stats_file}")
        return None

    return result


def test_scalability():
    """
    Main Scalability Test Loop.
    Scales the backend to [1, 3, 5] replicas and runs a load test for each level.
    """
    #driver = SwarmDriver()
    #driver = K8sDriver()
    driver = NomadDriver()
    levels = [1, 3, 5]

    output = {
        "test_name": "scalability_stress_test_nomad",
        "description": "Stress test using Locust on Nomad to measure throughput vs replicas",
        "results": []
    }

    print("--- Scalability & Load Balancing Stress Test (Nomad) ---")

    # Reset cluster to a clean state
    driver.reset_cluster()

    for replicas in levels:
        service_name = config.SERVICE_NAME  # Usually 'backend'

        driver.scale_service(service_name, replicas)

        print(f"[TEST] Waiting for {replicas} replicas to be ready...")
        time.sleep(2)  # Allow K8s API to update status

        # Wait for convergence
        start_wait = time.time()
        while True:
            current, desired = driver.get_replica_count(service_name)
            if current == replicas and desired == replicas:
                print(f"[TEST] Convergence reached: {current}/{replicas}")
                break

            if time.time() - start_wait > CONVERGENCE_TIMEOUT:
                print(f"[WARNING] Timeout waiting for convergence ({current}/{replicas}). proceeding anyway...")
                break
            time.sleep(2)

        print(f"[TEST] Stabilizing for {STABILIZATION_TIME}s...")
        time.sleep(STABILIZATION_TIME)

        # Run the actual load test
        data = run_locust_test(replicas)

        if data:
            print(f"-> Result: {data['rps']} RPS | {data['avg_latency']}ms avg | Failures: {data['failures']}")
            output["results"].append(data)
        else:
            print(f"[ERROR] No data collected for {replicas} replicas")

    # Save Results
    os.makedirs("results", exist_ok=True)
    outfile = "results/scalability_load_balancing_nomad.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n[TEST] Completed. JSON saved to {outfile}")


if __name__ == "__main__":
    test_scalability()