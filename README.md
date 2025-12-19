![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/Status-Development-orange)
![Docker](https://img.shields.io/badge/Orchestrator-Docker%20Swarm-2496ED)
![K8s](https://img.shields.io/badge/Orchestrator-Kubernetes-326CE5)

# COB-Service: Container Orchestrator Benchmark
COB (Container Orchestrator Benchmark) is a thesis project designed to analyze, stress-test,
and compare the performance of three major container orchestration technologies:

- Docker Swarm
- Kubernetes (K8s)
- HashiCorp Nomad

The goal is to evaluate these platforms under identical workloads using a custom microservices application 
(cob-service) and a suite of automated Python benchmark drivers.

## Supported Orchestrators & Versioning
This repository uses Git Tags to manage the specific configuration and benchmark suite for each orchestrator. 
To reproduce the results for a specific technology, please check out the corresponding tag.

| Orchestrator     | Git Tag      | Status     | Description                                    |
|:-----------------|:-------------|:-----------|:-----------------------------------------------|
| **Docker Swarm** | `v1.0-swarm` | Completed  | Full benchmark suite optimized for Swarm Mode. |
| **Kubernetes**   | `v2.0-k8s`   | Completed  | Benchmark adaptation for K8s clusters.         |
| **Nomad**        | `v3.0-nomad` | Planned    | Planned support for HashiCorp Nomad.           |

### How to Switch Versions
To switch the codebase to the specific orchestrator version you want to test:

````
# For Docker Swarm Benchmark
git checkout v1.0-swarm

# For Kubernetes Benchmark (when available)
git checkout v2.0-k8s

````


## Project Structure

- benchmark/: Contains the Python test suite and drivers
  - .drivers/: Abstraction layer to interact with the specific orchestrator (Swarm, K8s, etc.)
  - .tests/: The actual benchmark scripts (Scalability, Fault Tolerance, Overhead, etc.)
  - .results/: JSON outputs and CSV logs generated during tests.

- deployments/: YAML configuration files for deploying the stack (Docker Stack, K8s Manifests).

- src/: Source code for the microservices application (Frontend React, Backend Flask, Nginx).

## Installation & Prerequisites
1. Requirements
- Python 3.8+
- Docker (and a running cluster: Swarm, K8s, or Nomad depending on the version)
- Access to the cluster manager node (configured in benchmark/config.py)

2. Setup Benchmark Environment
It is recommended to use a virtual environment for the benchmark suite.

````

    cd benchmark
    python3 -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    pip install -r requirements.txt

````

## How to Run Benchmarks
Ensure your target cluster is up and running with the cob-service stack deployed.
1. Configure the Target 
Edit benchmark/config.py to set the correct API_URL and STACK_NAME for your current environment.
2. Run Specific TestsYou can run individual tests directly from the benchmark folder:

````

    # Example: Test Scalability and Load Balancing
    python tests/scalability_load_balancing.py
    
    # Example: Test Fault Tolerance (requires manual node kill)
    python tests/fault_tolerance.py
    
    # Example: Measure Scheduling Overhead
    python tests/scheduling_overhead.py

````

3. Analyze Results
After execution, results are automatically saved in the benchmark/results/ directory as JSON files and CSV
logs for further analysis.

## Benchmark Metrics
The suite analyzes the following metrics:
- Scalability: Request success rate and latency under increasing load (using Locust).
- Fault Tolerance: Recovery Time Objective (RTO) and service availability during node failures.
- Scheduling Overhead: Time required to schedule and start varying numbers of containers.
- Resource Overhead: CPU and RAM consumption of the control plane (e.g., dockerd, kubelet).
- Rolling Updates: Service availability during zero-downtime updates.

## License
This project is part of a Computer Engineering Thesis.Distributed under the MIT License.