import time
import requests
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
from drivers.swarm_driver import SwarmDriver
import config

def test_scheduling():
    driver = SwarmDriver(config.STACK_NAME)
    target = 10  # Ora possiamo osare 10 perché abbiamo tolto i limiti!

    # Reset iniziale
    driver.scale_service(config.SERVICE_NAME, 0)
    time.sleep(5)

    print(f"--- Scheduling Overhead (Target: {target}) ---")
    start = time.time()

    driver.scale_service(config.SERVICE_NAME, target)

    # Polling HTTP (Black Box)
    active = 0
    while active < target:
        try:
            unique_ids = set()
            # Fai più richieste delle repliche attese per beccarle tutte
            for _ in range(target * 3):
                resp = requests.get(config.API_URL, timeout=1)
                if resp.status_code == 200:
                    unique_ids.add(resp.json().get('container_id'))
            active = len(unique_ids)
            print(f"Active: {active}/{target}")
            if active == target: break
        except:
            pass
        time.sleep(0.5)

    duration = time.time() - start
    print(f"RESULT: {duration:.2f} seconds")


if __name__ == "__main__":
    test_scheduling()