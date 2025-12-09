import subprocess
import time
import json
import sys
import os

class SwarmDriver:
    def __init__(self, stack_name="cob-service"):
        self.stack_name = stack_name

    def _run(self, cmd):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def _ssh_exec(self, node, cmd):
        ssh_cmd = f"ssh -o StrictHostKeyChecking=no {node} '{cmd}'"
        print(f"[DRIVER-SSH] Executing on {node}: {cmd}")
        return self._run(ssh_cmd)

    def scale_service(self, service_short_name, replicas):
        full_name = f"{self.stack_name}_{service_short_name}"
        print(f"[DRIVER] Scaling {full_name} to {replicas}..")
        self._run(f"docker service scale {full_name}={replicas}")

    def get_replica_count(self, service_short_name):
        full_name = f"{self.stack_name}_{service_short_name}"
        res = self._run(f"docker service ls --filter name={full_name} --format ''{{{{.Replicas}}}}''")
        try:
            # Se output è vuoto o malformato ritorna 0,0
            line = res.stdout.strip()
            if "/" in line:
                current, desired = line.split("/")
                return int(current), int(desired)
            return 0, 0
        except Exception as e:
            return 0, 0

    def get_worker_nodes(self):
        res = self._run("docker node ls --format '{{.Hostname}}' --filter role=worker")
        return res.stdout.strip().split('\n')

    def update_image(self, service_short_name, image):
        full_name = f"{self.stack_name}_{service_short_name}"
        print(f"[DRIVER] Updating {full_name} to image {image}..")
        self._run(f"docker service update --image {image} --update-order start-first {full_name}")

    def get_cluster_stats(self):
        """
        Ritorna la somma di CPU e RAM usata dai
        container sul nodo corrente (Manager).
        """
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
                # Rimuovi unità e converti
                if "GiB" in mem_str:
                    val = float(mem_str.replace("GiB", "")) * 1024
                elif "MiB" in mem_str:
                    val = float(mem_str.replace("MiB", ""))
                elif "KiB" in mem_str:
                    val = float(mem_str.replace("KiB", "")) / 1024
                elif "B" in mem_str:
                    val = float(mem_str.replace("B", "")) / (1024 * 1024)
                else:
                    val = 0.0

                total_mem_mb += val
            except:
                pass

        return {"cpu_percent": total_cpu, "memory_mb": total_mem_mb}

    def create_dummy_service(self, service_name, replicas):
        """Crea un servizio leggero (Alpine) fuori dallo stack principale"""
        print(f"[DRIVER] Creating dummy service {service_name} with {replicas} replicas...")
        # Usiamo alpine con sleep infinity per avere overhead applicativo quasi nullo
        cmd = f"docker service create --name {service_name} --replicas {replicas} alpine:latest sleep infinity"
        self._run(cmd)

    def remove_service(self, service_name):
        print(f"[DRIVER] Removing service {service_name}...")
        self._run(f"docker service rm {service_name}")

    def count_running_tasks(self, service_name):
        """
        Conta quanti task sono EFFETTIVAMENTE in stato 'Running'.
        Non si fida di 'docker service ls', guarda i singoli processi.
        """
        # Filtriamo per 'current-state=running'
        cmd = f"docker service ps {service_name} --filter desired-state=running --filter 'current-state=running' --format '{{{{.ID}}}}'"
        res = self._run(cmd)
        # Conta le righe non vuote
        return len([line for line in res.stdout.strip().split('\n') if line])

    def reset_cluster(self, service_to_reset=["backend", "frontend"]):
        print("\n[DRIVER] --- RESETTING CLUSTER ---")

        for svc in service_to_reset:
            full_name = f"{self.stack_name}_{svc}"
            self._run(f"docker service scale {full_name}=0")

        print("[DRIVER] Waiting for containers to terminate...")
        max_retries = 30
        for _ in range(max_retries):
            still_alive = False
            # Controlliamo se ci sono task in running state per lo stack
            # Questo comando lista tutti i processi dello stack che non sono Shutdown
            cmd = f"docker stack ps {self.stack_name} --filter desired-state=running --format '{{{{.ID}}}}'"
            res = self._run(cmd)
            if res.stdout.strip():
                still_alive = True

            if not still_alive:
                break
            time.sleep(2)

        print("[DRIVER] Cluster clean. Cooling down (10s)...")
        time.sleep(10)
        print("[DRIVER] Ready \n")

