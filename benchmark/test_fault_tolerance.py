import subprocess
import time
import sys
import json

# Configuration
STACK_NAME = "cob-service"
SERVICE_FILTER = f"{STACK_NAME}_backend"

def log(message):
    """Print to stderr so it does not interfere with JSON output"""
    print(message, file=sys.stderr)

def get_backend_container_ids():
    """Get ONLY backend container IDs using a stricter filter"""
    try:
        cmd = f"docker ps --filter name={SERVICE_FILTER} --filter status=running --format {{{{.ID}}}}"
        output = (subprocess.check_output(cmd, shell=True)
                  .decode().strip().split("\n"))
        return [c for c in output if c]
    except Exception as e:
        log(f"Failed to get backend container IDs: {e}")
        return []

def run_fault_tolerance_test():
    log("Starting Swarm Healing Time test...")

    initial_ids = get_backend_container_ids()
    if not initial_ids:
        print(json.dumps({
            "status": "failed",
            "error": "No backend containers found",
            "metrics": {}
        }))
        return

    initial_count = len(initial_ids)
    log(f"Initial replicas: {initial_count} -> IDs: {initial_ids}")

    target_container = initial_ids[0]
    log(f"Killing container: {target_container}")
    subprocess.run(f"docker kill {target_container}", shell=True, stdout=subprocess.DEVNULL)

    start_time = time.time()
    new_container_id = None
    timeout = 30
    elapsed = 0

    while elapsed < timeout:
        current_ids = get_backend_container_ids()

        # Check if count is restored AND the killed container is gone
        if len(current_ids) == initial_count and target_container not in current_ids:
            # Find the new ID
            for cid in current_ids:
                if cid not in initial_ids:
                    new_container_id = cid
                    break
            if new_container_id:
                break

        time.sleep(0.5)
        elapsed = time.time() - start_time

    recovery_time = time.time() - start_time

    result = {
        "test_name": "fault_tolerance",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metrics": {
            "initial_replicas": initial_count,
            "recovery_time_seconds": round(recovery_time, 4) if new_container_id else None,
            "killed_container": target_container,
            "new_container": new_container_id
        }
    }

    if new_container_id:
        log(f"Recovery Complete. Time: {recovery_time:.4f}s")
        result["status"] = "passed"
    else:
        log("Timeout reached.")
        result["status"] = "failed"
        result["error"] = "Swarm did not recover within timeout"

    # Output ONLY JSON to stdout
    print(json.dumps(result))

if __name__ == "__main__":
    run_fault_tolerance_test()