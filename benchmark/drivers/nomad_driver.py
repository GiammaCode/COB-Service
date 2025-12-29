import subprocess
import json
import time

class NomadDriver:
    def __init__(self, job_name="cob-service"):
        self.job_name = job_name

    def _run(self, cmd):
      return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def scale_service(self, service_name, replicas):
        group_map = {
            "backend": "backend-group",
            "frontend": "frontend-group",
            "database": "db-group"
        }

        target_group = group_map.get(service_name, f"{service_name}-group")
        print(f"[NOMAD-DRIVER] Scaling {target_group} to {replicas} replicas...")

        cmd = f"nomad job scale {self.job_name} {target_group} {replicas}"
        res = self._run(cmd)

        if res.returncode != 0:
            print(f"[ERROR] Failed to scale {target_group}: {res.stderr}")

    def get_replica_count(self, service_name):
        group_map = {
            "backend": "backend-group",
            "frontend": "frontend-group"
        }
        target_group = group_map.get(service_name, f"{service_name}-group")

        cmd = f"nomad job status -json {self.job_name}"
        res = self._run(cmd)

        if res.returncode != 0:
            print(f"[ERROR] Nomad status failed: {res.stderr}")
            return 0, 0

        try:
            data = json.loads(res.stdout)

            # Gestione caso lista (la fix che abbiamo fatto prima)
            if isinstance(data, list):
                if len(data) > 0:
                    data = data[0]
                else:
                    return 0, 0

            desired = 0
            task_groups = data.get("TaskGroups", [])
            for tg in task_groups:
                if tg["Name"] == target_group:
                    desired = tg["Count"]
                    break

            # --- DEBUG PRINTS (AGGIUNGI QUESTO) ---
            summary_section = data.get("Summary", {})
            print(f"[DEBUG] Looking for group: '{target_group}' in keys: {list(summary_section.keys())}")
            # --------------------------------------

            summary = summary_section.get(target_group, {})
            current = summary.get("Running", 0)

            # --- DEBUG PRINTS (AGGIUNGI QUESTO) ---
            print(f"[DEBUG] Service: {service_name} | Target: {target_group} | Current: {current} | Desired: {desired}")
            # --------------------------------------

            return int(current), int(desired)

        except Exception as e:
            print(f"[ERROR] JSON parsing error: {e}")
            return 0, 0


    def reset_cluster(self):
        print("\n[NOMAD-DRIVER] --- RESETTING CLUSTER ---")
        self.scale_service("backend", 2)
        self.scale_service("frontend", 2)

        print("[NOMAD-DRIVER] Waiting for stabilization...")
        time.sleep(5)
        print("[NOMAD-DRIVER] Ready \n")