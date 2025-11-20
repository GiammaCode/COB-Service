from turtledemo.penrose import start

import requests
import concurrent.futures
from collections import Counter
import time

URL = "http://localhost:5001/"
TOT_REQUESTS = 100
CONCURRENT_WORKERS = 10

def send_request(request_id):
    """Send a request and return the ID container 
    that replies it"""
    try:
        response = requests.get(URL, timeout=5)
        if response.status_code == 200:
            data = response.json()
            # Recupera l'ID aggiunto nella modifica precedente
            return data.get('container_id', 'Unknown')
        else:
            return f"Error {response.status_code}"
    except Exception as e:
        return "Connection Error"

def run_load_balancing_test():
    print("starting load balancing test")
    print(f"TARGET: {URL}")
    print(f"TOTAL REQUESTS: {TOT_REQUESTS}")
    print(f"CONCURRENT WORKERS: {CONCURRENT_WORKERS}")

    results = []
    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        # list of task
        futures = [executor.submit(send_request, i) for i in range(TOT_REQUESTS)]

        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    end_time = time.time()
    duration = end_time - start_time

    counter = Counter(results)

    print(f"Duration: {duration: .2f} seconds")
    print(f"Total answer received: {len(results)}")

    print(f"{'ID Container ':<30} | {'Request':<10} | {'Percentage':<10}")
    print("-" * 55)

    for container_id, count in counter.items():
        percentage = (count / TOT_REQUESTS) * 100
        print(f"{container_id:<30} | {count:<10} | {percentage:.1f}%")


if __name__ == "__main__":
    run_load_balancing_test()