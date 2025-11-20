import requests
import time
import subprocess
import sys

URL = "http://localhost:5001/"

def get_backend_container_id():
    try:
        cmd =  "docker ps --filter name=backend --format {{.ID}}"
        output = (subprocess.check_output(cmd, shell=True)
                  .decode().strip().split("\n")[0])
        return output
    except Exception as e:
        print("Failed to get back container ID")
        return None

def run_fault_tolerance_test():
    print("Starting fault tolerance test")
    try:
        pre_check = requests.get(URL, timeout=2)
        if pre_check.status_code != 200:
            print("pre check failed")
            return
    except:
        print("Impossible connection to backend")

    container_id = get_backend_container_id()
    if not container_id:
        print("Container not found")
        return

    print(f"Target Container: {container_id}")

    # 2. Simulazione Guasto (Crash)
    print(f"KILLING container {container_id}...")
    subprocess.run(f"docker kill {container_id}", shell=True)

    start_downtime = time.time()

    # Simulazione Reazione Orchestratore (Restart)
    # In K8s/Swarm è automatico. Qui lo forziamo per misurare il tempo di boot del container.
    print("Orchestrator restarting container...")
    subprocess.run(f"docker start {container_id}", shell=True)
    ###############


    attempts = 0
    while True:
        try:
            resp = requests.get(URL, timeout=1)
            if resp.status_code == 200:
                end_downtime = time.time()
                break
        except requests.RequestException:
            pass

        time.sleep(0.2)
        attempts += 1
        if attempts > 100:  # Timeout sicurezza 20s
            print("Timeout: service is dead")
            return

    recovery_time = end_downtime - start_downtime
    print(f"Downtime: {recovery_time:.4f} seconds")


if __name__ == "__main__":
    run_fault_tolerance_test()