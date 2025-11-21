import requests
import threading
import time
import subprocess

URL = "http://localhost:5001/"
STACK_NAME = "cob-service"
SERVICE_NAME = f"{STACK_NAME}_backend"
DURATION_SECONDS = 15
errors = 0
total_reqs = 0
running = True


def load_generator():
    """Generate constant background traffic"""
    global errors, total_reqs
    while running:
        try:
            resp = requests.get(URL, timeout=1)
            if resp.status_code != 200:
                errors += 1
                print(f"HTTP Error {resp.status_code}")
        except Exception as e:
            errors += 1
            print(f"Connection Error: {e}")

        total_reqs += 1
        time.sleep(0.1)

def get_service_image():
    """Get service image"""
    cmd = f"docker service inspect {SERVICE_NAME} --format '{{{{.Spec.TaskTemplate.ContainerSpec.Image}}}}'"
    try:
        return subprocess.check_output(cmd, shell=True).decode().strip()
    except:
        return None


def run_rolling_update_test():
    global running
    print("--- Starting Rolling Update Test ---")

    # Get current image
    current_image = get_service_image()
    if not current_image:
        print("Could not get service image")
        return

    print(f"Current image: {current_image}")

    # Start load generation
    print("Starting continuous traffic...")
    t = threading.Thread(target=load_generator)
    t.start()

    time.sleep(2)  # Let traffic stabilize

    # Trigger Rolling Update
    print("Starting rolling update procedure...")

    # Force update with same image to trigger rolling restart
    update_cmd = f"docker service update --force {SERVICE_NAME}"
    subprocess.run(update_cmd, shell=True, capture_output=True)

    # Monitor update progress
    print("Monitoring update progress...")
    start_update = time.time()

    while True:
        time.sleep(1)
        # Check if update is complete
        inspect_cmd = f"docker service inspect {SERVICE_NAME} --format '{{{{.UpdateStatus.State}}}}'"
        try:
            state = subprocess.check_output(inspect_cmd, shell=True).decode().strip()
            if state == "completed":
                break
            elif state == "paused" or state == "rollback":
                print(f"Update state: {state}")
                break
        except:
            pass

        if time.time() - start_update > 60:
            print("Update timeout")
            break

    update_duration = time.time() - start_update
    print(f"Update completed in {update_duration:.2f} seconds")

    # Continue traffic for a bit more
    time.sleep(2)

    # Stop traffic
    running = False
    t.join()

    print("\n--- Results ---")
    print(f"Total Requests: {total_reqs}")
    print(f"Failed Requests: {errors}")

    if errors == 0:
        print("SUCCESS: Zero-downtime update achieved!")
    else:
        failure_rate = (errors / total_reqs) * 100
        print(f"FAILURE: Error rate of {failure_rate:.2f}% during update.")
        if failure_rate < 5:
            print("Note: Low error rate may be acceptable for rolling updates")


if __name__ == "__main__":
    run_rolling_update_test()


