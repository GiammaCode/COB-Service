import sys
import os
import json

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
import config
from drivers.swarm_driver import SwarmDriver


def test_resource_overhead():
    driver = SwarmDriver(config.STACK_NAME)
    print("--- Resource Overhead Test ---")

    # 1. Cluster Scarico
    print("[TEST] Cleaning up (0 replicas)...")
    driver.scale_service(config.SERVICE_NAME, 0)
    time.sleep(10)

    base_stats = driver.get_cluster_stats()
    print(f"-> Base: {base_stats}")

    # 2. Cluster Carico (Tanti container idle)
    # Nota: su hardware limitato, 20 container potrebbero pesare
    n_containers = 10
    print(f"[TEST] Scaling to {n_containers} idle containers...")
    driver.scale_service(config.SERVICE_NAME, n_containers)
    time.sleep(15)

    load_stats = driver.get_cluster_stats()
    print(f"-> Loaded: {load_stats}")

    # Calcolo Delta per container
    delta_mem = load_stats['memory_mb'] - base_stats['memory_mb']
    per_container = delta_mem / n_containers if n_containers > 0 else 0

    print(f"-> Memory Overhead per Container: ~{per_container:.2f} MB")

    res = {
        "test_name": "resource_overhead",
        "base_stats": base_stats,
        "load_stats": load_stats,
        "overhead_per_container_mb": per_container
    }

    with open("results_overhead.json", "w") as f:
        json.dump(res, f, indent=2)

    # Cleanup
    driver.scale_service(config.SERVICE_NAME, 0)


if __name__ == "__main__":
    test_resource_overhead()