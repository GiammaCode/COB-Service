import subprocess
import json
import time
import re


def run_test():
    print("--- Inizio Test Network Overhead (Overlay) ---")

    net_name = "bench-net"

    # 1. Setup Rete e Servizi
    print("Creazione rete overlay e servizi iperf3...")
    subprocess.run(f"docker network create -d overlay {net_name}", shell=True, stdout=subprocess.DEVNULL)

    # Server sul Manager (swarm09)
    subprocess.run(
        f"docker service create --name iperf-server --network {net_name} --constraint 'node.role==manager' networkstatic/iperf3 -s",
        shell=True, stdout=subprocess.DEVNULL)

    # Client su un Worker (esclude il manager per forzare traffico di rete reale)
    subprocess.run(
        f"docker service create --name iperf-client --network {net_name} --constraint 'node.role==worker' networkstatic/iperf3 -c iperf-server --json",
        shell=True, stdout=subprocess.DEVNULL)

    print("Attesa avvio container (15s)...")
    time.sleep(15)

    # 2. Recupero logs dal client per ottenere i risultati
    # Dobbiamo aspettare che il client finisca il test (default 10s)
    time.sleep(5)

    try:
        cmd = "docker service logs iperf-client --no-task-ids --raw"
        output = subprocess.check_output(cmd, shell=True).decode()

        # Pulizia output per trovare il JSON (iperf a volte stampa roba prima)
        json_match = re.search(r'\{.*\}', output, re.DOTALL)
        if json_match:
            iperf_data = json.loads(json_match.group(0))
            bits_per_second = iperf_data['end']['sum_received']['bits_per_second']
            gbps = bits_per_second / 1e9
        else:
            gbps = 0
            print("Impossibile parsare JSON da iperf.")

    except Exception as e:
        print(f"Errore esecuzione: {e}")
        gbps = -1

    # 3. Cleanup
    subprocess.run("docker service rm iperf-server iperf-client", shell=True, stdout=subprocess.DEVNULL)
    subprocess.run(f"docker network rm {net_name}", shell=True, stdout=subprocess.DEVNULL)

    results = {
        "test_name": "Network Overhead Test",
        "network_type": "Overlay",
        "throughput_gbps": round(gbps, 3),
        "notes": "Traffic routed Manager <-> Worker"
    }

    print("\nRISULTATO TEST RETE:")
    print(json.dumps(results, indent=4))


if __name__ == "__main__":
    run_test()