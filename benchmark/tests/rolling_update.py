import time
import requests
import threading
import sys
import os
import json

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
import config
from drivers.swarm_driver import SwarmDriver


def test_rolling_update():
    driver = SwarmDriver(config.STACK_NAME)
    print("--- Rolling Update Test ---")

    driver.scale_service(config.SERVICE_NAME, 3)
    time.sleep(5)

    errors = 0
    total = 0
    stop_load = False

    def background_traffic():
        nonlocal errors, total
        while not stop_load:
            try:
                if requests.get(config.API_URL, timeout=1).status_code != 200:
                    errors += 1
            except:
                errors += 1
            total += 1
            time.sleep(0.1)

    t = threading.Thread(target=background_traffic)
    t.start()

    # Trigger Update
    # Usiamo --force per simulare un update anche se l'immagine è la stessa
    print("[TEST] Updating service (force update)...")
    update_start = time.time()
    driver.update_image(config.SERVICE_NAME, "192.168.15.9:5000/cob-service-backend:latest")

    # Attendiamo abbastanza per il rolling (10s delay * 3 repliche = ~30s)
    time.sleep(40)

    stop_load = True
    t.join()

    update_duration = time.time() - update_start
    success_rate = ((total - errors) / total) * 100 if total > 0 else 0

    print(f"-> Update Duration: {update_duration:.2f}s")
    print(f"-> Success Rate: {success_rate:.2f}% ({errors} failures)")

    res = {
        "test_name": "rolling_update",
        "duration": update_duration,
        "success_rate": success_rate,
        "total_reqs": total,
        "failed_reqs": errors
    }

    os.makedirs("results", exist_ok=True)
    with open("results/rolling_update.json", "w") as f:
        json.dump(res, f, indent=2)


if __name__ == "__main__":
    test_rolling_update()