"""
Test: Service Discovery
Taxonomy Category: Container Orchestration -> Service Discovery

Measures Swarm's internal DNS and service discovery:
1. DNS resolution time for service names
2. Time for new containers to become discoverable
3. DNS consistency across nodes
4. Behavior when containers are added/removed

This test verifies that Swarm's service discovery works correctly and efficiently.
"""

import subprocess
import time
import json
import sys
import statistics

# Configuration
STACK_NAME = "cob-service"
SERVICE_NAME = f"{STACK_NAME}_backend"
DB_SERVICE_NAME = f"{STACK_NAME}_db"
REGISTRY = "192.168.15.9:5000"
TEST_SERVICE_NAME = "discovery-test"
TEST_IMAGE = f"{REGISTRY}/cob-service-backend:latest"
NETWORK_NAME = "cob-service_cob-service"
NUM_ITERATIONS = 10


def log(message):
    """Output to stderr to not interfere with final JSON"""
    print(f"[DISC] {message}", file=sys.stderr)


def cleanup_test_service():
    """Remove test service if exists"""
    subprocess.run(
        f"docker service rm {TEST_SERVICE_NAME}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)


def get_backend_container():
    """Get a running backend container ID"""
    cmd = f"docker ps --filter name={STACK_NAME}_backend --format '{{{{.ID}}}}'"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        containers = result.stdout.strip().split('\n')
        return containers[0] if containers and containers[0] else None
    except:
        return None


def dns_lookup_from_container(container_id, service_name, record_type="A"):
    """Perform DNS lookup from inside a container"""
    # Use nslookup or dig if available, fallback to getent
    cmd = f"docker exec {container_id} getent hosts {service_name}"

    start = time.time()
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        lookup_time = time.time() - start

        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split()
            ip = parts[0] if parts else None
            return {
                "success": True,
                "ip": ip,
                "lookup_time_ms": round(lookup_time * 1000, 2),
                "raw_output": result.stdout.strip()
            }
        else:
            return {
                "success": False,
                "lookup_time_ms": round(lookup_time * 1000, 2),
                "error": result.stderr.strip() or "No result"
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "DNS lookup timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def test_service_dns_resolution(container_id):
    """Test DNS resolution for various service names"""
    log("\n--- Testing DNS Resolution ---")

    # Services to test
    services = [
        {"name": "backend", "expected": True},
        {"name": "db", "expected": True},
        {"name": "frontend", "expected": True},
        {"name": f"{STACK_NAME}_backend", "expected": True},
        {"name": f"{STACK_NAME}_db", "expected": True},
        {"name": "nonexistent-service", "expected": False}
    ]

    results = []

    for service in services:
        log(f"  Looking up: {service['name']}")

        lookups = []
        for i in range(5):
            lookup = dns_lookup_from_container(container_id, service["name"])
            lookups.append(lookup)
            time.sleep(0.1)

        successful = [l for l in lookups if l.get("success")]
        times = [l["lookup_time_ms"] for l in lookups if l.get("lookup_time_ms")]

        result = {
            "service_name": service["name"],
            "expected_to_resolve": service["expected"],
            "resolved": len(successful) > 0,
            "resolution_rate": f"{len(successful)}/5",
            "lookup_times_ms": {
                "min": round(min(times), 2) if times else None,
                "max": round(max(times), 2) if times else None,
                "avg": round(statistics.mean(times), 2) if times else None
            },
            "ips_returned": list(set(l.get("ip") for l in successful if l.get("ip"))),
            "correct_behavior": (len(successful) > 0) == service["expected"]
        }

        results.append(result)

        status = "✓" if result["correct_behavior"] else "✗"
        log(f"    {status} Resolved: {result['resolved']}, IPs: {result['ips_returned']}")

    return results


def test_dns_consistency(container_id, service_name="backend"):
    """Test if DNS returns consistent results"""
    log(f"\n--- Testing DNS Consistency for '{service_name}' ---")

    results = []
    ips_seen = set()

    for i in range(20):
        lookup = dns_lookup_from_container(container_id, service_name)
        if lookup.get("success"):
            results.append(lookup)
            ips_seen.add(lookup.get("ip"))
        time.sleep(0.05)

    return {
        "service_name": service_name,
        "total_lookups": 20,
        "successful": len(results),
        "unique_ips": list(ips_seen),
        "ip_count": len(ips_seen),
        "is_vip": len(ips_seen) == 1,  # VIP mode returns single IP
        "is_dnsrr": len(ips_seen) > 1,  # DNSRR mode returns multiple IPs
        "avg_lookup_time_ms": round(
            statistics.mean([r["lookup_time_ms"] for r in results]), 2
        ) if results else None
    }


def test_new_service_discovery_time():
    """Measure how long until a new service is discoverable"""
    log("\n--- Testing New Service Discovery Time ---")

    cleanup_test_service()

    # Get a container to test from
    test_container = get_backend_container()
    if not test_container:
        return {"error": "No container available for testing"}

    results = []

    for iteration in range(3):
        log(f"  Iteration {iteration + 1}/3")

        # Ensure clean state
        cleanup_test_service()

        # Verify service is NOT discoverable
        pre_check = dns_lookup_from_container(test_container, TEST_SERVICE_NAME)
        if pre_check.get("success"):
            log(f"    WARNING: Service already discoverable before creation")

        # Create service
        create_start = time.time()
        cmd = f"""docker service create \
            --name {TEST_SERVICE_NAME} \
            --replicas 1 \
            --network {NETWORK_NAME} \
            --quiet \
            {TEST_IMAGE}"""

        subprocess.run(cmd, shell=True, capture_output=True)

        # Poll until discoverable
        discovery_time = None
        timeout = 60

        while time.time() - create_start < timeout:
            lookup = dns_lookup_from_container(test_container, TEST_SERVICE_NAME)
            if lookup.get("success"):
                discovery_time = time.time() - create_start
                log(f"    Discovered in {discovery_time:.2f}s")
                break
            time.sleep(0.2)

        results.append({
            "iteration": iteration + 1,
            "discovery_time": round(discovery_time, 4) if discovery_time else None,
            "discovered": discovery_time is not None,
            "ip_assigned": lookup.get("ip") if lookup.get("success") else None
        })

        # Cleanup
        cleanup_test_service()
        time.sleep(2)

    successful = [r for r in results if r.get("discovered")]
    times = [r["discovery_time"] for r in successful if r.get("discovery_time")]

    return {
        "iterations": results,
        "success_rate": f"{len(successful)}/3",
        "discovery_time": {
            "min": round(min(times), 4) if times else None,
            "max": round(max(times), 4) if times else None,
            "avg": round(statistics.mean(times), 4) if times else None
        }
    }


def test_service_removal_propagation():
    """Test how quickly DNS stops resolving a removed service"""
    log("\n--- Testing Service Removal Propagation ---")

    test_container = get_backend_container()
    if not test_container:
        return {"error": "No container available for testing"}

    # Create a test service
    cleanup_test_service()

    cmd = f"""docker service create \
        --name {TEST_SERVICE_NAME} \
        --replicas 1 \
        --network {NETWORK_NAME} \
        --quiet \
        {TEST_IMAGE}"""

    subprocess.run(cmd, shell=True, capture_output=True)

    # Wait for it to be discoverable
    log("  Waiting for service to be discoverable...")
    for _ in range(60):
        if dns_lookup_from_container(test_container, TEST_SERVICE_NAME).get("success"):
            break
        time.sleep(0.5)

    time.sleep(2)  # Let it stabilize

    # Now remove it and measure propagation time
    log("  Removing service and measuring propagation...")
    remove_start = time.time()
    subprocess.run(f"docker service rm {TEST_SERVICE_NAME}", shell=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Poll until NOT discoverable
    propagation_time = None
    still_resolving_samples = []

    for i in range(120):  # 60 seconds max
        lookup = dns_lookup_from_container(test_container, TEST_SERVICE_NAME)
        if not lookup.get("success"):
            propagation_time = time.time() - remove_start
            break
        still_resolving_samples.append(round(time.time() - remove_start, 2))
        time.sleep(0.5)

    return {
        "propagation_time": round(propagation_time, 4) if propagation_time else None,
        "dns_cleared": propagation_time is not None,
        "resolution_samples_after_removal": len(still_resolving_samples),
        "interpretation": (
            f"DNS stopped resolving after {propagation_time:.2f}s" if propagation_time
            else "DNS still resolving after 60s (possible caching issue)"
        )
    }


def run_service_discovery_test():
    """Run complete service discovery test"""
    log("Starting Service Discovery test")

    # Get a container to run tests from
    test_container = get_backend_container()
    if not test_container:
        log("ERROR: No backend container found")
        print(json.dumps({"error": "No backend container", "status": "failed"}))
        return

    log(f"Using container {test_container[:12]} for DNS tests")

    # Run tests
    dns_resolution = test_service_dns_resolution(test_container)
    dns_consistency = test_dns_consistency(test_container)
    new_service_discovery = test_new_service_discovery_time()
    removal_propagation = test_service_removal_propagation()

    # Determine status
    all_dns_correct = all(r.get("correct_behavior") for r in dns_resolution)
    discovery_works = new_service_discovery.get("success_rate", "0/3") != "0/3"

    status = "passed" if all_dns_correct and discovery_works else "partial"

    output = {
        "test_name": "service_discovery",
        "category": "container_orchestration",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "network": NETWORK_NAME,
            "test_container": test_container[:12]
        },
        "status": status,
        "results": {
            "dns_resolution": dns_resolution,
            "dns_consistency": dns_consistency,
            "new_service_discovery": new_service_discovery,
            "removal_propagation": removal_propagation
        },
        "summary": {
            "dns_working": all_dns_correct,
            "dns_mode": "VIP" if dns_consistency.get("is_vip") else "DNSRR",
            "avg_lookup_time_ms": dns_consistency.get("avg_lookup_time_ms"),
            "avg_discovery_time": new_service_discovery.get("discovery_time", {}).get("avg"),
            "removal_propagation_time": removal_propagation.get("propagation_time")
        },
        "interpretation": generate_interpretation(dns_resolution, dns_consistency, new_service_discovery)
    }

    print(json.dumps(output, indent=2))


def generate_interpretation(dns_resolution, dns_consistency, new_service):
    """Generate human-readable interpretation"""
    points = []

    # DNS mode
    if dns_consistency.get("is_vip"):
        points.append("Swarm is using VIP (Virtual IP) mode - single IP per service with internal load balancing")
    elif dns_consistency.get("is_dnsrr"):
        points.append("Swarm is using DNSRR mode - multiple IPs returned, client-side load balancing")

    # Lookup time
    avg_time = dns_consistency.get("avg_lookup_time_ms")
    if avg_time:
        if avg_time < 5:
            points.append(f"DNS lookup time is excellent ({avg_time}ms)")
        elif avg_time < 20:
            points.append(f"DNS lookup time is acceptable ({avg_time}ms)")
        else:
            points.append(f"DNS lookup time is slow ({avg_time}ms) - may impact service-to-service calls")

    # Discovery time
    disc_time = new_service.get("discovery_time", {}).get("avg")
    if disc_time:
        if disc_time < 5:
            points.append(f"New services become discoverable quickly ({disc_time:.1f}s)")
        elif disc_time < 15:
            points.append(f"New service discovery time is moderate ({disc_time:.1f}s)")
        else:
            points.append(f"New service discovery is slow ({disc_time:.1f}s) - may impact deployments")

    return points


if __name__ == "__main__":
    run_service_discovery_test()