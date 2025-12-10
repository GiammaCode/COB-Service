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
POLLING_INTERVAL = 0.1  # 10 req/s circa per monitorare la continuità


def traffic_generator():
    """Genera traffico costante per rilevare buchi di servizio"""
    global STOP_TRAFFIC, TRAFFIC_LOG
    print("[TRAFFIC] Generator started...")

    # Sessione riutilizzabile per efficienza
    s = requests.Session()

    while not STOP_TRAFFIC:
        ts = time.time()
        status = 0
        error_msg = ""
        try:
            # Timeout breve: in un rolling update non vogliamo code infinite
            resp = s.get(config.API_URL + "/assignments", timeout=1)
            status = resp.status_code
        except Exception as e:
            status = -1  # Connection Error
            error_msg = str(e)

        TRAFFIC_LOG.append({
            "timestamp": ts,
            "status": status,
            "error": error_msg
        })
        time.sleep(POLLING_INTERVAL)


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

    print(f"[TEST] Waiting for convergence ({replicas} replicas)...")
    time.sleep(10)  # Attesa tecnica

    # Verifica convergenza
    while True:
        curr, des = driver.get_replica_count(config.SERVICE_NAME)
        if curr == replicas:
            break
        time.sleep(2)

    # 2. START TRAFFIC
    t = threading.Thread(target=traffic_generator)
    t.start()

    print("[TEST] Baseline traffic (5s)...")
    time.sleep(5)

    # 3. TRIGGER UPDATE
    # Usiamo --force per garantire che l'update avvenga anche se l'immagine è identica.
    # --update-order start-first è CRUCIALE per il zero-downtime (accendi il nuovo prima di spegnere il vecchio)
    full_service_name = f"{config.STACK_NAME}_{config.SERVICE_NAME}"
    update_cmd = f"docker service update --force --update-order start-first --update-delay 10s {full_service_name}"

    print(f"[TEST] 🚀 Triggering Rolling Update (Start-First)...")
    update_start_time = time.time()

    # Eseguiamo il comando manualmente tramite il driver interno per avere il flag --force
    driver._run(update_cmd)

    # 4. MONITOR UPDATE
    # Attendiamo che l'update finisca.
    # Swarm impiegherà: (Delay 10s * Repliche) + Tempo di avvio container
    print("[TEST] Monitor update progress...")

    # Semplice attesa basata sul calcolo teorico + buffer
    # 3 repliche * 10s delay = 30s minimo. Facciamo 45s per sicurezza.
    # In una tesi potresti fare polling su "docker service ps" per vedere quando tutti sono "Running" da pochi secondi.
    time.sleep(45)

    update_end_time = time.time()
    update_duration = update_end_time - update_start_time
    print(f"[TEST] Update window finished ({update_duration:.2f}s). Stopping traffic...")

    # 5. STOP & ANALYZE
    STOP_TRAFFIC = True
    t.join()

    # 6. ANALISI
    total_reqs = len(TRAFFIC_LOG)
    # Consideriamo errori tutto ciò che non è 200 (inclusi 500, 502, 503, timeout)
    errors = [x for x in TRAFFIC_LOG if x['status'] != 200]
    total_errors = len(errors)

    # Filtriamo errori SOLO durante la finestra di update
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

    # Salvataggio CSV Log per grafici
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

    # Cleanup
    driver.reset_cluster()
    print(f"\n[TEST] Completed. JSON saved to {outfile}")


if __name__ == "__main__":
    test_rolling_update()