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
from drivers.nomad_driver import NomadDriver  # <--- USIAMO NOMAD

# Il processo da monitorare. In Nomad è un unico binario "nomad".
TARGET_PROCESS_NAME = "nomad"


def get_process_stats(process_name_substr):
    """
    Cerca il processo che contiene 'process_name_substr' nel nome
    e restituisce le statistiche aggregate (CPU e RAM).
    """
    total_cpu = 0.0
    total_mem = 0.0
    found = False

    # Iteriamo su tutti i processi
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # Check se il nome coincide (es. "nomad")
            if process_name_substr in proc.info['name']:
                p = psutil.Process(proc.info['pid'])

                # CPU percent (intervallo breve per campionamento istantaneo)
                # Nota: cpu_percent può essere > 100% su multicore
                total_cpu += p.cpu_percent(interval=0.1)

                # RSS Memory in MB
                total_mem += p.memory_info().rss / (1024 * 1024)
                found = True

                # Nomad è un singolo binario go, solitamente basta il padre.
                # Se ci sono processi figli forkati, potremmo volerli sommare,
                # ma per Nomad tipicamente il processo principale è quello che conta.
                # Rimuovi il break se vuoi sommare eventuali figli (raro per nomad agent).
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if not found:
        return None

    return {"cpu": total_cpu, "ram_mb": total_mem}


def monitor_resources(duration_sec=10):
    cpus = []
    mems = []

    print(f"[MONITOR] Sampling resources for process '{TARGET_PROCESS_NAME}'...")
    start = time.time()

    while time.time() - start < duration_sec:
        stats = get_process_stats(TARGET_PROCESS_NAME)
        if stats:
            cpus.append(stats['cpu'])
            mems.append(stats['ram_mb'])
        else:
            print(f"[WARNING] Process '{TARGET_PROCESS_NAME}' not found! Are you running this on a Nomad node?")

        time.sleep(1)  # Campiona ogni secondo

    if not cpus:
        return None

    return {
        "avg_cpu_percent": round(statistics.mean(cpus), 2),
        "avg_ram_mb": round(statistics.mean(mems), 2)
    }


def test_resource_overhead():
    driver = NomadDriver()

    # Livelli di carico: 0 (Baseline), 50, 100 container
    levels = [0, 50, 100]

    output = {
        "test_name": "control_plane_overhead_nomad",
        "description": f"Resource consumption of '{TARGET_PROCESS_NAME}' daemon with increasing task count",
        "results": []
    }

    print(f"--- Resource Overhead Test (Nomad - Process: {TARGET_PROCESS_NAME}) ---")

    # 1. Reset iniziale
    driver.reset_cluster()

    # Identifichiamo il servizio da scalare (backend è ideale perché leggero)
    service_to_scale = "backend"

    for count in levels:
        print(f"\n[TEST] Scaling {service_to_scale} to {count} replicas...")

        # Scaliamo usando il driver Nomad
        driver.scale_service(service_to_scale, count)

        if count > 0:
            print(f"[TEST] Waiting for convergence...")
            waited = 0
            # Attesa attiva che i task siano Running
            while waited < 120:
                curr, des = driver.get_replica_count(service_to_scale)

                # Feedback visivo
                sys.stdout.write(f"\r   Status: {curr}/{count} running...")
                sys.stdout.flush()

                if curr >= count:
                    print("")  # Newline
                    break
                time.sleep(2)
                waited += 2

            if waited >= 120:
                print("\n[WARNING] Timeout waiting for replicas (proceeding anyway)")

            print(f"[TEST] {curr} tasks running.")
            print("[TEST] Stabilizing (15s)...")
            time.sleep(15)
        else:
            # Caso 0 repliche (Baseline)
            print("[TEST] Baseline (0 tasks). Stabilizing...")
            # Assicuriamoci che sia davvero a 0
            curr, _ = driver.get_replica_count(service_to_scale)
            if curr > 0:
                print(f"[WARN] Expected 0 but found {curr}, forcing wait...")
                time.sleep(10)
            time.sleep(10)

        # 2. MISURAZIONE RISORSE
        # Misuriamo quanto consuma il processo Nomad su QUESTA macchina
        # (Idealmente questo script gira sul Manager o su un nodo rappresentativo)
        print("[TEST] Measuring Overhead...")
        stats = monitor_resources(duration_sec=10)

        if stats:
            print(f"-> Result: CPU {stats['avg_cpu_percent']}% | RAM {stats['avg_ram_mb']} MB")
            output["results"].append({
                "container_count": count,
                "process_stats": stats
            })
        else:
            print("[ERROR] Could not measure stats. Check permissions (sudo?) or process name.")

    # Save Results
    os.makedirs("results", exist_ok=True)
    outfile = "results/resource_overhead_nomad.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[TEST] Completed. JSON saved to {outfile}")


if __name__ == "__main__":
    # Controllo root (necessario per psutil su processi di sistema)
    if os.geteuid() != 0:
        print("[WARNING] You are not root. psutil might fail to read process stats for 'nomad'.")
        print(f"          Try: sudo {sys.executable} tests/resource_overhead.py")

    test_resource_overhead()