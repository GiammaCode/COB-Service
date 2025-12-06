import time
import requests
import threading
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
from drivers.swarm_driver import SwarmDriver

stop_traffic = False
errors = []

def traffic_generator():
    while not stop_traffic:
        try:
            resp = requests.get("http://localhost:5001/", timeout=1)
            if resp.status_code != 200:
                errors.append(time.time())
        except:
            errors.append(time.time())
        time.sleep(0.1)

def test_fault_tolerance():
    global stop_traffic
    driver = SwarmDriver()

    # Setup: Assicurati di avere repliche su più nodi
    driver.scale_service("backend", 4)
    time.sleep(10)

    victim_node = driver.get_worker_nodes()[0] # Prendi un worker a caso

    print(f"--- Start Fault Tolerance (Killing {victim_node}) ---")

    # 1. Start Traffic
    t = threading.Thread(target=traffic_generator)
    t.start()

    # 2. Kill Node
    time.sleep(2)
    kill_time = time.time()
    driver.drain_node(victim_node)

    # 3. Wait for recovery logic
    time.sleep(15)

    # 4. Stop & Measure
    stop_traffic = True
    t.join()

    # Ripristina nodo
    driver.active_node(victim_node)

    if not errors:
        print("Result: 0s downtime (Perfect!)")
    else:
        first_error = min(errors)
        last_error = max(errors)
        # Filtra errori avvenuti solo DOPO il kill command
        relevant_errors = [e for e in errors if e >= kill_time]
        if relevant_errors:
            downtime = max(relevant_errors) - min(relevant_errors)
            print(f"Result: {downtime:.4f} seconds of instability")
        else:
             print("Result: No relevant errors detected")

if __name__ == "__main__":
    test_fault_tolerance()