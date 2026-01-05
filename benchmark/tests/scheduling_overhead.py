import time
import sys
import os
import json

# Setup path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# Local imports
import config
# from drivers.k8s_driver import K8sDriver
from drivers.nomad_driver import NomadDriver  # <--- USIAMO NOMAD

DUMMY_SERVICE_NAME = "benchmark-dummy"
# Livelli di carico: 10, 50, 100 container
# Nomad è molto veloce, potremmo osare anche di più, ma restiamo coerenti col test K8s
LEVELS = [10, 50, 100]
TIMEOUT_SECONDS = 120


def test_scheduling():
    driver = NomadDriver()

    output = {
        "test_name": "scheduling_overhead_burst_nomad",
        "description": "Time to schedule N lightweight containers (Alpine) on Nomad",
        "results": []
    }

    print("--- Scheduling Overhead Test (Burst - Nomad) ---")

    # Clean start
    driver.remove_service(DUMMY_SERVICE_NAME)

    # --- WARMUP ---
    # Nomad è velocissimo a schedulare, ma se deve scaricare l'immagine docker (pull)
    # il test viene falsato dalla rete. Facciamo un giro a vuoto.
    print("[TEST] Warming up (Pulling Alpine image on nodes)...")
    driver.create_dummy_service(DUMMY_SERVICE_NAME, 3)  # 3 repliche (una per nodo)
    time.sleep(5)
    driver.remove_service(DUMMY_SERVICE_NAME)
    time.sleep(2)
    # --------------

    for target in LEVELS:
        print(f"\n[TEST] Testing burst of {target} containers...")

        # Start Timer
        start_time = time.time()

        # Inviamo il Job al cluster
        driver.create_dummy_service(DUMMY_SERVICE_NAME, target)

        # Polling for 'Running'
        # Nomad aggiorna lo stato molto velocemente
        while True:
            running = driver.count_running_tasks(DUMMY_SERVICE_NAME)

            sys.stdout.write(f"\r[POLLING] Active: {running}/{target}")
            sys.stdout.flush()

            if running >= target:
                end_time = time.time()
                print("")
                break

            # Timeout sicurezza
            if time.time() - start_time > TIMEOUT_SECONDS:
                print(f"\n[WARNING] Timeout reached! Only {running}/{target} started.")
                end_time = time.time()
                break

            time.sleep(0.1)  # Polling veloce per Nomad

        duration = end_time - start_time
        rate = target / duration if duration > 0 else 0

        print(f"\n-> Result: {target} containers in {duration:.3f}s")
        print(f"-> Rate: {rate:.2f} containers/sec")

        output["results"].append({
            "containers": target,
            "total_time_seconds": round(duration, 4),
            "avg_time_per_container": round(duration / target, 4),
            "containers_per_second": round(rate, 2)
        })

        # Cleanup immediato per il prossimo giro
        driver.remove_service(DUMMY_SERVICE_NAME)

        print("[TEST] Cooling down (5s)...")
        time.sleep(5)

    # Save res
    os.makedirs("results", exist_ok=True)
    outfile = "results/scheduling_overhead_nomad.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[TEST] Completed. JSON saved to {outfile}")


if __name__ == "__main__":
    test_scheduling()