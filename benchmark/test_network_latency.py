"""
Test: Network Latency
Taxonomy Category: Security and Multitenancy -> Network Isolation

Measures overlay network performance:
1. Container-to-container latency within overlay network
2. Comparison with host network latency
3. Cross-node vs same-node communication
4. Network overhead introduced by Swarm

This test reveals the cost of Swarm's overlay networking.
"""

import subprocess
import time
import json
import sys
import statistics
import requests

# Configuration
STACK_NAME = "cob-service"
SERVICE_NAME = f"{STACK_NAME}_backend"
REGISTRY = "192.168.15.9:5000"
TEST_SERVICE_NAME = "nettest"
TEST_IMAGE = f"{REGISTRY}/cob-service-backend:latest"
NETWORK_NAME = "cob-service_cob-service"
BACKEND_URL = "http://localhost:5001/"
NUM_PINGS = 20


def log(message):
    """Output to stderr to not interfere with final JSON"""
    print(f"[NET] {message}", file=sys.stderr)


def cleanup_test_service():
    """Remove test service if exists"""
    subprocess.run(
        f"docker service rm {TEST_SERVICE_NAME}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)


def get_backend_containers():
    """Get backend container info including IPs and nodes"""
    cmd = f"docker service ps {SERVICE_NAME} --filter 'desired-state=running' --format '{{{{.ID}}}} {{{{.Node}}}} {{{{.Name}}}}'"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 3:
                    task_id = parts[0]
                    node = parts[1]
                    name = parts[2]

                    # Get container ID
                    cmd2 = f"docker inspect --format '{{{{.Status.ContainerStatus.ContainerID}}}}' {task_id}"
                    result2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
                    container_id = result2.stdout.strip()[:12] if result2.stdout.strip() else None

                    if container_id:
                        containers.append({
                            "task_id": task_id,
                            "container_id": container_id,
                            "node": node,
                            "name": name
                        })
        return containers
    except Exception as e:
        log(f"Error: {e}")
        return []


def get_container_ip(container_id, network_name):
    """Get container IP on specific network"""
    cmd = f"docker inspect --format '{{{{.NetworkSettings.Networks.{network_name}.IPAddress}}}}' {container_id}"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip() if result.stdout.strip() else None
    except:
        return None


def get_node_ip(node_hostname):
    """Get node IP address"""
    cmd = f"docker node inspect {node_hostname} --format '{{{{.Status.Addr}}}}'"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip() if result.stdout.strip() else None
    except:
        return None


def ping_from_container(source_container_id, target_ip, count=5):
    """Execute ping from inside a container"""
    cmd = f"docker exec {source_container_id} ping -c {count} -W 2 {target_ip}"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

        # Parse ping output
        latencies = []
        for line in result.stdout.split('\n'):
            if 'time=' in line:
                # Extract time value
                time_part = line.split('time=')[1].split()[0]
                latencies.append(float(time_part.replace('ms', '')))

        if latencies:
            return {
                "success": True,
                "latencies_ms": latencies,
                "min": round(min(latencies), 3),
                "max": round(max(latencies), 3),
                "avg": round(statistics.mean(latencies), 3),
                "packet_loss": 0
            }
        else:
            # Check for packet loss
            if '100% packet loss' in result.stdout or '100% packet loss' in result.stderr:
                return {"success": False, "error": "100% packet loss"}
            return {"success": False, "error": "No ping response", "output": result.stdout[:200]}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Ping timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def http_latency_test(source_container_id, target_ip, port=5000, count=10):
    """Measure HTTP request latency from container to container"""
    latencies = []
    errors = 0

    for i in range(count):
        cmd = f"docker exec {source_container_id} curl -s -o /dev/null -w '%{{time_total}}' http://{target_ip}:{port}/ --max-time 5"
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                latency = float(result.stdout.strip()) * 1000  # Convert to ms
                latencies.append(latency)
            else:
                errors += 1
        except:
            errors += 1
        time.sleep(0.1)

    if latencies:
        return {
            "success": True,
            "requests": count,
            "successful": len(latencies),
            "errors": errors,
            "latencies_ms": {
                "min": round(min(latencies), 2),
                "max": round(max(latencies), 2),
                "avg": round(statistics.mean(latencies), 2),
                "stdev": round(statistics.stdev(latencies), 2) if len(latencies) > 1 else 0
            }
        }
    return {"success": False, "error": f"All {count} requests failed"}


def measure_external_latency():
    """Measure latency from outside the cluster (via ingress)"""
    log("  Measuring external (ingress) latency...")

    latencies = []
    for i in range(20):
        try:
            start = time.time()
            resp = requests.get(BACKEND_URL, timeout=5)
            if resp.status_code == 200:
                latencies.append((time.time() - start) * 1000)
        except:
            pass
        time.sleep(0.05)

    if latencies:
        return {
            "success": True,
            "requests": 20,
            "successful": len(latencies),
            "latencies_ms": {
                "min": round(min(latencies), 2),
                "max": round(max(latencies), 2),
                "avg": round(statistics.mean(latencies), 2),
                "stdev": round(statistics.stdev(latencies), 2) if len(latencies) > 1 else 0
            }
        }
    return {"success": False, "error": "No successful requests"}


def test_same_node_latency(containers):
    """Test latency between containers on the same node"""
    log("\n--- Testing Same-Node Latency ---")

    # Group containers by node
    by_node = {}
    for c in containers:
        node = c["node"]
        if node not in by_node:
            by_node[node] = []
        by_node[node].append(c)

    results = []

    for node, node_containers in by_node.items():
        if len(node_containers) < 2:
            continue

        source = node_containers[0]
        target = node_containers[1]

        # Get target IP
        target_ip = get_container_ip(target["container_id"], NETWORK_NAME.replace("-", "_"))
        if not target_ip:
            # Try alternate network name format
            target_ip = get_container_ip(target["container_id"], "cob-service_cob-service")

        if not target_ip:
            log(f"  Could not get IP for {target['container_id']}")
            continue

        log(f"  {source['container_id'][:8]} -> {target['container_id'][:8]} (same node: {node})")

        # ICMP ping test
        ping_result = ping_from_container(source["container_id"], target_ip, NUM_PINGS)

        # HTTP test
        http_result = http_latency_test(source["container_id"], target_ip)

        results.append({
            "type": "same_node",
            "node": node,
            "source": source["container_id"][:8],
            "target": target["container_id"][:8],
            "target_ip": target_ip,
            "icmp_ping": ping_result,
            "http_latency": http_result
        })

    return results


def test_cross_node_latency(containers):
    """Test latency between containers on different nodes"""
    log("\n--- Testing Cross-Node Latency ---")

    # Group containers by node
    by_node = {}
    for c in containers:
        node = c["node"]
        if node not in by_node:
            by_node[node] = []
        by_node[node].append(c)

    nodes = list(by_node.keys())
    if len(nodes) < 2:
        log("  Only one node has containers, skipping cross-node test")
        return []

    results = []

    # Test between first container of each node pair
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            source_node = nodes[i]
            target_node = nodes[j]

            source = by_node[source_node][0]
            target = by_node[target_node][0]

            # Get target IP
            target_ip = get_container_ip(target["container_id"], NETWORK_NAME.replace("-", "_"))
            if not target_ip:
                target_ip = get_container_ip(target["container_id"], "cob-service_cob-service")

            if not target_ip:
                log(f"  Could not get IP for {target['container_id']}")
                continue

            log(f"  {source['container_id'][:8]} ({source_node}) -> {target['container_id'][:8]} ({target_node})")

            # ICMP ping test
            ping_result = ping_from_container(source["container_id"], target_ip, NUM_PINGS)

            # HTTP test
            http_result = http_latency_test(source["container_id"], target_ip)

            results.append({
                "type": "cross_node",
                "source_node": source_node,
                "target_node": target_node,
                "source": source["container_id"][:8],
                "target": target["container_id"][:8],
                "target_ip": target_ip,
                "icmp_ping": ping_result,
                "http_latency": http_result
            })

    return results


def analyze_results(same_node, cross_node, external):
    """Analyze and compare latency results"""
    analysis = {
        "same_node_avg_ms": None,
        "cross_node_avg_ms": None,
        "external_avg_ms": None,
        "cross_node_overhead_ms": None,
        "overlay_overhead_percent": None,
        "interpretation": []
    }

    # Same node average
    same_pings = [r["icmp_ping"]["avg"] for r in same_node if r.get("icmp_ping", {}).get("success")]
    if same_pings:
        analysis["same_node_avg_ms"] = round(statistics.mean(same_pings), 3)

    # Cross node average
    cross_pings = [r["icmp_ping"]["avg"] for r in cross_node if r.get("icmp_ping", {}).get("success")]
    if cross_pings:
        analysis["cross_node_avg_ms"] = round(statistics.mean(cross_pings), 3)

    # External average
    if external.get("success"):
        analysis["external_avg_ms"] = external["latencies_ms"]["avg"]

    # Calculate overhead
    if analysis["same_node_avg_ms"] and analysis["cross_node_avg_ms"]:
        analysis["cross_node_overhead_ms"] = round(
            analysis["cross_node_avg_ms"] - analysis["same_node_avg_ms"], 3
        )

    # Interpretation
    if analysis["same_node_avg_ms"]:
        if analysis["same_node_avg_ms"] < 1:
            analysis["interpretation"].append("Same-node latency is excellent (<1ms)")
        elif analysis["same_node_avg_ms"] < 5:
            analysis["interpretation"].append("Same-node latency is good (<5ms)")
        else:
            analysis["interpretation"].append(f"Same-node latency is high ({analysis['same_node_avg_ms']}ms)")

    if analysis["cross_node_overhead_ms"]:
        if analysis["cross_node_overhead_ms"] < 1:
            analysis["interpretation"].append("Minimal overhead for cross-node communication")
        elif analysis["cross_node_overhead_ms"] < 5:
            analysis["interpretation"].append("Moderate cross-node overhead (normal for overlay networks)")
        else:
            analysis["interpretation"].append(
                f"High cross-node overhead ({analysis['cross_node_overhead_ms']}ms) - check network configuration")

    return analysis


def run_network_latency_test():
    """Run complete network latency test"""
    log("Starting Network Latency test")

    # Get containers
    containers = get_backend_containers()
    log(f"Found {len(containers)} backend containers")

    if len(containers) < 2:
        log("ERROR: Need at least 2 containers for network testing")
        print(json.dumps({
            "error": "Insufficient containers",
            "status": "failed",
            "containers_found": len(containers)
        }))
        return

    # Show container distribution
    nodes = set(c["node"] for c in containers)
    log(f"Containers distributed across {len(nodes)} nodes: {list(nodes)}")

    # Run tests
    same_node_results = test_same_node_latency(containers)
    cross_node_results = test_cross_node_latency(containers)

    log("\n--- Testing External (Ingress) Latency ---")
    external_results = measure_external_latency()

    # Analyze
    analysis = analyze_results(same_node_results, cross_node_results, external_results)

    # Build output
    output = {
        "test_name": "network_latency",
        "category": "network_isolation",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "service": SERVICE_NAME,
            "network": NETWORK_NAME,
            "ping_count": NUM_PINGS,
            "containers_tested": len(containers),
            "nodes_involved": list(nodes)
        },
        "status": "passed" if (same_node_results or cross_node_results) else "failed",
        "results": {
            "same_node": same_node_results,
            "cross_node": cross_node_results,
            "external_ingress": external_results
        },
        "analysis": analysis
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    run_network_latency_test()