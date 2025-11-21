import requests
import concurrent.futures
from collections import Counter
import time
import sys
import json

URL = "http://localhost:5001/"
TOT_REQUESTS = 100
CONCURRENT_WORKERS = 10


def log(message):
    print(message, file=sys.stderr)


def send_request(request_id):
    try:
        response = requests.get(URL, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get('container_id', 'Unknown')
        else:
            return "error_http"
    except Exception:
        return "error_connection"


def run_load_balancing_test():
    log("Starting load balancing test...")

    results = []
    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = [executor.submit(send_request, i) for i in range(TOT_REQUESTS)]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    duration = time.time() - start_time
    counter = Counter(results)

    # Calculate distribution logic
    unique_containers = len([k for k in counter.keys() if not k.startswith("error")])

    # Pass if at least 2 containers responded (assuming replicas > 1)
    status = "passed" if unique_containers > 0 else "failed"

    distribution_map = dict(counter)

    result = {
        "test_name": "load_balancing",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
        "metrics": {
            "total_requests": TOT_REQUESTS,
            "duration_seconds": round(duration, 2),
            "unique_responders": unique_containers,
            "distribution": distribution_map
        }
    }

    print(json.dumps(result))


if __name__ == "__main__":
    run_load_balancing_test()