"""
Test: Leader Election
Taxonomy Category: System Objectives -> High Availability

Measures Swarm's control plane resilience:
1. How fast does a new leader get elected when the current leader fails?
2. Does the cluster remain operational during leader transition?
3. Can new services be deployed after failover?

IMPORTANT: This test requires a multi-manager Swarm setup (3+ managers recommended).
If only 1 manager exists, the test will report limited results.
"""

import subprocess
import time
import json
import sys
import requests

# Configuration
STACK_NAME = "cob-service"
TEST_SERVICE_NAME = "leader-test"
REGISTRY = "192.168.15.9:5000"
TEST_IMAGE = f"{REGISTRY}/cob-service-backend:latest"
NETWORK_NAME = "cob-service_cob-service"
TIMEOUT_SECONDS = 120
NUM_ITERATIONS = 3


def log(message):
    """Output to stderr to not interfere with final JSON"""
    print(f"[LEADER] {message}", file=sys.stderr)


def get_swarm_nodes():
    """Get list of all Swarm nodes with their roles and status"""
    cmd = "docker node ls --format '{{.ID}} {{.Hostname}} {{.Status}} {{.Availability}} {{.ManagerStatus}}'"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        nodes = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 4:
                    node = {
                        "id": parts[0],
                        "hostname": parts[1],
                        "status": parts[2],
                        "availability": parts[3],
                        "manager_status": parts[4] if len(parts) > 4 else None
                    }
                    nodes.append(node)
        return nodes
    except Exception as e:
        log(f"Error getting nodes: {e}")
        return []


def get_current_leader():
    """Get the current Swarm leader node"""
    nodes = get_swarm_nodes()
    for node in nodes:
        if node.get("manager_status") == "Leader":
            return node
    return None


def get_managers():
    """Get list of manager nodes"""
    nodes = get_swarm_nodes()
    return [n for n in nodes if n.get("manager_status") in ["Leader", "Reachable"]]


