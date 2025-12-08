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
        print(f"docker service scale {full_name}={replicas}")
        self._run(f"docker service scale {full_name}={replicas}")

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

    def get_cluster_stats(self):
        """
        Ritorna la somma di CPU e RAM usata da tutti i container.
        Nota: Questo è un approccio 'best effort' usando docker stats sul manager.
        In un cluster vero dovresti sommare le stats di tutti i nodi.
        Per la tesi, se lanci i test dal manager, questo ti dà una stima locale o
        puoi usare 'docker stats --no-stream' se hai accesso socket a tutti.
        """
        # Esegue docker stats una volta sola (--no-stream) e formatta in JSON
        cmd = "docker stats --no-stream --format '{{.CPUPerc}} {{.MemUsage}}'"
        res = self._run(cmd)

        total_cpu = 0.0
        total_mem_mb = 0.0

        for line in res.stdout.strip().split('\n'):
            if not line: continue
            try:
                parts = line.split()
                # CPU: "0.50%" -> 0.50
                cpu_str = parts[0].replace('%', '')
                total_cpu += float(cpu_str)

                # MEM: "20.5MiB / 100MiB" -> prendiamo 20.5MiB
                mem_str = parts[1]  # "20.5MiB"
                val_str = mem_str[:-3]  # "20.5"
                unit = mem_str[-3:]  # "MiB"

                val = float(val_str)
                if unit == "GiB":
                    val *= 1024
                elif unit == "KiB":
                    val /= 1024

                total_mem_mb += val
            except:
                pass

        return {"cpu_percent": total_cpu, "memory_mb": total_mem_mb}

