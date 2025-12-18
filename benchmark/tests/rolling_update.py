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
from drivers.k8s_driver import K8sDriver

# --- Constants & Globals ---
STOP_TRAFFIC = False
TRAFFIC_LOG = []
POLLING_INTERVAL = 0.1  # Seconds between requests
HTTP_TIMEOUT = 1  # Timeout for individual requests
UPDATE_WINDOW = 45  # Time to monitor during the update
REPLICAS = 3


def traffic_generator():
    """
    Generates constant traffic to detect service gaps during updates.
    Logs every request to TRAFFIC_LOG.
    """
    global STOP_TRAFFIC, TRAFFIC_LOG
    print("[TRAFFIC] Generator started...")

    s = requests.Session()

    # We test the specific endpoint to ensure backend connectivity
    base_url = config.API_URL

    while not STOP_TRAFFIC:
        ts = time.time()
        status = 0
        error_msg = ""
        try:
            resp = s.get(f"{base_url}/assignments", timeout=HTTP_TIMEOUT)
            status = resp.status_code
        except Exception as e:
            status = -1  # Connection error or timeout
            error_msg = str(e)

        TRAFFIC_LOG.append({
            "timestamp": ts,
            "status": status,
            "error": error_msg
        })
        time.sleep(POLLING_INTERVAL)


def wait_for_http_ready(url, timeout=60):
    """
    Polls a URL until it returns HTTP 200 OK.
    """
    print(f"[TEST] Waiting for HTTP 200 OK from {url}...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            if requests.get(url, timeout=HTTP_TIMEOUT).status_code == 200:
                print("[TEST] Service is READY!")
                return True
        except:
            pass
        time.sleep(1)

    print("[TEST] Service NOT READY (Timeout).")
    return False


def test_rolling_update():
    """
    Main Rolling Update Test.
    Scales service, starts traffic, triggers K8s rollout, and analyzes downtime.
    """
    global STOP_TRAFFIC
    driver = K8sDriver()

    output = {
        "test_name": "rolling_update_zero_downtime_k8s",
        "description": "Verifies service availability during a forced rolling update (rollout restart)",
        "replicas": REPLICAS,
        "results": {}
    }

    print("--- Rolling Update Test (Zero Downtime - K8s) ---")

    # 1. SETUP
    driver.reset_cluster()

    service_name = config.SERVICE_NAME  # 'backend'
    driver.scale_service(service_name, REPLICAS)

    print(f"[TEST] Waiting for infrastructure ({REPLICAS} replicas)...")

    # Wait for K8s convergence
    max_wait = 120
    start_wait = time.time()
    while True:
        curr, des = driver.get_replica_count(service_name)
        if curr == REPLICAS and des == REPLICAS:
            break
        if time.time() - start_wait > max_wait:
            print("[CRITICAL] Timeout waiting for replicas.")
            return
        time.sleep(2)

    # Extra cooldown to ensure containers are fully up
    time.sleep(5)

    # Check Application Level Health
    target_url = f"{config.API_URL}/assignments"
    if not wait_for_http_ready(target_url):
        print("[CRITICAL] Cluster unresponsive. Aborting test.")
        return

    # 2. START TRAFFIC GENERATOR
    t = threading.Thread(target=traffic_generator)
    t.start()

    print("[TEST] Recording baseline traffic (5s)...")
    time.sleep(5)

    # 3. TRIGGER UPDATE
    print(f"[TEST] Triggering Rolling Update (Rollout Restart)...")
    update_start_time = time.time()

    driver.trigger_rolling_update(service_name)

    # 4. MONITOR UPDATE PROCESS
    print(f"[TEST] Monitoring update process for {UPDATE_WINDOW}s...")
    time.sleep(UPDATE_WINDOW)

    update_end_time = time.time()
    update_duration = update_end_time - update_start_time
    print(f"[TEST] Update window finished. Stopping traffic...")

    # 5. STOP & ANALYZE
    STOP_TRAFFIC = True
    t.join()

    # Calculate Stats
    total_reqs = len(TRAFFIC_LOG)
    errors = [x for x in TRAFFIC_LOG if x['status'] != 200]
    total_errors = len(errors)

    # Filter errors that happened strictly during the update window
    update_errors = [x for x in errors if x['timestamp'] >= update_start_time and x['timestamp'] <= update_end_time]

    success_rate = ((total_reqs - total_errors) / total_reqs) * 100 if total_reqs > 0 else 0

    print(f"\n-> RESULTS:")
    print(f"   Total Requests: {total_reqs}")
    print(f"   Failed Requests: {total_errors}")
    print(f"   Success Rate: {success_rate:.2f}%")

    output["results"] = {
        "duration_seconds": round(update_duration, 2),
        "total_requests": total_reqs,
        "failed_requests": total_errors,
        "success_rate_percent": round(success_rate, 2),
        "errors_during_update": len(update_errors)
    }

    # Save CSV Log
    csv_path = "results/rolling_update_log_k8s.csv"
    os.makedirs("results", exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "status", "error"])
        writer.writeheader()
        writer.writerows(TRAFFIC_LOG)

    # Save JSON Results
    outfile = "results/rolling_update_k8s.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n[TEST] Completed. JSON saved to {outfile}")


if __name__ == "__main__":
    test_rolling_update()