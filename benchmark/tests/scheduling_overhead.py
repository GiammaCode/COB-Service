import time
import sys
import os
import json

# Setup path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# Local imports
import config
from drivers.k8s_driver import K8sDriver

DUMMY_SERVICE_NAME = "benchmark-dummy"
LEVELS = [10, 50, 100]
TIMEOUT_SECONDS = 120

def test_scheduling():
    #driver = SwarmDriver(config.STACK_NAME)
    driver = K8sDriver()

    output = {
        "test_name": "scheduling_overhead_burst_k8s",
        "description": "Time to schedule N lightweight containers (Alpine) on Kubernetes",
        "results": []
    }

    print("--- Scheduling Overhead Test (Burst) ---")

    # Clean start
    driver.reset_cluster()
    # Also ensure dummy service is gone from previous failed runs
    driver.remove_service(DUMMY_SERVICE_NAME)

    for target in LEVELS:
        print(f"\n[TEST] Testing burst of {target} containers...")

        # Create Deployment (Start Timer)
        # K8s is async: the command returns immediately after creating the Deployment object.
        # The scheduler starts working afterwards.
        start_time = time.time()
        driver.create_dummy_service(DUMMY_SERVICE_NAME, target)

        # 2. Polling for 'Running'
        while True:
            running = driver.count_running_tasks(DUMMY_SERVICE_NAME)

            sys.stdout.write(f"\r[POLLING] Active: {running}/{target}")
            sys.stdout.flush()

            if running >= target:
                end_time = time.time()
                print("")
                break

            # safety timeout
            if time.time() - start_time > TIMEOUT_SECONDS:
                print(f"\n[WARNING] Timeout reached! Only {running}/{target} started.")
                end_time = time.time()
                break

            time.sleep(0.2)

        duration = end_time - start_time
        rate = target / duration if duration > 0 else 0

        print(f"\n-> Result: {target} containers in {duration:.3f}s")
        print(f"-> Rate: {rate:.2f} containers/sec")

        output["results"].append({
            "containers": target,
            "total_time_seconds": round(duration, 4),
            "avg_time_per_container": round(duration / target, 4),
            "containers_per_second": round(rate, 2)
        })

        # Cleanup
        driver.remove_service(DUMMY_SERVICE_NAME)

        print("[TEST] Cooling down (15s)...")
        time.sleep(15)

    # Save res
    os.makedirs("results", exist_ok=True)
    outfile = "results/scheduling_overhead.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[TEST] Completed. JSON saved to {outfile}")


if __name__ == "__main__":
    test_scheduling()