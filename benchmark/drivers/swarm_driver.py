import subprocess
import time
import json

class SwarmDriver:
    def __init__(self, stack_name="cob-service"):
        self.stack_name = stack_name

    def _run(self, cmd):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def scale_service(self, service_short_name, replicas):
        full_name = f"{self.stack_name}_{service_short_name}"
        print(f"[DRIVER] Scaling {full_name} to {replicas}..")
        self._run(f"docker service scale {full_name}=={replicas}")

    def get_replica_count(self, service_short_name):
        full_name = f"{self.stack_name}_{service_short_name}"
        res = self._run(f"docker service ls --filter name={full_name} --format ''{{{{.Replicas}}}}''")
        try:
            current, desired = res.stdout.split()
            return int(current), int(desired)
        except:
            return 0, 0

    def update_image(self, service_short_name, image):
        full_name = f"{self.stack_name}_{service_short_name}"
        print(f"[DRIVER] Updating {full_name} to image {image}..")
        # --update-order start-first è tipico per zero-downtime
        self._run(f"docker service update --image {image} --update-order start-first {full_name}")

    def drain_node(self, node_hostname):
        print(f"[DRIVER] Draining node {node_hostname}...")
        self._run(f"docker node update --availability drain {node_hostname}")

    def active_node(self, node_hostname):
        print(f"[DRIVER] Activating node {node_hostname}...")
        self._run(f"docker node update --availability active {node_hostname}")

    def get_worker_nodes(self):
        res = self._run("docker node ls --format '{{.Hostname}}' --filter role=worker")
        return res.stdout.strip().split('\n')

    def get_cluster_resources(self):
        # Questo è "White Box" ma necessario per test Resource Overhead
        # Su K8s useresti 'kubectl top nodes'
        # Qui usiamo un hack sommando docker stats o leggendo info sistema
        # Per semplicità, qui ritorniamo dati mock o letti da docker system df
        res = self._run("docker system df --format '{{json .}}'")
        return res.stdout  # Da parsare

