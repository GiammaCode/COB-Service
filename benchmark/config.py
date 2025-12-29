"""
Global Configuration for the Benchmark Suite.
"""

# Stack/Namespace name (used for both Swarm and K8s legacy compatibility)
STACK_NAME = "cob-service"

# Name of the main backend service (K8s deployment name)
SERVICE_NAME = "backend"

# Base API URL
#API_URL = "http://192.168.15.9/api"

# Nomad
API_URL = "http://192.168.15.10/api"