import time
import requests
import threading
import sys
import os
import json
import csv

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
import config
from drivers.swarm_driver import SwarmDriver

TEST_DURATION = 60  # Total monitoring duration post-kill
POLLING_INTERVAL = 0.1 # Request frequency (10 req/s for high precision)

stop_traffic = False
traffic_log = []

def traffic_generator():
    """Generates sequential traffic and logs every single request"""
    global stop_traffic
    print("[TRAFFIC] Generator started...")

    # Session for performance, but disable keep-alive to test real routing
    s = requests.Session()

    while not stop_traffic:
        ts = time.time()
        status = 0
        error_msg = ""
        try:
            # Very short timeout: if the node is dead, we want to fail immediately
            resp = s.get(config.API_URL + "/assignments", timeout=0.5)
            status = resp.status_code
        except Exception as e:
            status = -1  # Connection Error / Timeout
            error_msg = str(e)

        traffic_log.append({
            "timestamp": ts,
            "status": status,
            "error": error_msg
        })
        time.sleep(POLLING_INTERVAL)

def test_fault_tolerance():
    global stop_traffic
    driver = SwarmDriver(config.STACK_NAME)

    output = {
        "test_name": "fault_tolerance_hard_kill",
        "victim_node": None,
        "rto_seconds": 0,
        "total_failures": 0,
        "timeline_events": []
    }

    print("--- Fault Tolerance Test (Hard Kill) ---")

    # SETUP
    driver.reset_cluster()

    # Use 6 replicas to ensure we have targets on the victim node
    target_replicas = 6
    driver.scale_service(config.SERVICE_NAME, target_replicas)

    print(f"[TEST] Waiting for convergence ({target_replicas} replicas)...")
    time.sleep(15)

    # Identify victim
    workers = driver.get_worker_nodes()
    if not workers:
        print("[ERROR] No worker nodes found! Is the cluster running?")
        return

    # Choose the first available worker
    victim = workers[0]
    print(f"[TEST] Target Victim: {victim}")
    output["victim_node"] = victim

    # START TRAFFIC
    t = threading.Thread(target=traffic_generator)
    t.start()

    # Let traffic run for a while to establish a baseline
    print("[TEST] Baseline traffic (10s)...")
    time.sleep(10)

    # KILL
    print(f"\n[TEST] EXECUTING HARD KILL ON {victim}...")
    kill_time = time.time()
    output["timeline_events"].append({"event": "kill_start", "time": kill_time})

    input(f">>> MANUAL ACTION: Shutdown Docker on {victim} and press ENTER <<<")
    print(f"[TEST] Node killed. Monitoring recovery for {TEST_DURATION}s...")

    # MONITOR RECOVERY
    time.sleep(TEST_DURATION)
    stop_traffic = True
    t.join()

    # RESTORE NODE (For future cleanup)
    print(f"[TEST] Restoring node {victim} (cleanup)...")

    # --- DATA ANALYSIS ---
    # Convert logs to CSV for debug
    csv_path = "results/fault_tolerance_log.csv"
    os.makedirs("results", exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "status", "error"])
        writer.writeheader()
        writer.writerows(traffic_log)

    # RTO Calculation
    # Look for the first failure after kill
    failures_after_kill = [x for x in traffic_log if x['timestamp'] > kill_time and x['status'] != 200]

    if not failures_after_kill:
        print("-> NO FAILURES DETECTED. The system was not affected by the kill (or the kill didn't work).")
        rto = 0
    else:
        first_fail_ts = failures_after_kill[0]['timestamp']

        # Look for when the system became stable again (e.g. last 10 consecutive successes)
        # Simplification: take the last error timestamp and calculate difference from the first
        last_fail_ts = failures_after_kill[-1]['timestamp']

        # Raw RTO: Time from start of problems to end of problems
        rto = last_fail_ts - first_fail_ts

        total_errors = len(failures_after_kill)

        output["rto_seconds"] = round(rto, 2)
        output["total_failures"] = total_errors
        output["first_fail_ts"] = first_fail_ts
        output["last_fail_ts"] = last_fail_ts

        print(f"\n-> RESULTS:")
        print(f"   Failures detected: {total_errors}")
        print(f"   Estimated RTO: {rto:.2f} seconds")
        print(f"   (Details in CSV file: {csv_path})")

    # Saving JSON
    outfile = "results/fault_tolerance.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    test_fault_tolerance()