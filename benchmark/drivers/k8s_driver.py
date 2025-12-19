import subprocess
import time
import json
import sys
import os

class K8sDriver:
    def __init__(self, namespace="cob-service"):
        self.namespace = namespace

    def _run(self, cmd):
        # do command and save output
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def scale_service(self, service_name, replicas):
        """Scale a service by replicas"""
        print(f"[K8S-DRIVER] Scaling {service_name} to {replicas} replicas...")
        cmd = f"kubectl scale deployment {service_name} --replicas={replicas} -n {self.namespace}"
        res = self._run(cmd)
        if res.returncode != 0:
            print(f"[ERROR] Failed to scale {service_name}: {res.stderr}]")

    def get_replica_count(self, service_name):
        """Get the number of replicas for a service"""
        cmd = f"kubectl get deployment {service_name} -n {self.namespace} -o json"
        res = self._run(cmd)

        if res.returncode != 0:
            return 0,0

        try:
            data = json.loads(res.stdout)
            # Spec.replicas è il desired
            desired = data.get("spec", {}).get("replicas", 0)
            # Status.readyReplicas sono quelle attive (se manca è 0)
            current = data.get("status", {}).get("readyReplicas", 0)
            if current is None: current = 0  # Fix per K8s quando scala a 0

            return int(current), int(desired)
        except Exception as e:
            print(f"[ERROR] Error parsing JSON: {e}")

    def get_worker_nodes(self):
        """Return nodes list"""
        cmd = "kubectl get nodes -o jsonpath='{.items[*].status.addresses[?(@.type==\"InternalIP\")].address}'"
        # Oppure per nome: '{.items[*].metadata.name}'
        # Usiamo i nomi per coerenza con lo Swarm driver se serve per SSH, o gli IP.
        # Qui usiamo i nomi host:
        cmd = "kubectl get nodes -o jsonpath='{.items[*].metadata.name}'"
        res = self._run(cmd)
        return res.stdout.strip().split()

    def update_image(self, service_name, image):
        """Update image"""
        print(f"[K8S-DRIVER] Updating {service_name} to image {image}...")
        cmd = f"kubectl set image deployment/{service_name} {service_name}={image} -n {self.namespace}"
        self._run(cmd)

    def crete_dummy_service(self, service_name, replicas):
        """Create a dummy service"""
        print(f"[K8S-DRIVER] Creating dummy deployment {service_name}...")
        # Creiamo un deployment imperativo
        cmd = (f"kubectl create deployment {service_name} --image=alpine:latest --replicas={replicas} "
               f"-n {self.namespace} -- sleep infinity")
        self._run(cmd)

    def remove_service(self, service_name):
        print(f"[K8S-DRIVER] Removing deployment {service_name}...")
        self._run(f"kubectl delete deployment {service_name} -n {self.namespace}")

    def count_runnin_task(self, service_name):
        """Count the number of running tasks about a specific service"""
        cmd = f"kubectl get pods -n {self.namespace} -l app={service_name} --field-selector=status.phase=Running --no-headers | wc -l"
        res = self._run(cmd)
        try:
            return int(res.stdout.strip())
        except:
            return 0

    def reset_cluster(self, services_to_reset=["backend", "frontend"]):
        print("\n[K8S-DRIVER] --- RESETTING CLUSTER ---")
        for svc in services_to_reset:
            self.scale_service(svc, 0)

        print("[K8S-DRIVER] Waiting for termination...")
        time.sleep(5)  # K8s è veloce a terminare

        print("[K8S-DRIVER] Ready \n")

    def trigger_rolling_update(self, service_name):
       """Trigger rolling update,
       K8s creates new pods and terminates olds,
       policy: MaxSurge, maxUnavailable"""
       print(f"[K8S-DRIVER] Triggering rollout restart for {service_name}...")
       # rollout restart forza la ricreazione dei pod mantenendo il servizio attivo
       cmd = f"kubectl rollout restart deployment/{service_name} -n {self.namespace}"
       self._run(cmd)

    def get_nodes_with_pods(self, service_name):
        """
        Returns a list of node names where the pods of the given service are currently running.
        Useful to identify a valid 'victim' node for fault tolerance tests.
        """
        cmd = f"kubectl get pods -n {self.namespace} -l app={service_name} -o jsonpath='{{.items[*].spec.nodeName}}'"
        res = self._run(cmd)

        if res.returncode != 0:
            print(f"[ERROR] Could not get pod nodes: {res.stderr}")
            return []

        # .split() separates the names, set() removes duplicates, list() converts back to list
        node_list = list(set(res.stdout.strip().split()))
        return node_list

    def get_pod_node(self, service_name):
        """Returns the node name where the first pod of the service is running"""
        cmd = (f"kubectl get pod "
               f"-n {self.namespace} "
               f"-l app={service_name} "
               f"--field-selector=status.phase=Running "
               f"-o jsonpath='{{.items[0].spec.nodeName}}'")
        res = self._run(cmd)
        return res.stdout.strip()

    def cordon_node(self, node_name):
        """Marks the node as unschedulable"""
        print(f"[K8S-DRIVER] Cordoning node {node_name}...")
        self._run(f"kubectl cordon {node_name}")

    def uncordon_node(self, node_name):
        """Marks the node as schedulable again"""
        print(f"[K8S-DRIVER] Uncordoning node {node_name}...")
        self._run(f"kubectl uncordon {node_name}")

    def delete_pods_by_label(self, service_name):
        """Deletes all pods associated with a service label to force restart"""
        print(f"[K8S-DRIVER] Deleting pods for {service_name}...")
        self._run(f"kubectl delete pod -n {self.namespace} -l app={service_name}")