import time
import subprocess
import requests
import json

# Configurazione
SERVICE_URL = "http://192.168.15.9:5001"  # Endpoint Backend
SERVICE_NAME = "cob-service_backend"


def run_test():
    results = {}

    print(f"--- Inizio Test Resilienza: {SERVICE_NAME} ---")

    # 1. Check Baseline
    try:
        resp = requests.get(SERVICE_URL, timeout=2)
        if resp.status_code != 200:
            raise Exception("Il servizio non risponde correttamente all'avvio.")
    except Exception as e:
        print(f"Errore iniziale: {e}")
        return

    # 2. Identifica un Container ID locale (sul manager) da uccidere
    # Nota: In produzione reale, si userebbe SSH per uccidere su worker remoti.
    # Qui cerchiamo un container locale per semplicità.
    try:
        cmd = f"docker ps --filter name={SERVICE_NAME} --format '{{{{.ID}}}}'"
        container_id = subprocess.check_output(cmd, shell=True).decode().strip().split('\n')[0]
    except:
        container_id = None

    start_time = time.time()

    if container_id:
        print(f"Killing container locale: {container_id}")
        subprocess.run(f"docker kill {container_id}", shell=True, stdout=subprocess.DEVNULL)
    else:
        print("Nessun container locale trovato. Simulo crash forzando update di una replica...")
        # Simula crash riavviando forzatamente
        subprocess.run(f"docker service update --force {SERVICE_NAME}", shell=True, stdout=subprocess.DEVNULL)

    kill_time = time.time()

    # 3. Polling per il recupero
    downtime_start = kill_time
    recovered = False
    failed_requests = 0

    while not recovered:
        try:
            resp = requests.get(SERVICE_URL, timeout=1)
            if resp.status_code == 200:
                recovered = True
            else:
                failed_requests += 1
                time.sleep(0.1)
        except:
            failed_requests += 1
            time.sleep(0.1)

        # Timeout di sicurezza 60 secondi
        if (time.time() - kill_time) > 60:
            break

    end_time = time.time()

    results = {
        "test_name": "Resilience Test",
        "mttr_seconds": round(end_time - kill_time, 4),  # Mean Time To Recovery
        "failed_requests_count": failed_requests,
        "service_status": "Recovered" if recovered else "Failed"
    }

    print("\nRISULTATO TEST RESILIENZA:")
    print(json.dumps(results, indent=4))


if __name__ == "__main__":
    run_test()