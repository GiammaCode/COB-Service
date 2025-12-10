import time
import requests
import threading
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

# Configurazione
STOP_TRAFFIC = False
TRAFFIC_LOG = []
POLLING_INTERVAL = 0.1


def traffic_generator():
    """Genera traffico costante per rilevare buchi di servizio"""
    global STOP_TRAFFIC, TRAFFIC_LOG
    print("[TRAFFIC] Generator started...")

    s = requests.Session()

    while not STOP_TRAFFIC:
        ts = time.time()
        status = 0
        error_msg = ""
        try:
            resp = s.get(config.API_URL + "/assignments", timeout=1)
            status = resp.status_code
        except Exception as e:
            status = -1
            error_msg = str(e)

        TRAFFIC_LOG.append({
            "timestamp": ts,
            "status": status,
            "error": error_msg
        })
        time.sleep(POLLING_INTERVAL)


def wait_for_http_ready(url, timeout=60):
    """Attende che l'URL risponda 200 OK"""
    print(f"[TEST] Waiting for HTTP 200 OK from {url}...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            if requests.get(url, timeout=1).status_code == 200:
                print("[TEST] Service is READY! 🟢")
                return True
        except:
            pass
        time.sleep(1)
    print("[TEST] Service NOT READY (Timeout) 🔴")
    return False


def test_rolling_update():
    global STOP_TRAFFIC
    driver = SwarmDriver(config.STACK_NAME)

    output = {
        "test_name": "rolling_update_zero_downtime",
        "description": "Verifies service availability during a forced rolling update (start-first)",
        "replicas": 3,
        "results": {}
    }

    print("--- Rolling Update Test (Zero Downtime) ---")

    # 1. SETUP
    driver.reset_cluster()

    replicas = 3
    driver.scale_service(config.SERVICE_NAME, replicas)

    print(f"[TEST] Waiting for infrastructure ({replicas} replicas)...")

    # Attesa convergenza Docker
    while True:
        curr, des = driver.get_replica_count(config.SERVICE_NAME)
        if curr == replicas:
            break
        time.sleep(2)

    # --- FIX: ATTESA LIVELLO APPLICATIVO (HTTP) ---
    # Non partiamo finché NGINX + Backend non si parlano
    if not wait_for_http_ready(config.API_URL + "/assignments"):
        print("[CRITICAL] Il cluster non risponde. Test abortito.")
        driver.reset_cluster()
        return
    # ----------------------------------------------

    # 2. START TRAFFIC
    t = threading.Thread(target=traffic_generator)
    t.start()

    print("[TEST] Baseline traffic (5s)...")
    time.sleep(5)

    # 3. TRIGGER UPDATE
    full_service_name = f"{config.STACK_NAME}_{config.SERVICE_NAME}"
    # Aggiornamento lento (10s delay) per vedere bene il transitorio
    update_cmd = f"docker service update --force --update-order start-first --update-delay 10s {full_service_name}"

    print(f"[TEST] 🚀 Triggering Rolling Update (Start-First)...")
    update_start_time = time.time()

    driver._run(update_cmd)

    # 4. MONITOR UPDATE
    # Attesa fissa abbondante per coprire tutto il rolling
    time.sleep(45)

    update_end_time = time.time()
    update_duration = update_end_time - update_start_time
    print(f"[TEST] Update window finished ({update_duration:.2f}s). Stopping traffic...")

    # 5. STOP & ANALYZE
    STOP_TRAFFIC = True
    t.join()

    # 6. ANALISI
    total_reqs = len(TRAFFIC_LOG)
    errors = [x for x in TRAFFIC_LOG if x['status'] != 200]
    total_errors = len(errors)

    # Errori solo DURANTE l'update (escludiamo eventuali errori iniziali di warmup se sfuggiti)
    update_errors = [x for x in errors if x['timestamp'] >= update_start_time and x['timestamp'] <= update_end_time]

    success_rate = ((total_reqs - total_errors) / total_reqs) * 100 if total_reqs > 0 else 0

    print(f"\n-> RISULTATI:")
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

    # Salvataggio CSV Log
    csv_path = "results/rolling_update_log.csv"
    os.makedirs("results", exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "status", "error"])
        writer.writeheader()
        writer.writerows(TRAFFIC_LOG)

    # Salvataggio JSON
    outfile = "results/rolling_update.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)

    driver.reset_cluster()
    print(f"\n[TEST] Completed. JSON saved to {outfile}")


if __name__ == "__main__":
    test_rolling_update()