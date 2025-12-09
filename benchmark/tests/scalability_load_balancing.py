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
    """
    print(f"[TEST] Starting Load Test with Locust (Replicas: {replicas})...")

    # File temporaneo per i risultati CSV
    csv_prefix = f"locust_res_{replicas}"

    # Comando Locust:
    # -f locustfile.py : il file con la definizione del task
    # --headless : senza UI web
    # -u {users} : numero utenti concorrenti
    # -r {spawn_rate} : quanti utenti spawnare al secondo
    # -t {duration}s : durata test
    # --host : indirizzo target
    # --csv : output su file
    cmd = [
        "locust",
        "-f", os.path.join(parent_dir, "locustfile.py"),
        "--headless",
        "-u", str(users),
        "-r", str(spawn_rate),
        "-t", f"{duration}s",
        "--host", config.API_URL.replace("/api", ""),  # Locust aggiunge i path relativi, passiamo la base
        "--csv", csv_prefix
    ]

    # Eseguiamo Locust
    try:
        subprocess.run(cmd, check=True, cwd=parent_dir, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Locust failed: {e}")
        return None

    # Leggiamo il CSV generato (locust_res_{replicas}_stats.csv)
    stats_file = os.path.join(parent_dir, f"{csv_prefix}_stats.csv")
    result = {}

    if os.path.exists(stats_file):
        with open(stats_file, mode='r') as f:
            reader = csv.DictReader(f)
            for row in reader:
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
        # Pulizia file temp
        os.remove(stats_file)
        # Rimuovi anche _failures.csv ecc se creati
        # os.remove(os.path.join(parent_dir, f"{csv_prefix}_failures.csv"))

    else:
        print("[ERROR] Stats file not found!")

    return result


def test_scalability():
    driver = SwarmDriver(config.STACK_NAME)

    # Livelli di scalabilità da testare
    # Consiglio: spingi un po' di più se l'hardware regge (es. 10)
    levels = [1, 3, 5]

    output = {
        "test_name": "scalability_stress_test",
        "description": "Stress test using Locust to find saturation point",
        "results": []
    }

    print("--- Scalability & Load Balancing Stress Test (Locust) ---")

    for replicas in levels:
        #driver.reset_cluster()
        driver.scale_service(config.SERVICE_NAME, replicas)
        print(f"[TEST] Waiting for {replicas} replicas to be ready...")
        # Polling semplice per vedere se sono UP
        time.sleep(5)  # Attesa tecnica Docker
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

        time.sleep(5)
        data = run_locust_test(replicas, duration=20, users=100, spawn_rate=20)

        if data:
            print(f"-> Result: {data['rps']} RPS | {data['avg_latency']}ms avg latency")
            output["results"].append(data)


    driver.reset_cluster()

    os.makedirs("results", exist_ok=True)
    outfile = "results/scalability_load_balancing.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[TEST] Completed. Results saved to {outfile}")


if __name__ == "__main__":
    test_scalability()