import requests
import threading
import time
import subprocess
import sys
import json

# Configuration
URL = "http://localhost:5001/"
STACK_NAME = "cob-service"
SERVICE_NAME = f"{STACK_NAME}_backend"

# Global stats
errors = 0
total_reqs = 0
running = True


def log(message):
    print(message, file=sys.stderr)


def load_generator():
    """Generate constant background traffic"""
    global errors, total_reqs
    while running:
        try:
            resp = requests.get(URL, timeout=1)
            if resp.status_code != 200:
                errors += 1
        except Exception:
            errors += 1

        total_reqs += 1
        time.sleep(0.1)


def get_service_image():
    cmd = f"docker service inspect {SERVICE_NAME} --format '{{{{.Spec.TaskTemplate.ContainerSpec.Image}}}}'"
    try:
        return subprocess.check_output(cmd, shell=True).decode().strip()
    except:
        return None


def run_rolling_update_test():
    global running
    log("--- Starting Rolling Update Test ---")

    current_image = get_service_image()
    if not current_image:
        print(json.dumps({"status": "failed", "error": "Could not get service image"}))
        return

    log(f"Current image: {current_image}")

    # Start load
    t = threading.Thread(target=load_generator)
    t.start()
    time.sleep(2)

    # Update
    log("Triggering update...")
    update_cmd = f"docker service update --force {SERVICE_NAME}"
    subprocess.run(update_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    start_update = time.time()
    update_success = False

    while True:
        time.sleep(1)
        inspect_cmd = f"docker service inspect {SERVICE_NAME} --format '{{{{.UpdateStatus.State}}}}'"
        try:
            state = subprocess.check_output(inspect_cmd, shell=True).decode().strip()
            if state == "completed":
                update_success = True
                break
            elif state in ["paused", "rollback"]:
                break
        except:
            pass

        if time.time() - start_update > 60:
            log("Update timeout")
            break

    update_duration = time.time() - start_update

    # Cooldown
    time.sleep(2)
    running = False
    t.join()

    failure_rate = (errors / total_reqs * 100) if total_reqs > 0 else 0

    # Define success criteria (e.g., < 1% error rate)
    status = "passed" if update_success and failure_rate < 1.0 else "failed"

    result = {
        "test_name": "rolling_update",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
        "metrics": {
            "total_requests": total_reqs,
            "failed_requests": errors,
            "failure_rate_percent": round(failure_rate, 2),
            "update_duration_seconds": round(update_duration, 2),
            "update_state_final": "completed" if update_success else "failed"
        }
    }

    print(json.dumps(result))


if __name__ == "__main__":
    run_rolling_update_test()