import subprocess
import time
import os

TESTS = [
    "tests/scheduling_overhead.py",
    "tests/scalability_load_balancing.py",
    "tests/rolling_update.py",
    "tests/fault_tolerance.py",
    "tests/resource_overhead.py"
]


def run_suite():
    print("==========================================")
    print("STARTING BENCHMARK SUITE (SWARM)")
    print("==========================================")

    os.makedirs("results", exist_ok=True)

    for script in TESTS:
        print(f"\n>>>> RUNNING {script} <<<<")
        try:
            # Esegue lo script python come sottoprocesso
            subprocess.run(["python3", script], check=True)
            time.sleep(5)  # Pausa tra test per cleanup
        except subprocess.CalledProcessError as e:
            print(f"!!!! TEST FAILED: {script} !!!!")
        except Exception as e:
            print(f"ERROR: {e}")

    print("\n==========================================")
    print("SUITE COMPLETED. CHECK JSON FILES.")
    print("==========================================")


if __name__ == "__main__":
    run_suite()