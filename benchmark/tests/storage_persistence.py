import time
import sys
import os
import json
import subprocess
from pymongo import MongoClient

# Setup path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# Local imports
import config
#from drivers.swarm_driver import SwarmDriver
from drivers.k8s_driver import K8sDriver

# Constants
MONGO_LOCAL_PORT = 27017
# We connect to localhost because we use kubectl port-forward
MONGO_URI = f"mongodb://mongoadmin:secret@127.0.0.1:{MONGO_LOCAL_PORT}/?authSource=admin"

class PortForwarder:
    """Helper to manage kubectl port-forward in the background"""
    def __init__(self, namespace, service_name, local_port, remote_port):
        self.cmd = [
            "kubectl", "port-forward",
            f"svc/{service_name}",
            f"{local_port}:{remote_port}",
            "-n", namespace
        ]
        self.process = None

    def start(self):
        print(f"[FORWARDER] Starting tunnel to {self.cmd[2]} on port {self.cmd[3]}...")
        # Start detached process
        self.process = subprocess.Popen(
            self.cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(3) # Wait for tunnel to be established

    def stop(self):
        if self.process:
            print("[FORWARDER] Stopping tunnel...")
            self.process.terminate()
            self.process.wait()

def test_storage():
    #driver = SwarmDriver(config.STACK_NAME)
    driver = K8sDriver()
    output = {
        "test_name": "storage_persistence_nfs",
        "description": "Verifies data persistence when DB moves between nodes using NFS",
        "steps": [],
        "result": "UNKNOWN"
    }

    print("--- Storage Persistence Test (NFS) ---")

    print("[TEST] Deploying stack with NFS volume...")
    driver.scale_service("db", 1)

    time.sleep(5)

    # Identify Start Node
    # node_start = driver.get_db_node()
    node_start = driver.get_pod_node("db")
    print(f"[TEST] DB started on Node: {node_start}")

    print("[TEST] Writing verification data...")
    pf = PortForwarder("cob-service", "db", MONGO_LOCAL_PORT, 27017)
    pf.start()
    try:
        print("[TEST] Connecting to MongoDB...")
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client["benchmark_test_db"]
        coll = db["persistence_check"]

        # Clean and Insert
        coll.delete_many({})
        test_doc = {"_id": "test_record", "timestamp": time.time(), "origin_node": node_start}
        coll.insert_one(test_doc)
        print(f"[TEST] Data written: {test_doc}")
        output["steps"].append({"action": "write", "node": node_start, "status": "success"})
    except Exception as e:
        print(f"[ERROR] Write failed: {e}")
        pf.stop()
        return

    # Stop tunnel before moving pod (connection would break anyway)
    pf.stop()

    # 3. FORCE MIGRATION
    print(f"[TEST] Forcing migration AWAY from {node_start}...")

    # A. Cordon current node so K8s can't schedule there
    driver.cordon_node(node_start)

    # B. Delete the pod to force rescheduling
    driver.delete_pods_by_label("db")

    print("[TEST] Waiting for rescheduling (20s)...")
    time.sleep(20)

    # C. Verify new location
    node_end = driver.get_pod_node("db")
    print(f"[TEST] DB moved to Node: {node_end}")

    if node_start == node_end:
        print("[WARNING] DB did not move! Do you have enough worker nodes?")
        output["steps"].append({"action": "migrate", "from": node_start, "to": node_end, "status": "failed"})
    else:
        output["steps"].append({"action": "migrate", "from": node_start, "to": node_end, "status": "success"})

    # 4. READ DATA (Verify Persistence)
    print("[TEST] Opening tunnel to read data...")
    pf = PortForwarder("cob-service", "db", MONGO_LOCAL_PORT, 27017)
    pf.start()

    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        coll = client["benchmark_test_db"]["persistence_check"]

        doc = coll.find_one({"_id": "test_record"})

        if doc and doc["origin_node"] == node_start:
            print(f"[SUCCESS] Data found! Written on {doc['origin_node']}, Read on {node_end}.")
            output["result"] = "PASSED"
        else:
            print(f"[FAILURE] Data missing or mismatch. Got: {doc}")
            output["result"] = "FAILED"

    except Exception as e:
        print(f"[ERROR] Read failed: {e}")
        output["result"] = "ERROR"
    finally:
        pf.stop()

    # 5. CLEANUP
    print("[TEST] Cleaning up (Uncordon)...")
    driver.uncordon_node(node_start)

    # Save Results
    os.makedirs("results", exist_ok=True)
    outfile = "results/storage_persistence_k8s.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[TEST] Completed. JSON saved to {outfile}")


if __name__ == "__main__":
    test_storage()