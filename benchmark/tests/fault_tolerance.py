import time
import requests
import threading
import sys
import os
import json

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
import config
from drivers.swarm_driver import SwarmDriver

# Configurazione
TEST_DURATION = 60  # Durata totale monitoraggio post-kill
POLLING_INTERVAL = 0.1 # Frequenza richieste (10 req/s per alta precisione)
MANUAL_MODE = False  # Metti True se SSH non funziona e vuoi spegnere a mano

stop_traffic = False
traffic_log = []

def traffic_generator():
    """Genera traffico sequenziale e logga ogni singola richiesta"""
    global stop_traffic
    print("[TRAFFIC] Generator started...")

    # Sessione per performance, ma disabilitiamo keep-alive per testare il routing reale
    s = requests.Session()

    while not stop_traffic:
        ts = time.time()
        status = 0
        error_msg = ""
        try:
            # Timeout molto breve: se il nodo è morto, vogliamo fallire subito
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

    # 1. SETUP
    driver.reset_cluster()

    # Usiamo 6 repliche per essere sicuri di avere target sul nodo vittima
    target_replicas = 6
    driver.scale_service(config.SERVICE_NAME, target_replicas)

    print(f"[TEST] Waiting for convergence ({target_replicas} replicas)...")
    time.sleep(15)

    # Identifica vittima
    workers = driver.get_worker_nodes()
    if not workers:
        print("[ERROR] No worker nodes found! Is the cluster running?")
        return

    # Scegliamo il primo worker disponibile
    victim = workers[0]
    print(f"[TEST] Target Victim: {victim}")
    output["victim_node"] = victim

    # 2. START TRAFFIC
    t = threading.Thread(target=traffic_generator)
    t.start()

    # Lascia girare il traffico per un po' per avere una baseline
    print("[TEST] Baseline traffic (10s)...")
    time.sleep(10)

    # 3. KILL
    print(f"\n[TEST] 🔥 EXECUTING HARD KILL ON {victim}...")
    kill_time = time.time()
    output["timeline_events"].append({"event": "kill_start", "time": kill_time})

    if MANUAL_MODE:
        input(f">>> AZIONE MANUALE: Spegni Docker su {victim} e premi INVIO <<<")
    else:
        driver.stop_node_daemon(victim)

    print(f"[TEST] Node killed. Monitoring recovery for {TEST_DURATION}s...")

    # 4. MONITOR RECOVERY
    time.sleep(TEST_DURATION)

    # 5. STOP & ANALYZE
    stop_traffic = True
    t.join()

    # 6. RESTORE NODE (Per pulizia futura)
    print(f"[TEST] Restoring node {victim} (cleanup)...")
    if not MANUAL_MODE:
        driver.start_node_daemon(victim)

    # --- ANALISI DATI ---
    # Convertiamo i log in CSV per debug
    csv_path = "results/fault_tolerance_log.csv"
    os.makedirs("results", exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "status", "error"])
        writer.writeheader()
        writer.writerows(traffic_log)

    # Calcolo RTO
    # Cerchiamo il primo fallimento dopo il kill
    failures_after_kill = [x for x in traffic_log if x['timestamp'] > kill_time and x['status'] != 200]

    if not failures_after_kill:
        print("-> ⚠️ NO FAILURES DETECTED. Il sistema non ha risentito del kill (o il kill non ha funzionato).")
        rto = 0
    else:
        first_fail_ts = failures_after_kill[0]['timestamp']

        # Cerchiamo quando il sistema è tornato stabile (es. ultimi 10 successi consecutivi)
        # Semplificazione: prendiamo l'ultimo timestamp di errore e calcoliamo la differenza dal primo
        last_fail_ts = failures_after_kill[-1]['timestamp']

        # RTO grezzo: Tempo dall'inizio dei problemi alla fine dei problemi
        rto = last_fail_ts - first_fail_ts

        total_errors = len(failures_after_kill)

        output["rto_seconds"] = round(rto, 2)
        output["total_failures"] = total_errors
        output["first_fail_ts"] = first_fail_ts
        output["last_fail_ts"] = last_fail_ts

        print(f"\n-> RISULTATI:")
        print(f"   Failures detected: {total_errors}")
        print(f"   Estimated RTO: {rto:.2f} seconds")
        print(f"   (Dettagli nel file CSV: {csv_path})")

    # Salvataggio JSON
    outfile = "results/fault_tolerance.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    test_fault_tolerance()