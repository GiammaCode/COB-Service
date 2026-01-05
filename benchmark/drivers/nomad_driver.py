import subprocess
import json
import time
import os
import textwrap


class NomadDriver:
    """
    Driver class to interact with HashiCorp Nomad via CLI.
    Used for scaling, deploying, and monitoring services during tests.
    """

    # Mapping between abstract service names and actual Nomad Task Group names
    GROUP_MAP = {
        "backend": "backend-group",
        "frontend": "frontend-group",
        "database": "db-group"
    }

    def __init__(self, job_name="cob-service"):
        self.job_name = job_name

    def _run(self, cmd):
        """Executes a shell command and returns the result object."""
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def _get_group_name(self, service_name):
        """Helper to resolve the Nomad Task Group name."""
        return self.GROUP_MAP.get(service_name, f"{service_name}-group")

    def scale_service(self, service_name, replicas):
        """
        Scales a specific task group to the desired number of replicas.
        """
        target_group = self._get_group_name(service_name)
        print(f"[NOMAD-DRIVER] Scaling {target_group} to {replicas} replicas...")

        cmd = f"nomad job scale {self.job_name} {target_group} {replicas}"
        res = self._run(cmd)

        if res.returncode != 0:
            print(f"[ERROR] Failed to scale {target_group}: {res.stderr}")

    def get_replica_count(self, service_name):
        """
        Retrieves the (Current, Desired) replica counts for a service.
        Parses 'nomad job status -json'.
        """
        target_group = self._get_group_name(service_name)

        # Possible names to look for in the JSON structure
        possible_names = [target_group, service_name]

        cmd = f"nomad job status -json {self.job_name}"
        res = self._run(cmd)

        if res.returncode != 0:
            print(f"[ERROR] Nomad status failed: {res.stderr}")
            return 0, 0

        try:
            data = json.loads(res.stdout)

            # Handle list response (cli quirk in some versions)
            if isinstance(data, list):
                data = data[0] if len(data) > 0 else {}

            # --- 1. DETERMINE DESIRED COUNT ---
            desired = 0
            task_groups = data.get("TaskGroups", [])
            for tg in task_groups:
                if tg["Name"] in possible_names:
                    desired = tg["Count"]
                    break

            # --- 2. RETRIEVE CURRENT RUNNING COUNT ---
            job_summary = data.get("Summary", {})

            # Handle nested Summary structure
            if "Summary" in job_summary and isinstance(job_summary["Summary"], dict):
                group_map_data = job_summary["Summary"]
            else:
                group_map_data = job_summary

            # Find the target group summary
            final_summary = group_map_data.get(target_group)
            if not final_summary:
                final_summary = group_map_data.get(service_name, {})

            current = final_summary.get("Running", 0)

            # Safety fallback: if Running > 0 but Desired is 0 (transient state),
            # assume Desired equals Current to avoid blocking tests.
            if current > 0 and desired == 0:
                desired = current

            return int(current), int(desired)

        except Exception as e:
            print(f"[ERROR] JSON parsing error in get_replica_count: {e}")
            return 0, 0

    def trigger_rolling_update(self, service_name=None):
        """
        Forces a rolling restart of the job.
        Nomad handles the rolling logic based on the 'update' stanza in the job file.
        """
        print(f"[NOMAD-DRIVER] Triggering Rolling Restart for job '{self.job_name}'...")

        cmd = f"nomad job restart {self.job_name}"
        res = self._run(cmd)

        if res.returncode != 0:
            print(f"[ERROR] Failed to trigger rolling update: {res.stderr}")
        else:
            print(f"[NOMAD-DRIVER] Rolling update triggered successfully.")

    def wait_for_deployment_completion(self, timeout=120):
        """
        Waits for the latest deployment to reach 'successful' status.
        Returns the elapsed time in seconds.
        """
        print(f"[NOMAD-DRIVER] Waiting for deployment completion (timeout={timeout}s)...")
        start_time = time.time()

        # Allow Nomad a moment to register the new deployment ID
        time.sleep(2)

        # 1. Find the latest Deployment ID
        cmd_list = f"nomad deployment list -json -job {self.job_name}"
        res = self._run(cmd_list)

        if res.returncode != 0:
            print(f"[ERROR] Could not list deployments: {res.stderr}")
            return 0

        try:
            deployments = json.loads(res.stdout)
            if not deployments:
                print("[WARNING] No deployments found.")
                return 0

            # Nomad usually sorts by date desc, taking the first one
            latest_deployment = deployments[0]
            deploy_id = latest_deployment['ID']
            print(f"[NOMAD-DRIVER] Tracking Deployment ID: {deploy_id}")

        except Exception as e:
            print(f"[ERROR] JSON parsing error (list): {e}")
            return 0

        # 2. Monitor Loop
        while time.time() - start_time < timeout:
            cmd_status = f"nomad deployment status -json {deploy_id}"
            res_status = self._run(cmd_status)

            if res_status.returncode == 0:
                try:
                    data = json.loads(res_status.stdout)
                    status = data.get("Status")

                    # Possible statuses: running, successful, failed, cancelled
                    if status == "successful":
                        elapsed = time.time() - start_time
                        print(f"[NOMAD-DRIVER] Deployment SUCCESSFUL in {elapsed:.2f}s")
                        return elapsed

                    elif status in ["failed", "cancelled"]:
                        print(f"[ERROR] Deployment {status}!")
                        return time.time() - start_time

                    # If 'running', continue waiting...

                except Exception as e:
                    print(f"[DEBUG] Error parsing deployment status: {e}")

            time.sleep(1)

        print(f"[ERROR] Timeout waiting for deployment {deploy_id}")
        return timeout

    def get_active_nodes(self, service_name):
        """
        Returns a list of Node Names where the specified service is running.
        Useful for identifying victim nodes for fault tolerance tests.
        """
        target_group = self._get_group_name(service_name)

        cmd = f"nomad job status -json {self.job_name}"
        res = self._run(cmd)

        if res.returncode != 0:
            print(f"[ERROR] Could not get job status: {res.stderr}")
            return []

        active_nodes = set()
        try:
            data = json.loads(res.stdout)
            if isinstance(data, list):
                data = data[0] if len(data) > 0 else {}

            allocations = data.get("Allocations", [])

            for alloc in allocations:
                # Check correct group and running status
                if alloc["TaskGroup"] == target_group and alloc["ClientStatus"] == "running":
                    node_name = alloc.get("NodeName", "unknown")
                    active_nodes.add(node_name)

        except Exception as e:
            print(f"[ERROR] JSON parsing error in get_active_nodes: {e}")
            return []

        return list(active_nodes)

    def create_dummy_service(self, service_name, replicas):
        """
        Creates a temporary Nomad job with N lightweight tasks (Alpine).
        Used for scheduling overhead/burst tests.
        """
        print(f"[NOMAD-DRIVER] Submitting job '{service_name}' with {replicas} replicas...")

        # Minimal HCL template using textwrap to avoid indentation issues
        job_hcl = textwrap.dedent(f"""
        job "{service_name}" {{
          datacenters = ["dc1"]
          type        = "service"

          group "bench-group" {{
            count = {replicas}

            network {{
              mode = "bridge"
            }}

            task "alpine" {{
              driver = "docker"

              config {{
                image   = "alpine:latest"
                command = "sleep"
                args    = ["3600"]
              }}

              resources {{
                cpu    = 20
                memory = 20
              }}
            }}
          }}
        }}
        """)

        filename = f"/tmp/{service_name}.nomad"
        try:
            with open(filename, "w") as f:
                f.write(job_hcl)

            cmd = f"nomad job run {filename}"
            res = self._run(cmd)

            if res.returncode != 0:
                print(f"[ERROR] Failed to submit dummy job: {res.stderr}")
        finally:
            # Cleanup temp file
            if os.path.exists(filename):
                os.remove(filename)

    def remove_service(self, service_name):
        """
        Stops and Purges a job completely.
        """
        print(f"[NOMAD-DRIVER] Removing job '{service_name}'...")
        cmd = f"nomad job stop -purge {service_name}"
        self._run(cmd)

    def count_running_tasks(self, service_name):
        """
        Counts total tasks in 'running' state for a specific job.
        Aggregates counts from all task groups.
        """
        cmd = f"nomad job status -json {service_name}"
        res = self._run(cmd)

        if res.returncode != 0:
            return 0

        try:
            data = json.loads(res.stdout)
            if isinstance(data, list):
                if not data: return 0
                data = data[0]

            summary = data.get("Summary", {})

            # Handle recursive Summary object if present
            groups = summary.get("Summary", summary)

            total_running = 0
            if isinstance(groups, dict):
                for _, stats in groups.items():
                    total_running += stats.get("Running", 0)

            return total_running

        except Exception as e:
            return 0

    def reset_cluster(self):
        """
        Resets the main service to a known baseline (2 backend, 2 frontend).
        """
        print("\n[NOMAD-DRIVER] --- RESETTING CLUSTER ---")
        self.scale_service("backend", 2)
        self.scale_service("frontend", 2)

        print("[NOMAD-DRIVER] Waiting for stabilization...")
        time.sleep(5)
        print("[NOMAD-DRIVER] Ready \n")