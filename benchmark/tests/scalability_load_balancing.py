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
    Esegue Locust in modalità headless e restituisce le statistiche.
    Salva i CSV in results/csv_raw senza cancellarli.
    """
    print(f"[TEST] Starting Load Test with Locust (Replicas: {replicas})...")

    # 1. Configurazione percorsi CSV
    # Cartella results/csv_raw nella root del benchmark
    results_dir = os.path.join(parent_dir, "results")
    csv_dir = os.path.join(results_dir, "csv_raw")
    os.makedirs(csv_dir, exist_ok=True)

    # Prefisso del file (es: results/csv_raw/locust_rep_1)
    csv_prefix = os.path.join(csv_dir, f"locust_rep_{replicas}")

    # Comando Locust
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

    # 2. Esecuzione Locust
    # check=False è CRUCIALE: permette di continuare anche se Locust esce con errore (es. troppi 500)
    try:
        subprocess.run(cmd, check=False, cwd=parent_dir, stdout=subprocess.DEVNULL)
    except Exception as e:
        print(f"[CRITICAL ERROR] Locust failed to start: {e}")
        return None

    # 3. Lettura dei risultati dal CSV generato
    # Locust aggiunge "_stats.csv" al prefisso che gli abbiamo passato
    stats_file = f"{csv_prefix}_stats.csv"
    result = {}

    if os.path.exists(stats_file):
        try:
            with open(stats_file, mode='r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Prendiamo solo la riga "Aggregated" che contiene il riassunto
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

        # NOTA: Non cancelliamo più i file (os.remove rimosso)
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

    # Reset iniziale per pulizia
    driver.reset_cluster()

    for replicas in levels:
        # Scale
        driver.scale_service(config.SERVICE_NAME, replicas)

        # Attesa convergenza
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

        # Tempo extra per stabilizzazione Flask
        time.sleep(5)

        # Esecuzione Test
        data = run_locust_test(replicas, duration=20, users=500, spawn_rate=50)

        # Aggiunta al report (anche se failures > 0)
        if data:
            print(f"-> Result: {data['rps']} RPS | {data['avg_latency']}ms avg | Failures: {data['failures']}")
            output["results"].append(data)
        else:
            print(f"[ERROR] No data collected for {replicas} replicas")

        # Reset tra un test e l'altro per pulire le risorse
        driver.reset_cluster()

    # Salvataggio JSON finale
    os.makedirs("results", exist_ok=True)
    outfile = "results/scalability_load_balancing.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n[TEST] Completed. JSON saved to {outfile}")
    print(f"[TEST] Raw CSVs saved in results/csv_raw/")


if __name__ == "__main__":
    test_scalability()