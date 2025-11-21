import requests
import time
import subprocess
import sys

URL = "http://localhost:5001/"
SERVICE_FILTER = "cob-service_backend"


def get_backend_container_ids():
    """Get ONLY backend container IDs using a stricter filter"""
    try:
        cmd = f"docker ps --filter name={SERVICE_FILTER} --filter status=running --format {{{{.ID}}}}"
        output = (subprocess.check_output(cmd, shell=True)
                  .decode().strip().split("\n"))
        return [c for c in output if c]
    except Exception as e:
        print(f"Failed to get backend container IDs: {e}")
        return []


def run_fault_tolerance_test():
    print("Starting Swarm Healing Time test...")

    initial_ids = get_backend_container_ids()
    if not initial_ids:
        print("No backend containers found. Is the stack running?")
        return

    initial_count = len(initial_ids)
    print(f"Initial replicas: {initial_count} -> IDs: {initial_ids}")

    target_container = initial_ids[0]
    print(f"Killing container: {target_container}")
    subprocess.run(f"docker kill {target_container}", shell=True, stdout=subprocess.DEVNULL)

    start_time = time.time()
    new_container_id = None
    timeout = 30  # timeout
    elapsed = 0

    while elapsed < timeout:
        current_ids = get_backend_container_ids()

        if len(current_ids) == initial_count and target_container not in current_ids:
            for cid in current_ids:
                if cid not in initial_ids:
                    new_container_id = cid
                    break

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