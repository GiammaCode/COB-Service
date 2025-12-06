import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
from drivers.swarm_driver import SwarmDriver

def test_resource_overhead():
    driver = SwarmDriver()
    print("--- Start Resource Overhead ---")

    # 1. Empty Cluster Stats
    driver.scale_service("backend", 0)
    # Qui dovresti implementare nel driver la lettura della RAM dei processi Docker
    # Per ora simuliamo la chiamata al driver
    print("Measuring base overhead...")
    # base_mem = driver.get_system_resources()

    # 2. Loaded Cluster Stats
    driver.scale_service("backend", 20)
    print("Measuring loaded overhead...")
    # load_mem = driver.get_system_resources()

    # Delta
    print("Result: Delta analysis (Implementation dependent on driver internals)")


if __name__ == "__main__":
    test_resource_overhead()