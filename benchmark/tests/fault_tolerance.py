import time
import requests
import threading
import sys
import os
import json
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
import benchmark.config as config
from drivers.swarm_driver import SwarmDriver

stop_traffic = False
traffic_log = []


def traffic_generator():
    while not stop_traffic:
        timestamp = time.time()
        status = 0
        try:
            resp = requests.get(config.API_URL, timeout=1)
            status = resp.status_code
        except:
            status = 500

        traffic_log.append({"ts": timestamp, "status": status})
        time.sleep(0.1)


def test_fault_tolerance():
    global stop_traffic
    driver = SwarmDriver(config.STACK_NAME)

    print("--- Fault Tolerance Test ---")

    # 1. Setup stabile (almeno 3 repliche per avere ridondanza)
    driver.scale_service(config.SERVICE_NAME, 3)
    time.sleep(10)

    # Identifica vittima
    workers = driver.get_worker_nodes()
    if not workers:
        print("[ERROR] No worker nodes found to kill!")
        return
    victim = workers[0]

    print(f"[TEST] Starting background traffic...")
    t = threading.Thread(target=traffic_generator)
    t.start()
    time.sleep(5)  # Traffico normale

    print(f"[TEST] KILLING NODE: {victim}")
    kill_time = time.time()
    driver.drain_node(victim)

    # 2. Attendi recovery
    time.sleep(20)

    # 3. Stop & Analyze
    stop_traffic = True
    t.join()

    # Ripristina nodo per il futuro
    print(f"[TEST] Restoring node {victim}...")
    driver.active_node(victim)

    # Calcolo Downtime
    # Cerchiamo errori DOPO il kill time e PRIMA che torni 200
    errors_after_kill = [x for x in traffic_log if x['ts'] >= kill_time and x['status'] != 200]

    result = {
        "test_name": "fault_tolerance",
        "victim_node": victim,
        "downtime_seconds": 0,
        "total_errors": len(errors_after_kill)
    }

    if errors_after_kill:
        start_error = min(x['ts'] for x in errors_after_kill)
        end_error = max(x['ts'] for x in errors_after_kill)
        downtime = end_error - start_error
        result["downtime_seconds"] = round(downtime, 2)
        print(f"-> Downtime Detected: {downtime:.2f} seconds")
    else:
        print("-> 0 Downtime (Seamless failover)")

    with open("results_fault.json", "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    test_fault_tolerance()