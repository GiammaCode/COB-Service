import requests
import threading
import time
import subprocess

URL = "http://localhost:5001/"
DURATION_SECONDS = 15
errors = 0
total_reqs = 0
running = True


def load_generator():
    """Genera traffico costante in background."""
    global errors, total_reqs
    while running:
        try:
            resp = requests.get(URL, timeout=1)
            if resp.status_code != 200:
                errors += 1
                print(f"❌ Errore HTTP {resp.status_code}")
        except Exception as e:
            errors += 1
            print(f"❌ Errore Connessione: {e}")

        total_reqs += 1
        time.sleep(0.1)


def run_rolling_update_test():
    global running
    print("--- Inizio Test Rolling Update (Simulato) ---")

    # 1. Prepariamo l'ambiente con 3 repliche per avere ridondanza
    print("configurazione cluster a 3 repliche...")
    subprocess.run("docker-compose up -d --scale backend=3", shell=True)
    time.sleep(5)  # wait for boot

    # 2. Avvia il carico
    print("🚀 Avvio traffico continuo...")
    t = threading.Thread(target=load_generator)
    t.start()

    # 3. Simula Rolling Update (Restart sequenziale)
    print("🔄 Inizio procedura di aggiornamento (Restart Sequenziale)...")

    # Ottieniamo la lista dei container
    cmd = "docker ps --filter name=backend --format {{.ID}}"
    containers = subprocess.check_output(cmd, shell=True).decode().strip().split('\n')

    for container in containers:
        if not container: continue
        print(f"   -> Riavvio replica {container}...")
        subprocess.run(f"docker restart {container}", shell=True)
        time.sleep(2)  # Attende che torni su prima di passare al prossimo

    # 4. Fine test
    time.sleep(2)
    running = False
    t.join()

    print("\n--- Risultati ---")
    print(f"Richieste Totali: {total_reqs}")
    print(f"Richieste Fallite: {errors}")

    if errors == 0:
        print("✅ SUCCESS: Zero-downtime update riuscito!")
    else:
        failure_rate = (errors / total_reqs) * 100
        print(f"⚠️ FAILURE: Tasso di errore del {failure_rate:.2f}% durante l'update.")

    # Cleanup
    subprocess.run("docker-compose up -d --scale backend=1", shell=True)


if __name__ == "__main__":
    run_rolling_update_test()