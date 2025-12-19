import time
import sys
import os
import json
from pymongo import MongoClient

# Setup path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

import config
from drivers.swarm_driver import SwarmDriver

# Mongo Configuration (Direct access for data verification)
# Note: Ensure port 27017 is exposed on all nodes or use the manager IP
MONGO_URI = "mongodb://mongoadmin:secret@192.168.15.9:27017/?authSource=admin"


def get_db_node(driver):
    """Finds which node the DB is running on"""
    cmd = "docker service ps cob-service_db --filter desired-state=running --format '{{.Node}}'"
    res = driver._run(cmd)
    return res.stdout.strip()


def test_storage():
    driver = SwarmDriver(config.STACK_NAME)
    output = {
        "test_name": "storage_persistence_nfs",
        "description": "Verifies data persistence when DB moves between nodes using NFS",
        "steps": []
    }

    print("--- Storage Persistence Test (NFS) ---")

    # 1. INITIAL SETUP
    print("[TEST] Deploying stack with NFS volume...")
    # We assume the stack is already deployed with the new YAML
    # Or you can force the update if the script supports it.
    # For safety, restart the DB to ensure it's fresh
    driver.scale_service("db", 1)
    time.sleep(10)

    node_start = get_db_node(driver)
    print(f"[TEST] DB started on Node: {node_start}")

    # 2. DATA WRITING
    print("[TEST] Writing verification data...")
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client["benchmark_test_db"]
        coll = db["persistence_check"]

        # Cleanup and Writing
        coll.delete_many({})
        test_doc = {"_id": "test_record", "timestamp": time.time(), "origin_node": node_start}
        coll.insert_one(test_doc)
        print(f"[TEST] Data written: {test_doc}")
        output["steps"].append({"action": "write", "node": node_start, "status": "success"})
    except Exception as e:
        print(f"[ERROR] Write failed: {e}")
        return

    # 3. FORCED MIGRATION (Simulating move to another node)
    # Find a node that is NOT the current one
    all_nodes = driver.get_worker_nodes()  # Include manager if active as worker
    # If get_worker_nodes returns only workers, manually add the manager if needed
    # For simplicity, force a constraint that EXCLUDES the current node

    print(f"[TEST] Forcing DB migration away from {node_start}...")

    # Update the service adding a constraint: node.hostname != node_start
    constraint = f"node.hostname!={node_start}"
    driver._run(f"docker service update --constraint-add {constraint} cob-service_db")

    print("[TEST] Waiting for migration (20s)...")
    time.sleep(20)

    node_end = get_db_node(driver)
    print(f"[TEST] DB moved to Node: {node_end}")

    if node_start == node_end:
        print("[WARNING] DB did not move! Do you have enough nodes?")
        output["steps"].append({"action": "migrate", "from": node_start, "to": node_end, "status": "failed"})
    else:
        output["steps"].append({"action": "migrate", "from": node_start, "to": node_end, "status": "success"})

    # 4. DATA READING (Persistence Verification)
    print("[TEST] Verifying data persistence...")
    try:
        # Reconnect (mongo client should handle reconnection, or create a new one)
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        coll = client["benchmark_test_db"]["persistence_check"]

        doc = coll.find_one({"_id": "test_record"})

        if doc and doc["origin_node"] == node_start:
            print(f"[SUCCESS] Data found! Created on {doc['origin_node']}, read on {node_end}.")
            output["result"] = "PASSED"
        else:
            print(f"[FAILURE] Data mismatch or not found. Doc: {doc}")
            output["result"] = "FAILED"

    except Exception as e:
        print(f"[ERROR] Read failed: {e}")
        output["result"] = "ERROR"

    # 5. CLEANUP (Remove constraints to return to normal)
    print("[TEST] Cleaning up constraints...")
    driver._run(f"docker service update --constraint-rm {constraint} cob-service_db")

    # Saving
    os.makedirs("results", exist_ok=True)
    with open("results/storage_persistence.json", "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    test_storage()