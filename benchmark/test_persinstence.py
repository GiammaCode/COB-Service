import requests
import subprocess
import time
import json

BASE_URL = "http://localhost:5001"
ASSIGNMENT_URL = f"{BASE_URL}/assignments"


def get_mongo_container():
    cmd = "docker ps --filter name=db --format {{.ID}}"
    return subprocess.check_output(cmd, shell=True).decode().strip()


def run_persistence_test():
    print("--- Inizio Test Data Persistence ---")

    # 1. Creazione Dato
    print("📝 Creazione nuovo assignment...")
    payload = {
        "title": "Persistence Test Assignment",
        "description": "Data must survive container death",
        "due_date": "2025-12-31T23:59:59Z"
    }
    try:
        resp = requests.post(ASSIGNMENT_URL, json=payload)
        if resp.status_code != 201:
            print(f"❌ Errore creazione assignment: {resp.text}")
            return

        data = resp.json()
        assignment_id = data.get('_id') or data.get('id')  # Gestisce ObjectId
        print(f"✅ Assignment creato con ID: {assignment_id}")

    except Exception as e:
        print(f"❌ Errore connessione: {e}")
        return

    # 2. Distruzione Database
    db_container = get_mongo_container()
    print(f"💣 KILLING Database container {db_container}...")
    subprocess.run(f"docker rm -f {db_container}", shell=True)

    print("😴 Attesa (il sistema è senza DB)...")
    time.sleep(2)

    # 3. Ripristino Database
    print("♻️ Ricreazione container DB (docker-compose up)...")
    subprocess.run("docker-compose up -d db", shell=True)

    print("⏳ Attesa boot database (10s)...")
    time.sleep(10)  # Mongo ci mette un po' a partire

    # 4. Verifica Esistenza Dati
    print(f"🔍 Verifica esistenza assignment {assignment_id}...")
    try:
        check_resp = requests.get(f"{ASSIGNMENT_URL}/{assignment_id}")

        if check_resp.status_code == 200:
            print("✅ SUCCESS: I dati sono persistiti dopo la distruzione del container!")
            print(f"   Dati recuperati: {check_resp.json()['title']}")
        elif check_resp.status_code == 404:
            print("❌ FAILURE: L'assignment non esiste più. Il volume non ha funzionato.")
        else:
            print(f"⚠️ Errore inaspettato: {check_resp.status_code}")

    except Exception as e:
        print(f"❌ Errore verifica: {e}")


if __name__ == "__main__":
    run_persistence_test()