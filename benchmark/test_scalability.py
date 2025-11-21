import requests
import concurrent.futures
import time
import subprocess

URL = "http://localhost:5001"
STACK_NAME = "cob-service"
SERVICE_NAME = f"{STACK_NAME}_backend"
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

def get_current_replicas():
    """Get current number of replicas"""
    cmd = f"docker service ls --filter name={SERVICE_NAME} --format '{{{{.Replicas}}}}'"
    try:
        output = subprocess.check_output(cmd, shell=True).decode().strip()
        return output.split('/')[0]
    except:
        return "Unknow"

def scale_service(replicas_count):
    """Scale service"""
    cmd = f"docker service scale {SERVICE_NAME}={replicas_count}"
    subprocess.run(cmd, shell=True, capture_output=True)

    max_wait = 100
    start = time.time()

    while time.time() - start < max_wait:
        current = get_current_replicas()
        if current == str(replicas_count):
            print(f"Scaled to {replicas_count} replicas")
            return True
        time.sleep(2)

    print("timeout scaling")
    return False


def benchmark(replicas_count):
   if not scale_service(replicas_count):
       print("scaling failed")
       return 0
   time.sleep(2)
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
   rps = success_count / duration if duration > 0 else 0
   avg_latency = (total_latency / success_count) * 1000 if success_count > 0 else 0
   print(f"\n   Results with {replicas_count} Replica(s):")
   print(f"   Throughput (RPS): {rps:.2f} req/s")
   print(f"   Average Latency: {avg_latency:.2f} ms")
   print(f"   Success Rate: {success_count}/{TOTAL_REQUESTS} ({success_count / TOTAL_REQUESTS * 100:.1f}%)")

   return rps


def run_scalability_test():
    print("   Starting Horizontal Scalability Test")

    # Test with 1 Replica
    rps_1 = benchmark(1)

    # Test with 3 Replicas
    rps_3 = benchmark(3)

    print("\n" + "=" * 60)
    print("   Final Comparison")
    print("=" * 60)

    if rps_1 > 0:
        increase = ((rps_3 - rps_1) / rps_1) * 100
        print(f"Throughput increase: {increase:.2f}%")
        print(f"Speedup factor: {rps_3 / rps_1:.2f}x")

        if rps_3 > rps_1:
            print("SUCCESS: System scales positively with horizontal scaling.")
            if increase > 50:
                print("   Excellent scaling efficiency!")
            elif increase > 25:
                print("   Good scaling efficiency.")
            else:
                print("   Moderate scaling efficiency.")
        else:
            print("WARNING: No improvement detected.")
            print("   Possible bottleneck: Database, network, or client CPU.")
    else:
        print("FAILURE: Could not measure baseline performance")

    # Cleanup: return to 1 replica
    print("\nCleaning up - scaling back to 1 replica...")
    scale_service(1)


if __name__ == "__main__":
    run_scalability_test()


