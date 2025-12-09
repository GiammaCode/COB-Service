import time
import sys
import os
import json

# Setup path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

import config
from drivers.swarm_driver import SwarmDriver


def test_scheduling():
    driver = SwarmDriver(config.STACK_NAME)

    # Definiamo i livelli di carico per lo scheduler
    # 10: Riscaldamento
    # 50: Carico medio
    # 100: Burst (se l'hardware lo permette, altrimenti riduci a 75)
    levels = [10, 50, 100]

    dummy_service = "benchmark_dummy"

    output = {
        "test_name": "scheduling_overhead_burst",
        "description": "Time to schedule N lightweight containers (Alpine)",
        "results": []
    }

    print("--- Scheduling Overhead Test (Burst) ---")

    driver.reset_cluster()

    for target in levels:
        print(f"\n[TEST] Testing burst of {target} containers...")

        # 1. Creazione del servizio (Start Timer)
        start_time = time.time()
        driver.create_dummy_service(dummy_service, target)

        # 2. Polling attivo per verificare lo stato 'Running'
        # Non usiamo HTTP, controlliamo direttamente Docker
        while True:
            running = driver.count_running_tasks(dummy_service)
            # print(f"\rNodes Active: {running}/{target}", end="") # Decommenta per vedere progresso live

            if running >= target:
                end_time = time.time()
                break

            # Timeout di sicurezza (60s)
            if time.time() - start_time > 60:
                print("\n[WARNING] Timeout reached!")
                end_time = time.time()
                break

            # Polling frequente ma non troppo per non intasare la CPU del manager
            time.sleep(0.2)

        duration = end_time - start_time
        print(f"\n-> Result: {target} containers in {duration:.3f}s")
        print(f"-> Rate: {target / duration:.2f} containers/sec")

        output["results"].append({
            "containers": target,
            "total_time_seconds": round(duration, 4),
            "avg_time_per_container": round(duration / target, 4),
            "containers_per_second": round(target / duration, 2)
        })

        # Cleanup immediato per il prossimo livello
        driver.remove_service(dummy_service)
        # Pausa per far stabilizzare il cluster (cleanup dei network namespaces)
        print("[TEST] Cooling down (10s)...")
        time.sleep(10)

    # Salvataggio
    os.makedirs("results", exist_ok=True)
    outfile = "results/scheduling_overhead.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[TEST] Completed. JSON saved to {outfile}")


if __name__ == "__main__":
    test_scheduling()