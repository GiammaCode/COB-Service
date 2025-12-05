"""
Test: Resource Overhead
Taxonomy Category: Resource Management

Measures the resource cost of running Swarm itself:
1. CPU/Memory used by Swarm components (dockerd, containerd)
2. Overhead per container managed
3. Comparison between idle and active states
4. Network overhead from overlay networking

This helps understand the "tax" of using Swarm vs bare containers.
"""

import subprocess
import time
import json
import sys
import statistics
import re

# Configuration
STACK_NAME = "cob-service"
SERVICE_NAME = f"{STACK_NAME}_backend"
SAMPLE_INTERVAL = 2  # seconds between samples
NUM_SAMPLES = 10


def log(message):
    """Output to stderr to not interfere with final JSON"""
    print(f"[OVERHEAD] {message}", file=sys.stderr)


def get_process_stats(process_name):
    """Get CPU and memory stats for a process"""
    cmd = f"ps aux | grep -E '{process_name}' | grep -v grep"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        total_cpu = 0
        total_mem = 0
        total_rss_kb = 0
        count = 0

        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 11:
                    try:
                        cpu = float(parts[2])
                        mem = float(parts[3])
                        rss = int(parts[5])  # RSS in KB
                        total_cpu += cpu
                        total_mem += mem
                        total_rss_kb += rss
                        count += 1
                    except (ValueError, IndexError):
                        continue

        if count > 0:
            return {
                "process_count": count,
                "cpu_percent": round(total_cpu, 2),
                "mem_percent": round(total_mem, 2),
                "rss_mb": round(total_rss_kb / 1024, 2)
            }
        return None
    except Exception as e:
        return {"error": str(e)}


def get_docker_system_stats():
    """Get Docker system-wide resource usage"""
    try:
        # Docker system df
        cmd = "docker system df --format '{{json .}}'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        df_stats = []
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    df_stats.append(json.loads(line))
                except:
                    pass

        # Docker info
        cmd = "docker info --format '{{json .}}'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        info = {}
        if result.stdout.strip():
            try:
                info = json.loads(result.stdout.strip())
            except:
                pass

        return {
            "disk_usage": df_stats,
            "containers_running": info.get("ContainersRunning", 0),
            "containers_total": info.get("Containers", 0),
            "images": info.get("Images", 0),
            "swarm_active": info.get("Swarm", {}).get("LocalNodeState") == "active",
            "swarm_managers": info.get("Swarm", {}).get("Managers", 0),
            "swarm_nodes": info.get("Swarm", {}).get("Nodes", 0)
        }
    except Exception as e:
        return {"error": str(e)}


def get_container_overhead():
    """Measure overhead per container"""
    cmd = "docker stats --no-stream --format '{{json .}}'"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

        containers = []
        total_cpu = 0
        total_mem_mb = 0

        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    stats = json.loads(line)

                    # Parse CPU
                    cpu_str = stats.get("CPUPerc", "0%").replace("%", "")
                    cpu = float(cpu_str) if cpu_str else 0

                    # Parse memory
                    mem_str = stats.get("MemUsage", "0MiB / 0MiB").split("/")[0].strip()
                    mem_mb = parse_memory(mem_str)

                    containers.append({
                        "name": stats.get("Name", "unknown"),
                        "cpu_percent": cpu,
                        "memory_mb": mem_mb
                    })

                    total_cpu += cpu
                    total_mem_mb += mem_mb
                except:
                    continue

        return {
            "container_count": len(containers),
            "total_cpu_percent": round(total_cpu, 2),
            "total_memory_mb": round(total_mem_mb, 2),
            "avg_cpu_per_container": round(total_cpu / len(containers), 2) if containers else 0,
            "avg_memory_per_container_mb": round(total_mem_mb / len(containers), 2) if containers else 0,
            "containers": containers
        }
    except Exception as e:
        return {"error": str(e)}


def parse_memory(mem_str):
    """Parse memory string like '125.4MiB' or '1.2GiB' to MB"""
    try:
        mem_str = mem_str.strip()
        if 'GiB' in mem_str:
            return float(mem_str.replace('GiB', '')) * 1024
        elif 'MiB' in mem_str:
            return float(mem_str.replace('MiB', ''))
        elif 'KiB' in mem_str:
            return float(mem_str.replace('KiB', '')) / 1024
        elif 'GB' in mem_str:
            return float(mem_str.replace('GB', '')) * 1000
        elif 'MB' in mem_str:
            return float(mem_str.replace('MB', ''))
        else:
            return float(mem_str)
    except:
        return 0


