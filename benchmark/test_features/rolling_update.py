import time
import requests
import threading
from ..drivers.swarm_driver import SwarmDriver

def test_rolling_update():
    driver = SwarmDriver()
    driver.scale_service("backend", 3)
    time.sleep(5)

    print("--- Start Rolling Update ---")

    # Immagine fittizia o stessa immagine forzando redeploy
    # Su K8s useresti 'kubectl set image'
    # Per il test, possiamo usare un tag diverso se disponibile, o forzare update

    errors = 0
    total = 0

    def background_traffic():
        nonlocal errors, total
        while total < 200: # 200 richieste totali
            try:
                if requests.get("http://localhost:5001/", timeout=1).status_code != 200:
                    errors += 1
            except:
                errors += 1
            total += 1
            time.sleep(0.05)

    t = threading.Thread(target=background_traffic)
    t.start()

    # Trigger Update
    driver.update_image("backend", "192.168.15.9:5000/cob-service-backend:latest")

    t.join()

    success_rate = ((total - errors) / total) * 100
    print(f"Result: {success_rate:.2f}% Success Rate during update")

if __name__ == "__main__":
    test_rolling_update()