import time
import requests
from benchmark.test_features.swarm_driver import SwarmDriver


def test_scheduling_overhead():
    driver = SwarmDriver()
    target_replicas = 5

    # 1. Reset
    driver.scale_service("backend", 0)
    time.sleep(5)  # Attesa tecnica cleanup

    print("--- Start Scheduling Overhead Test ---")
    start_time = time.time()

    # 2. Command
    driver.scale_service("backend", target_replicas)
    command_sent_time = time.time()

    # 3. Measure (Polling HTTP)
    active_replicas = 0
    while active_replicas < target_replicas:
        try:
            # Facciamo N richieste per vedere quanti container unici rispondono
            unique_ids = set()
            for _ in range(target_replicas * 2):
                resp = requests.get("http://localhost:5001/", timeout=1)
                if resp.status_code == 200:
                    unique_ids.add(resp.json().get('container_id'))

            active_replicas = len(unique_ids)
            print(f"Replicas responding: {active_replicas}/{target_replicas}")

            if active_replicas >= target_replicas:
                break
        except:
            pass
        time.sleep(0.5)

    end_time = time.time()

    print(f"Result: {end_time - start_time:.4f} seconds")
    return end_time - start_time


if __name__ == "__main__":
    test_scheduling_overhead()