def measure_swarm_components():
    """Measure resource usage of Swarm/Docker components"""
    log("\n--- Measuring Swarm Component Overhead ---")

    components = {
        "dockerd": "dockerd",
        "containerd": "containerd",
        "containerd-shim": "containerd-shim"
    }

    samples = {comp: [] for comp in components}

    for i in range(NUM_SAMPLES):
        log(f"  Sample {i + 1}/{NUM_SAMPLES}")

        for comp_name, proc_pattern in components.items():
            stats = get_process_stats(proc_pattern)
            if stats and "error" not in stats:
                samples[comp_name].append(stats)

        time.sleep(SAMPLE_INTERVAL)

    # Aggregate results
    results = {}
    for comp_name, comp_samples in samples.items():
        if comp_samples:
            results[comp_name] = {
                "samples": len(comp_samples),
                "cpu_percent": {
                    "min": round(min(s["cpu_percent"] for s in comp_samples), 2),
                    "max": round(max(s["cpu_percent"] for s in comp_samples), 2),
                    "avg": round(statistics.mean(s["cpu_percent"] for s in comp_samples), 2)
                },
                "memory_mb": {
                    "min": round(min(s["rss_mb"] for s in comp_samples), 2),
                    "max": round(max(s["rss_mb"] for s in comp_samples), 2),
                    "avg": round(statistics.mean(s["rss_mb"] for s in comp_samples), 2)
                }
            }

    return results


def measure_idle_vs_load():
    """Compare resource usage at idle vs under load"""
    log("\n--- Measuring Idle vs Load Overhead ---")

    # Measure idle state
    log("  Measuring idle state...")
    time.sleep(3)  # Let system settle

    idle_samples = []
    for i in range(5):
        idle_samples.append(get_container_overhead())
        time.sleep(1)

    idle_avg = {
        "cpu_percent": statistics.mean(s["total_cpu_percent"] for s in idle_samples if "total_cpu_percent" in s),
        "memory_mb": statistics.mean(s["total_memory_mb"] for s in idle_samples if "total_memory_mb" in s)
    }

    # Generate load
    log("  Generating load...")
    import threading
    import requests

    stop_load = threading.Event()

    def generate_load():
        while not stop_load.is_set():
            try:
                requests.get("http://localhost:5001/", timeout=2)
            except:
                pass
            time.sleep(0.01)

    # Start load threads
    threads = []
    for _ in range(10):
        t = threading.Thread(target=generate_load)
        t.start()
        threads.append(t)

    # Measure under load
    time.sleep(3)  # Let load build up

    load_samples = []
    for i in range(5):
        load_samples.append(get_container_overhead())
        time.sleep(1)

    # Stop load
    stop_load.set()
    for t in threads:
        t.join()

    load_avg = {
        "cpu_percent": statistics.mean(s["total_cpu_percent"] for s in load_samples if "total_cpu_percent" in s),
        "memory_mb": statistics.mean(s["total_memory_mb"] for s in load_samples if "total_memory_mb" in s)
    }

    return {
        "idle": {
            "cpu_percent": round(idle_avg["cpu_percent"], 2),
            "memory_mb": round(idle_avg["memory_mb"], 2)
        },
        "under_load": {
            "cpu_percent": round(load_avg["cpu_percent"], 2),
            "memory_mb": round(load_avg["memory_mb"], 2)
        },
        "delta": {
            "cpu_increase_percent": round(load_avg["cpu_percent"] - idle_avg["cpu_percent"], 2),
            "memory_increase_mb": round(load_avg["memory_mb"] - idle_avg["memory_mb"], 2)
        }
    }


def measure_network_overhead():
    """Measure network-related overhead from overlay networking"""
    log("\n--- Measuring Network Overhead ---")

    # Count network namespaces (overlay creates these)
    cmd = "ls /var/run/docker/netns 2>/dev/null | wc -l"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    netns_count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0

    # Count overlay networks
    cmd = "docker network ls --filter driver=overlay --format '{{.Name}}' | wc -l"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    overlay_count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0

    # Check for VXLAN interfaces
    cmd = "ip -o link show type vxlan 2>/dev/null | wc -l"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    vxlan_count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0

    return {
        "network_namespaces": netns_count,
        "overlay_networks": overlay_count,
        "vxlan_interfaces": vxlan_count,
        "interpretation": (
            f"Swarm manages {overlay_count} overlay networks using VXLAN encapsulation. "
            f"Each adds ~50 bytes overhead per packet."
        )
    }


