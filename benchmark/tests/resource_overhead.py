import time
import sys
import os
import json
import psutil
import statistics

# set up path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# Local imports
import config
from drivers.k8s_driver import K8sDriver

TARGET_PROCESS_NAME = "k3s"

def get_process_stats(process_name_substr):
    """
    search 'process_name_substr'
    and return aggregate statistics (with children processes).
    """
    total_cpu = 0.0
    total_mem = 0.0
    found = False
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # Check if name matches (e.g. "k3s" or "k3s-server")
            if process_name_substr in proc.info['name']:
                p = psutil.Process(proc.info['pid'])

                # CPU percent
                total_cpu += p.cpu_percent(interval=0.1)
                # RSS Memory in MB
                total_mem += p.memory_info().rss / (1024 * 1024)
                found = True

                # Se troviamo il processo principale, spesso basta quello.
                # Se vogliamo sommare tutto, togliamo il break.
                # Per stabilità, prendiamo il primo match "principale" (spesso root)
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if not found:
        return None

    return {"cpu": total_cpu, "ram_mb": total_mem}

def monitor_resources(duration_sec=10):
    cpus = []
    mems = []

    print(f"[MONITOR] Sampling resources for process containing '{TARGET_PROCESS_NAME}'...")
    start = time.time()

    while time.time() - start < duration_sec:
        stats = get_process_stats(TARGET_PROCESS_NAME)
        if stats:
            cpus.append(stats['cpu'])
            mems.append(stats['ram_mb'])
        else:
            print(f"[WARNING] Process '{TARGET_PROCESS_NAME}' not found!")

        time.sleep(1)  # Campiona ogni secondo

    if not cpus:
        return None

    return {
        "avg_cpu_percent": round(statistics.mean(cpus), 2),
        "avg_ram_mb": round(statistics.mean(mems), 2)
    }


def test_resource_overhead():
    #driver = SwarmDriver(config.STACK_NAME)
    driver = K8sDriver()

    levels = [0, 50, 100]

    output = {
        "test_name": "control_plane_overhead",
        "description": f"Resource consumption of '{TARGET_PROCESS_NAME}' daemon with increasing pod count",
        "results": []
    }

    print(f"--- Resource Overhead Test (K8s - {TARGET_PROCESS_NAME}) ---")

    driver.reset_cluster()

    for count in levels:
        print(f"\n[TEST] Scaling Backend to {count} replicas...")

        driver.scale_service(config.SERVICE_NAME, count)

        if count > 0:
            print(f"[TEST] Waiting for convergence...")
            waited = 0
            while waited < 120:
                curr, des = driver.get_replica_count(config.SERVICE_NAME)
                if curr == count:
                    break
                time.sleep(2)
                waited += 2

            if waited >= 120:
                print("[WARNING] Timeout waiting for replicas (proceeding anyway)")

            print(f"[TEST] {count} pods running.")
            print("[TEST] Stabilizing (15s)...")
            time.sleep(15)
        else:
            print("[TEST] Baseline (0 pods). Stabilizing...")
            time.sleep(10)

        # 2. MISURAZIONE
        print("[TEST] Measuring Overhead...")
        stats = monitor_resources(duration_sec=10)

        if stats:
            print(f"-> Result: CPU {stats['avg_cpu_percent']}% | RAM {stats['avg_ram_mb']} MB")
            output["results"].append({
                "container_count": count,
                "process_stats": stats
            })
        else:
            print("[ERROR] Could not measure stats.")

    # Save Results
    os.makedirs("results", exist_ok=True)
    outfile = "results/resource_overhead_k8s.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[TEST] Completed. JSON saved to {outfile}")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("[WARNING] You are not root. psutil might fail to read process stats.")
        print(f"          Try: sudo {sys.executable} tests/resource_overhead.py")

    test_resource_overhead()