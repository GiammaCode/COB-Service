import time
import requests
import threading
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
from drivers.k8s_driver import K8sDriver
from drivers.nomad_driver import NomadDriver

# --- Constants ---
TEST_DURATION = 90      # Duration of monitoring after the kill (seconds)
POLLING_INTERVAL = 0.1  # Request frequency (10 req/s for high precision RTO)
REPLICAS = 6            # High replica count to ensure spread across nodes

# Globals
stop_traffic = False
traffic_log = []

def traffic_generator():
    """
    Generates sequential traffic to measure availability.
    Logs every request to calculate RTO (Recovery Time Objective).
    """
    global stop_traffic, traffic_log
    print("[TRAFFIC] Generator started...")

    s = requests.Session()
    # We disable keep-alive to test fresh routing for every request,
    # ensuring we hit the load balancer logic properly.
    s.keep_alive = False

    base_url = config.API_URL

    while not stop_traffic:
        ts = time.time()
        status = 0
        error_msg = ""
        try:
            # Very short timeout: if a node is dead, we want to fail fast
            resp = s.get(f"{base_url}/assignments", timeout=0.5)
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
    #driver = K8sDriver()
    dirver = NomadDriver()

    output = {
        "test_name": "fault_tolerance_hard_kill_k8s",
        "description": "Measures RTO (Recovery Time Objective) after a node hard power-off",
        "victim_node": None,
        "rto_seconds": 0,
        "total_failures": 0,
        "timeline_events": []
    }

    print("--- Fault Tolerance Test (Hard Kill) ---")


    driver.reset_cluster()

    service_name = config.SERVICE_NAME  # 'backend'

    # Scale to many replicas to guarantee they land on the victim node too
    print(f"[TEST] Scaling to {REPLICAS} replicas to ensure cluster spread...")
    driver.scale_service(service_name, REPLICAS)

    print(f"[TEST] Waiting for convergence...")
    time.sleep(10)  # Simple wait for K8s

    # Identify a valid victim (a node that is actually running backend pods)
    active_nodes = driver.get_active_nodes(service_name)
    victim_candidates = [
        node for node in active_nodes
        if "mng" not in node.lower()
    ]

    if not victim_candidates:
        print("[ERROR] No active nodes found for the service.")
        return

    victim = victim_candidates[0]
    print(f"[TEST] Target Victim identified: {victim}")
    output["victim_node"] = victim

    # START TRAFFIC
    t = threading.Thread(target=traffic_generator)
    t.start()

    # Baseline traffic
    print("[TEST] Recording baseline traffic (10s)...")
    time.sleep(10)

    # KILL
    print(f"\n" + "=" * 50)
    print(f" >>> ACTION REQUIRED <<<")
    print(f" 1. Go to Proxmox Interface")
    print(f" 2. Locate VM: {victim}")
    print(f" 3. Right Click -> STOP (Hard Shutdown)")
    print(f" 4. IMMEDIATELY press ENTER here once clicked.")
    print(f"=" * 50 + "\n")

    kill_time = time.time()
    input(f"Press ENTER when {victim} is shutting down...")

    # Update kill time to be closer to actual user action if they delayed
    # (We assume the user presses enter right after clicking)
    kill_time = time.time()
    output["timeline_events"].append({"event": "kill_confirmed", "time": kill_time})

    print(f"[TEST] Node kill confirmed. Monitoring recovery for {TEST_DURATION}s...")

    # MONITOR RECOVERY
    time.sleep(TEST_DURATION)
    stop_traffic = True
    t.join()

    # CLEANUP REMINDER
    print(f"\n[IMPORTANT] Test finished. Remember to START node {victim} again in Proxmox!")

    # save raw data
    csv_path = "results/fault_tolerance_log_k8s.csv"
    os.makedirs("results", exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "status", "error"])
        writer.writeheader()
        writer.writerows(traffic_log)

    # Calculate RTO
    # We look for the first failure AFTER the kill confirmation
    failures_after_kill = [x for x in traffic_log if x['timestamp'] > kill_time and x['status'] != 200]

    if not failures_after_kill:
        print("\n-> RESULT: NO FAILURES DETECTED.")
        print("   Possibilities:")
        print("   1. The load balancer instantly routed away (Excellent).")
        print("   2. You killed a node that had no active traffic at that specific millisecond.")
        rto = 0
    else:
        first_fail_ts = failures_after_kill[0]['timestamp']
        last_fail_ts = failures_after_kill[-1]['timestamp']

        # RTO = Time between first error and last error
        rto = last_fail_ts - first_fail_ts

        # If RTO is very small (< 1s), it might be just a glitch.
        # If it's large (~60s), it's the K8s Node Monitor Grace Period.

        total_errors = len(failures_after_kill)

        output["rto_seconds"] = round(rto, 2)
        output["total_failures"] = total_errors
        output["first_fail_ts"] = first_fail_ts
        output["last_fail_ts"] = last_fail_ts

        print(f"\n-> RESULTS:")
        print(f"   Failures detected: {total_errors}")
        print(f"   Estimated RTO: {rto:.2f} seconds")
        print(f"   (See {csv_path} for details)")

    # Save JSON
    outfile = "results/fault_tolerance_nomad.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    test_fault_tolerance()