def calculate_total_overhead(components, containers, system):
    """Calculate total Swarm overhead"""
    total = {
        "swarm_components_mb": 0,
        "container_runtime_mb": 0,
        "total_overhead_mb": 0
    }

    # Swarm components
    for comp_name, stats in components.items():
        if "memory_mb" in stats:
            total["swarm_components_mb"] += stats["memory_mb"]["avg"]

    # Container runtime (containerd-shim per container)
    if "containerd-shim" in components:
        shim_memory = components["containerd-shim"]["memory_mb"]["avg"]
        container_count = containers.get("container_count", 0)
        if container_count > 0:
            total["per_container_shim_mb"] = round(shim_memory / container_count, 2)

    total["swarm_components_mb"] = round(total["swarm_components_mb"], 2)
    total["total_overhead_mb"] = round(
        total["swarm_components_mb"] + containers.get("total_memory_mb", 0), 2
    )

    return total


def run_resource_overhead_test():
    """Run complete resource overhead test"""
    log("Starting Resource Overhead test")

    # Get system info
    system_stats = get_docker_system_stats()
    log(f"Swarm active: {system_stats.get('swarm_active')}")
    log(f"Containers running: {system_stats.get('containers_running')}")

    # Measure components
    components = measure_swarm_components()

    # Measure containers
    log("\n--- Measuring Container Overhead ---")
    container_stats = get_container_overhead()
    log(f"  Containers: {container_stats.get('container_count', 0)}")
    log(f"  Total CPU: {container_stats.get('total_cpu_percent', 0)}%")
    log(f"  Total Memory: {container_stats.get('total_memory_mb', 0)} MB")

    # Measure idle vs load
    idle_vs_load = measure_idle_vs_load()

    # Measure network overhead
    network = measure_network_overhead()

    # Calculate totals
    totals = calculate_total_overhead(components, container_stats, system_stats)

    output = {
        "test_name": "resource_overhead",
        "category": "resource_management",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "sample_interval": SAMPLE_INTERVAL,
            "num_samples": NUM_SAMPLES
        },
        "status": "passed",
        "system_info": system_stats,
        "swarm_components": components,
        "container_overhead": container_stats,
        "idle_vs_load": idle_vs_load,
        "network_overhead": network,
        "totals": totals,
        "summary": {
            "dockerd_memory_mb": components.get("dockerd", {}).get("memory_mb", {}).get("avg"),
            "containerd_memory_mb": components.get("containerd", {}).get("memory_mb", {}).get("avg"),
            "total_swarm_overhead_mb": totals.get("swarm_components_mb"),
            "avg_memory_per_container_mb": container_stats.get("avg_memory_per_container_mb"),
            "cpu_increase_under_load": idle_vs_load.get("delta", {}).get("cpu_increase_percent")
        },
        "interpretation": generate_interpretation(components, container_stats, idle_vs_load)
    }

    print(json.dumps(output, indent=2))


def generate_interpretation(components, containers, idle_vs_load):
    """Generate human-readable interpretation"""
    points = []

    # Docker daemon overhead
    dockerd_mem = components.get("dockerd", {}).get("memory_mb", {}).get("avg", 0)
    if dockerd_mem:
        if dockerd_mem < 100:
            points.append(f"Docker daemon memory usage is low ({dockerd_mem} MB)")
        elif dockerd_mem < 300:
            points.append(f"Docker daemon memory usage is moderate ({dockerd_mem} MB)")
        else:
            points.append(f"Docker daemon memory usage is high ({dockerd_mem} MB)")

    # Per-container overhead
    avg_per_container = containers.get("avg_memory_per_container_mb", 0)
    if avg_per_container:
        points.append(f"Average memory per container: {avg_per_container} MB")

    # Load impact
    cpu_delta = idle_vs_load.get("delta", {}).get("cpu_increase_percent", 0)
    if cpu_delta > 50:
        points.append(f"High CPU increase under load (+{cpu_delta}%) - good resource utilization")
    elif cpu_delta > 10:
        points.append(f"Moderate CPU increase under load (+{cpu_delta}%)")
    else:
        points.append(f"Low CPU change under load (+{cpu_delta}%) - containers may be I/O bound")

    return points


if __name__ == "__main__":
    run_resource_overhead_test()