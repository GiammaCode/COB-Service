import time
import sys
import os
import json

# Setup path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

import config
from drivers.swarm_driver import SwarmDriver


def test_scheduling():
    driver = SwarmDriver(config.STACK_NAME)

    # Define load levels for the scheduler
    # 10: Warmup
    # 50: Medium load
    # 100: Burst (if hardware allows, otherwise reduce to 75)
    levels = [10, 50, 100]

    dummy_service = "benchmark_dummy"

    output = {
        "test_name": "scheduling_overhead_burst",
        "description": "Time to schedule N lightweight containers (Alpine)",
        "results": []
    }

    print("--- Scheduling Overhead Test (Burst) ---")

    driver.reset_cluster()

    for target in levels:
        print(f"\n[TEST] Testing burst of {target} containers...")

        # 1. Service creation (Start Timer)
        start_time = time.time()
        driver.create_dummy_service(dummy_service, target)

        # 2. Active polling to verify 'Running' state
        # We don't use HTTP, we check Docker directly
        while True:
            running = driver.count_running_tasks(dummy_service)
            # print(f"\rNodes Active: {running}/{target}", end="") # Uncomment to see live progress

            if running >= target:
                end_time = time.time()
                break

            # Safety timeout (60s)
            if time.time() - start_time > 60:
                print("\n[WARNING] Timeout reached!")
                end_time = time.time()
                break

            # Frequent polling but not too much to avoid clogging manager CPU
            time.sleep(0.2)

        duration = end_time - start_time
        print(f"\n-> Result: {target} containers in {duration:.3f}s")
        print(f"-> Rate: {target / duration:.2f} containers/sec")

        output["results"].append({
            "containers": target,
            "total_time_seconds": round(duration, 4),
            "avg_time_per_container": round(duration / target, 4),
            "containers_per_second": round(target / duration, 2)
        })

        # Immediate cleanup for the next level
        driver.remove_service(dummy_service)
        # Pause to let the cluster stabilize (network namespaces cleanup)
        print("[TEST] Cooling down (10s)...")
        time.sleep(10)

    # Saving
    os.makedirs("results", exist_ok=True)
    outfile = "results/scheduling_overhead.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[TEST] Completed. JSON saved to {outfile}")


if __name__ == "__main__":
    test_scheduling()