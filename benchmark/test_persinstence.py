import requests
import subprocess
import time
import json
import sys

BASE_URL = "http://localhost:5001"
ASSIGNMENT_URL = f"{BASE_URL}/assignments"
STACK_NAME = "cob-service"


def log(message):
    print(message, file=sys.stderr)


def get_db_container_id():
    cmd = f"docker ps --filter name={STACK_NAME}_db --format {{{{.ID}}}}"
    try:
        output = subprocess.check_output(cmd, shell=True).decode().strip()
        return output.split('\n')[0] if output else None
    except Exception:
        return None


def run_persistence_test():
    log("Starting persistence test...")

    payload = {
        "title": "Persistence Test Data",
        "description": "Data survival test",
        "due_date": "2025-12-31T23:59:59Z"
    }

    result = {
        "test_name": "data_persistence",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "failed",  # default
        "metrics": {}
    }

    # 1. Create Data
    try:
        resp = requests.post(ASSIGNMENT_URL, json=payload)
        if resp.status_code != 201:
            result["error"] = f"API Error {resp.status_code}"
            print(json.dumps(result))
            return
        assignment_id = resp.json().get('_id')
    except Exception as e:
        result["error"] = str(e)
        print(json.dumps(result))
        return

    # 2. Kill DB
    db_container = get_db_container_id()
    if db_container:
        log(f"Killing DB container: {db_container}")
        subprocess.run(f"docker kill {db_container}", shell=True, stdout=subprocess.DEVNULL)
    else:
        result["error"] = "DB container not found"
        print(json.dumps(result))
        return

    # 3. Wait for restart
    log("Waiting for DB restart...")
    time.sleep(2)  # Initial pause
    restarted = False
    for _ in range(30):
        new_id = get_db_container_id()
        if new_id and new_id != db_container:
            restarted = True
            break
        time.sleep(1)

    if not restarted:
        result["error"] = "DB did not restart"
        print(json.dumps(result))
        return

    # 4. Verify Data
    time.sleep(5)  # Wait for Mongo internal startup
    try:
        check_resp = requests.get(f"{ASSIGNMENT_URL}/{assignment_id}")
        if check_resp.status_code == 200:
            result["status"] = "passed"
            result["metrics"]["data_retrieved"] = True
            log("Success: Data survived.")
        else:
            result["metrics"]["data_retrieved"] = False
            result["error"] = f"Data missing. HTTP {check_resp.status_code}"
    except Exception as e:
        result["error"] = f"Verification failed: {e}"

    print(json.dumps(result))


if __name__ == "__main__":
    run_persistence_test()