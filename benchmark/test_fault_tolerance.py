import requests
import time
import subprocess
import sys

URL = "http://localhost:5001/"
STACK_NAME = "cob-service"
# Specifica il nome del servizio backend come definito nello stack (solitamente stackname_servicename)
SERVICE_FILTER = f"{STACK_NAME}_backend"


def get_backend_container_ids():
    """Get ONLY backend container IDs using a stricter filter"""
    try:
        # CORREZIONE 1: Aggiunto filtro più specifico (name=cob-service_backend)
        # Usa -q per quiet (solo ID) e filtra solo i running
        cmd = f"docker ps --filter name={SERVICE_FILTER} --filter status=running --format {{{{.ID}}}}"
        output = (subprocess.check_output(cmd, shell=True)
                  .decode().strip().split("\n"))
        # Rimuove stringhe vuote se non ci sono container
        return [c for c in output if c]
    except Exception as e:
        print(f"Failed to get backend container IDs: {e}")
        return []


def run_fault_tolerance_test():
    print("Starting Swarm Healing Time test...")

    # 1. Ottieni stato iniziale
    initial_ids = get_backend_container_ids()
    if not initial_ids:
        print("No backend containers found. Is the stack running?")
        return

    initial_count = len(initial_ids)
    print(f"Initial replicas: {initial_count} -> IDs: {initial_ids}")

    # 2. Scegli vittima e uccidi
    target_container = initial_ids[0]
    print(f"Killing container: {target_container}")
    subprocess.run(f"docker kill {target_container}", shell=True, stdout=subprocess.DEVNULL)

    start_time = time.time()

    # 3. Loop di attesa (Misura il tempo di rigenerazione di Swarm)
    # CORREZIONE 2: Non controlliamo l'HTTP 200, ma lo stato del cluster
    print("Waiting for Swarm to provision new replica...")

    new_container_id = None
    timeout = 30  # timeout di sicurezza
    elapsed = 0

    while elapsed < timeout:
        current_ids = get_backend_container_ids()

        # Condizione di successo:
        # A. Siamo tornati al numero originale di repliche
        # B. La lista degli ID è diversa (il vecchio è morto, uno nuovo è nato)
        if len(current_ids) == initial_count and target_container not in current_ids:
            # Troviamo chi è il nuovo
            for cid in current_ids:
                if cid not in initial_ids:
                    new_container_id = cid
                    break

            # Se abbiamo trovato il nuovo, usciamo dal loop
            if new_container_id:
                break

        time.sleep(0.5)
        elapsed = time.time() - start_time

    recovery_time = time.time() - start_time

    if new_container_id:
        print(f"\nRECOVERY COMPLETE")
        print(f"Swarm Healing Time: {recovery_time:.4f} seconds")
        print(f"New Container ID: {new_container_id}")
        print(f"Current Backend IDs: {current_ids}")
    else:
        print(f"\nTimeout reached. Swarm did not recover in {timeout}s.")


if __name__ == "__main__":
    run_fault_tolerance_test()