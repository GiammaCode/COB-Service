import requests
import concurrent.futures
import time
import subprocess

URL = "http://localhost:5001"
TOTAL_REQUESTS = 200
CONCURRENT_WORKERS = 20

def send_request(i):
    try:
        start = time.time()
        resp = requests.get(URL)
        latency = time.time() - start
        return resp.status_code, latency
    except:
        return 500, 0

def benchmark(replicas_count):
    print(f"Starting benchmark with {replicas_count} replicas")

    print(f"   -> Scaling backend a {replicas_count}...")
    subprocess.run(f"docker-compose up -d --scale backend={replicas_count} --no-recreate", shell=True)
    time.sleep(5)

    start_time = time.time()
    success_count = 0
    total_latency = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = [executor.submit(send_request, i) for i in range(TOTAL_REQUESTS)]
        for future in concurrent.futures.as_completed(futures):
            status, latency = future.result()
            if status == 200:
                success_count += 1
                total_latency += latency

    duration = time.time() - start_time
    rps = success_count / duration
    avg_latency = (total_latency / success_count) * 1000 if success_count > 0 else 0

    print(f"   Risultati {replicas_count} Repliche:")
    print(f"   ✅ RPS (Throughput): {rps:.2f} req/s")
    print(f"   ✅ Latenza Media: {avg_latency:.2f} ms")
    return rps


def run_scalability_test():
    print("--- Inizio Test Scalabilità (Horizontal Scaling) ---")

    # Test con 1 Replica
    rps_1 = benchmark(1)

    # Test con 3 Repliche
    rps_3 = benchmark(3)

    print("\n--- Confronto Finale ---")
    increase = ((rps_3 - rps_1) / rps_1) * 100
    print(f"Incremento throughput: {increase:.2f}%")

    if rps_3 > rps_1:
        print("✅ SUCCESS: Il sistema scala positivamente.")
    else:
        print("⚠️ WARNING: Nessun miglioramento. Possibile collo di bottiglia (es. DB o CPU client).")

    # Cleanup: torna a 1 replica
    subprocess.run("docker-compose up -d --scale backend=1", shell=True)


if __name__ == "__main__":
    run_scalability_test()

