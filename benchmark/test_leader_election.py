"""
Test: Leader Election (Robust Version)
Taxonomy Category: System Objectives -> High Availability

Measures Swarm's control plane resilience:
1. Forces a Leader Election by demoting the current leader.
2. Measures time to elect a new leader.
3. Verifies cluster operability during transition.

Includes safety mechanisms to restore node state even if the test crashes.
"""

import subprocess
import time
import json
import sys

# Configuration
STACK_NAME = "cob-service"
TEST_SERVICE_NAME = "leader-test"
# Usa l'immagine senza risolvere il digest per evitare timeout del registry
TEST_IMAGE = "192.168.15.9:5000/cob-service-backend:latest"
TIMEOUT_SECONDS = 120
NUM_ITERATIONS = 3

def log(message):
    print(f"[LEADER] {message}", file=sys.stderr)

def get_swarm_nodes():
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
                        "manager_status": parts[4] if len(parts) > 4 else "Worker"
                    }
                    nodes.append(node)
        return nodes
    except Exception as e:
        log(f"Error getting nodes: {e}")
        return []

def get_current_leader():
    nodes = get_swarm_nodes()
    for node in nodes:
        if node.get("manager_status") == "Leader":
            return node
    return None

def get_managers():
    nodes = get_swarm_nodes()
    return [n for n in nodes if n.get("manager_status") in ["Leader", "Reachable"]]

def is_cluster_healthy():
    try:
        # Check simple command response
        result = subprocess.run("docker node ls", shell=True, capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except:
        return False

def can_deploy_service():
    # Cleanup preventivo
    subprocess.run(f"docker service rm {TEST_SERVICE_NAME}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)

    # ADDED: --no-resolve-image prevents registry timeouts
    cmd = f"""docker service create \
        --name {TEST_SERVICE_NAME} \
        --replicas 1 \
        --restart-condition none \
        --no-resolve-image \
        --quiet \
        {TEST_IMAGE}"""

    start = time.time()
    # Increased timeout
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        success = result.returncode == 0
    except subprocess.TimeoutExpired:
        success = False

    deploy_time = time.time() - start

    # Cleanup post
    subprocess.run(f"docker service rm {TEST_SERVICE_NAME}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return success, deploy_time

def run_iteration(iteration_num):
    log(f"\n--- Iteration {iteration_num}/{NUM_ITERATIONS} ---")

    leader = get_current_leader()
    if not leader:
        return {"success": False, "error": "No leader found initially"}

    leader_hostname = leader['hostname']
    log(f"  Current Leader: {leader_hostname}")

    result = {
        "initial_leader": leader_hostname,
        "demote_time": None,
        "election_time": None,
        "new_leader": None,
        "cluster_responsive": False,
        "deployment_capability": False,
        "success": False
    }

    try:
        # 1. DEMOTE LEADER (Simulate Failure)
        log(f"  Demoting leader {leader_hostname}...")
        start_demote = time.time()
        subprocess.run(f"docker node demote {leader_hostname}", shell=True, check=True, stdout=subprocess.DEVNULL)
        result["demote_time"] = time.time()

        # 2. WAIT FOR ELECTION
        log("  Waiting for new leader...")
        election_start = time.time()
        new_leader_found = False

        while time.time() - election_start < TIMEOUT_SECONDS:
            if is_cluster_healthy():
                result["cluster_responsive"] = True
                curr = get_current_leader()
                if curr and curr['hostname'] != leader_hostname:
                    result["new_leader"] = curr['hostname']
                    result["election_time"] = round(time.time() - election_start, 4)
                    new_leader_found = True
                    log(f"  New Leader Elected: {curr['hostname']} in {result['election_time']}s")
                    break
            time.sleep(0.5)

        if not new_leader_found:
            log("  FAIL: No new leader elected within timeout")
            return result

        # 3. VERIFY DEPLOYMENT
        log("  Verifying deployment capability...")
        time.sleep(2) # Give raft a moment to stabilize
        can_dep, dep_time = can_deploy_service()
        result["deployment_capability"] = can_dep
        result["deployment_time"] = round(dep_time, 4) if can_dep else None

        if can_dep:
            log(f"  Deployment successful in {dep_time:.2f}s")
            result["success"] = True
        else:
            log("  Deployment FAILED")

    except Exception as e:
        log(f"  ERROR during test: {e}")
        result["error"] = str(e)

    finally:
        # 4. RESTORE NODE (ALWAYS RUNS)
        log(f"  RESTORING node {leader_hostname}...")
        try:
            subprocess.run(f"docker node promote {leader_hostname}", shell=True, stdout=subprocess.DEVNULL)
            # Wait for node to rejoin quorum
            time.sleep(5)
        except Exception as e:
            log(f"  CRITICAL: Failed to restore node: {e}")

    return result

def run_leader_election_test():
    log("Starting Leader Election Benchmark (High Availability)")

    managers = get_managers()
    if len(managers) < 3:
        log("WARNING: You need at least 3 Managers for HA testing.")

    results = []
    for i in range(NUM_ITERATIONS):
        res = run_iteration(i + 1)
        results.append(res)
        time.sleep(5)

    # Calculate metrics
    successful = [r for r in results if r["success"]]

    metrics = {
        "test_name": "leader_election",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "passed" if len(successful) >= 2 else "failed",
        "total_iterations": NUM_ITERATIONS,
        "successful_iterations": len(successful),
        "metrics": {
            "avg_election_time": 0,
            "avg_deployment_time": 0
        },
        "details": results
    }

    if successful:
        metrics["metrics"]["avg_election_time"] = round(sum(r["election_time"] for r in successful) / len(successful), 4)
        metrics["metrics"]["avg_deployment_time"] = round(sum(r["deployment_time"] for r in successful) / len(successful), 4)

    print(json.dumps(metrics, indent=2))

if __name__ == "__main__":
    run_leader_election_test()