import requests
import subprocess
import time
import json

BASE_URL = "http://localhost:5001"
ASSIGNMENT_URL = f"{BASE_URL}/assignments"
STACK_NAME = "cob-service"


def get_db_service_name():
    """Get the database service name in Docker Swarm"""
    return f"{STACK_NAME}_db"


def get_db_container_id():
    """Get the container ID of the database service"""
    cmd = f"docker ps --filter name={get_db_service_name()} --format {{{{.ID}}}}"
    try:
        output = subprocess.check_output(cmd, shell=True).decode().strip()
        return output.split('\n')[0] if output else None
    except Exception as e:
        print(f"Error getting container ID: {e}")
        return None



def run_persistence_test():
    print("Starting persistence test")
    payload = {
        "title": "Persistence Test Assignment",
        "description": "Data must survive container death",
        "due_date": "2025-12-31T23:59:59Z"
    }
    try:
        resp = requests.post(ASSIGNMENT_URL, json=payload)
        if resp.status_code != 201:
            print(resp.status_code)
            return

        data = resp.json()
        assignment_id = data.get('_id')
        print(f"Assignment ID: {assignment_id}")

    except Exception as e:
        print(f"Error {e}")
        return

    db_container = get_db_container_id()
    if not db_container:
        print("No DB container found")
        return

    #Killing db
    subprocess.run(f"docker kill {db_container}", shell=True)
    time.sleep(2)

    max_wait = 60
    start_time = time.time()

    while time.time() < start_time + max_wait:
        new_container = get_db_container_id()
        if new_container and new_container != db_container:
            print(f"New database container started: {new_container}")
            break
        time.sleep(2)
    else:
        print("Database did not restart in time")
        return

    time.sleep(10)

    try:
        check_resp = requests.get(f"{ASSIGNMENT_URL}/{assignment_id}")

        if check_resp.status_code == 200:
            print("SUCCESS: Data persisted after container destruction!")
            print(f"   Retrieved data: {check_resp.json()['title']}")
        elif check_resp.status_code == 404:
            print("FAILURE: Assignment no longer exists. Volume did not work.")
        else:
            print(f"Unexpected error: {check_resp.status_code}")

    except Exception as e:
        print(f"Verification error: {e}")


if __name__ == "__main__":
    run_persistence_test()