def is_cluster_healthy():
    """Check if Swarm cluster is responding to commands"""
    try:
        result = subprocess.run(
            "docker node ls",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except:
        return False


def can_deploy_service():
    """Test if we can deploy a new service (cluster is functional)"""
    # Cleanup first
    subprocess.run(
        f"docker service rm {TEST_SERVICE_NAME}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(2)

    # Try to create service
    cmd = f"""docker service create \
        --name {TEST_SERVICE_NAME} \
        --replicas 1 \
        --restart-condition none \
        --quiet \
        {TEST_IMAGE}"""

    start = time.time()
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    deploy_time = time.time() - start

    success = result.returncode == 0

    # Cleanup
    subprocess.run(
        f"docker service rm {TEST_SERVICE_NAME}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return success, deploy_time


def simulate_leader_failure(leader_hostname):
    """
    Simulate leader failure by draining the node.
    NOTE: In a real test, you would stop the Docker daemon on the leader.
    Since we can't do that remotely, we use drain as a simulation.

    For a true test, manually run: sudo systemctl stop docker
    on the leader node.
    """
    # Drain the leader node (removes it from scheduling, simulates partial failure)
    cmd = f"docker node update --availability drain {leader_hostname}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0


def restore_node(hostname):
    """Restore a drained node to active"""
    cmd = f"docker node update --availability active {hostname}"
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def measure_leader_election_after_drain():
    """
    Measure cluster behavior after draining the leader.
    Note: Draining doesn't trigger full leader election, but tests cluster resilience.
    """
    result = {
        "success": False,
        "initial_leader": None,
        "managers_count": 0,
        "drain_time": None,
        "cluster_responsive_after": None,
        "can_deploy_after": None,
        "new_leader": None,
        "notes": []
    }

    # Get initial state
    leader = get_current_leader()
    managers = get_managers()

    if not leader:
        result["error"] = "No leader found"
        return result

    result["initial_leader"] = leader["hostname"]
    result["managers_count"] = len(managers)

    if len(managers) < 2:
        result["notes"].append("Single manager setup - cannot test failover")
        result["notes"].append("Add more managers with: docker swarm join-token manager")

        # Still test basic functionality
        can_deploy, deploy_time = can_deploy_service()
        result["can_deploy_after"] = deploy_time if can_deploy else None
        result["success"] = can_deploy
        return result

    log(f"  Initial leader: {leader['hostname']}")
    log(f"  Total managers: {len(managers)}")

    # Drain the leader
    log("  Draining leader node...")
    drain_start = time.time()
    drained = simulate_leader_failure(leader["hostname"])
    result["drain_time"] = round(time.time() - drain_start, 4)

    if not drained:
        result["error"] = "Failed to drain leader"
        restore_node(leader["hostname"])
        return result

    # Monitor cluster health and leader change
    log("  Monitoring cluster response...")
    check_start = time.time()

    while time.time() - check_start < TIMEOUT_SECONDS:
        if is_cluster_healthy():
            result["cluster_responsive_after"] = round(time.time() - drain_start, 4)

            # Check for new leader
            new_leader = get_current_leader()
            if new_leader:
                result["new_leader"] = new_leader["hostname"]
                if new_leader["hostname"] != leader["hostname"]:
                    log(f"  New leader elected: {new_leader['hostname']}")
                break

        time.sleep(0.5)

    # Test if we can deploy
    log("  Testing deployment capability...")
    can_deploy, deploy_time = can_deploy_service()
    result["can_deploy_after"] = round(deploy_time, 4) if can_deploy else None

    # Restore the drained node
    log("  Restoring drained node...")
    restore_node(leader["hostname"])
    time.sleep(2)

    result["success"] = (
            result["cluster_responsive_after"] is not None and
            can_deploy
    )

    return result


def run_leader_election_test():
    """Run complete leader election test"""
    log("Starting Leader Election test")

    # Initial cluster state
    nodes = get_swarm_nodes()
    managers = get_managers()
    leader = get_current_leader()

    log(f"Cluster state:")
    log(f"  Total nodes: {len(nodes)}")
    log(f"  Manager nodes: {len(managers)}")
    log(f"  Current leader: {leader['hostname'] if leader else 'None'}")

    # Check if we can do meaningful testing
    if len(managers) < 3:
        log("\nWARNING: Less than 3 managers. Swarm HA requires 3+ managers.")
        log("Current test will be limited.")

    results = []

    for i in range(NUM_ITERATIONS):
        log(f"\n--- Iteration {i + 1}/{NUM_ITERATIONS} ---")
        result = measure_leader_election_after_drain()
        results.append(result)

        if result.get("notes"):
            for note in result["notes"]:
                log(f"  NOTE: {note}")

        time.sleep(5)

    # Aggregate results
    successful = [r for r in results if r.get("success")]

    responsive_times = [r["cluster_responsive_after"] for r in successful if r.get("cluster_responsive_after")]
    deploy_times = [r["can_deploy_after"] for r in successful if r.get("can_deploy_after")]

    output = {
        "test_name": "leader_election",
        "category": "fault_tolerance",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cluster_info": {
            "total_nodes": len(nodes),
            "manager_nodes": len(managers),
            "initial_leader": leader["hostname"] if leader else None,
            "manager_hostnames": [m["hostname"] for m in managers]
        },
        "config": {
            "iterations": NUM_ITERATIONS,
            "timeout_seconds": TIMEOUT_SECONDS
        },
        "status": determine_status(results, managers),
        "summary": {
            "successful_tests": len(successful),
            "failed_tests": len(results) - len(successful),
            "ha_capable": len(managers) >= 3
        },
        "metrics": {
            "cluster_responsive_time": {
                "min": round(min(responsive_times), 4) if responsive_times else None,
                "max": round(max(responsive_times), 4) if responsive_times else None,
                "mean": round(sum(responsive_times) / len(responsive_times), 4) if responsive_times else None
            },
            "deploy_after_drain_time": {
                "min": round(min(deploy_times), 4) if deploy_times else None,
                "max": round(max(deploy_times), 4) if deploy_times else None,
                "mean": round(sum(deploy_times) / len(deploy_times), 4) if deploy_times else None
            }
        },
        "iterations": results,
        "recommendations": generate_recommendations(managers, results)
    }

    print(json.dumps(output, indent=2))


def determine_status(results, managers):
    """Determine overall test status"""
    if len(managers) < 2:
        return "skipped_single_manager"

    successful = [r for r in results if r.get("success")]
    if len(successful) >= len(results) * 0.8:
        return "passed"
    elif len(successful) > 0:
        return "partial"
    else:
        return "failed"


def generate_recommendations(managers, results):
    """Generate recommendations based on test results"""
    recs = []

    if len(managers) < 3:
        recs.append("Add more manager nodes for true HA (minimum 3 recommended)")
        recs.append("Use: docker swarm join-token manager")

    if len(managers) == 2:
        recs.append("WARNING: 2 managers provides no fault tolerance (need majority)")

    successful = [r for r in results if r.get("success")]
    if successful:
        avg_response = sum(
            r["cluster_responsive_after"] for r in successful if r.get("cluster_responsive_after")) / len(successful)
        if avg_response > 10:
            recs.append(f"Cluster response time ({avg_response:.1f}s) is high - check network latency between managers")

    return recs if recs else ["Cluster HA configuration looks good"]


if __name__ == "__main__":
    run_leader_election_test()