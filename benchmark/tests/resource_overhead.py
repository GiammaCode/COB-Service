import time
import sys
import os
import json
import psutil
import statistics

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

import config
from drivers.swarm_driver import SwarmDriver


def get_dockerd_stats(process_name="dockerd"):
    for proc in psutil.process_iter(['pid', 'name']):
        if process_name in proc.info['name']:
            try:
                p = psutil.Process(proc.info['pid'])
                return {
                    "cpu": p.cpu_percent(interval=0.1),
                    "ram_mb": p.memory_info().rss / (1024 * 1024)
                }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    return None


def monitor_resources(duration_sec=10):
    cpus = []
    mems = []

    # Cerca il processo una volta
    target_proc = None
    for proc in psutil.process_iter(['pid', 'name']):
        if "dockerd" in proc.info['name']:
            target_proc = psutil.Process(proc.info['pid'])
            break

    if not target_proc:
        print("[ERROR] Process 'dockerd' not found! Are you running as root/sudo?")
        return None

    # Campionamento
    start = time.time()
    while time.time() - start < duration_sec:
        try:
            # interval=None perché chiamiamo in loop con sleep
            cpus.append(target_proc.cpu_percent(interval=None))
            mems.append(target_proc.memory_info().rss / (1024 * 1024))
            time.sleep(0.5)
        except:
            break

    return {
        "avg_cpu_percent": round(statistics.mean(cpus), 2),
        "avg_ram_mb": round(statistics.mean(mems), 2)
    }


def test_resource_overhead():
    driver = SwarmDriver(config.STACK_NAME)

    # Livelli di carico (Container Reali Flask)
    # Nota: 100 container Flask richiedono molta RAM.
    # Se il test fallisce o il PC si blocca, riduci a [0, 10, 50]
    levels = [0, 50, 100]

    output = {
        "test_name": "control_plane_overhead_real_app",
        "description": "Resource consumption of 'dockerd' with REAL Backend containers",
        "results": []
    }

    print("--- Resource Overhead Test (Real Backend) ---")

    driver.reset_cluster()

    for count in levels:
        print(f"\n[TEST] Scaling Backend to {count} replicas...")

        driver.scale_service(config.SERVICE_NAME, count)

        if count > 0:
            print(f"[TEST] Waiting for convergence...")
            while True:
                current, desired = driver.get_replica_count(config.SERVICE_NAME)
                if current == count:
                    break
                time.sleep(2)

            print(f"[TEST] {count} backend.yml containers running.")
            # Pausa più lunga per far stabilizzare i processi Python che partono
            print("[TEST] Stabilizing (10s)...")
            time.sleep(10)
        else:
            print("[TEST] Baseline (0 containers). Stabilizing...")
            time.sleep(5)

        # 3. MISURAZIONE
        print("[TEST] Monitoring 'dockerd' resources (10s)...")
        stats = monitor_resources()

        if stats:
            print(f"-> Result: CPU {stats['avg_cpu_percent']}% | RAM {stats['avg_ram_mb']} MB")
            output["results"].append({
                "container_count": count,
                "dockerd_stats": stats
            })


    os.makedirs("results", exist_ok=True)
    outfile = "results/resource_overhead.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[TEST] Completed. JSON saved to {outfile}")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("[WARNING] This script might need 'sudo' to read dockerd stats accurately.")
        print("          Try: sudo ./venv/bin/python3 tests/resource_overhead.py")
    test_resource_overhead()