import subprocess
import json
import time
import re
import sys


def cleanup():
    """Rimuove servizi e reti residui per evitare errori"""
    print("   -> Esecuzione pulizia risorse pre/post test...")
    # Ignoriamo stderr per evitare confusione se non esistono
    subprocess.run("docker service rm iperf-server iperf-client", shell=True, stderr=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL)
    subprocess.run("docker network rm bench-net", shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    time.sleep(3)  # Tempo tecnico per lo svuotamento della rete


def run_test():
    print("--- Inizio Test Network Overhead (Overlay) ---")

    net_name = "bench-net"

    # 1. Pulizia Preventiva
    cleanup()

    try:
        # 2. Setup Rete e Servizi
        print("1. Creazione rete overlay...")
        subprocess.check_call(f"docker network create -d overlay {net_name}", shell=True)

        print("2. Avvio Server iperf3 (su swarm09)...")
        # Constraint: forza l'esecuzione sul manager specificato
        subprocess.check_call(
            f"docker service create --name iperf-server --network {net_name} --constraint 'node.hostname==swarm09' networkstatic/iperf3 -s",
            shell=True)

        print("3. Avvio Client iperf3 (su nodo REMOTO)...")
        # MODIFICA CHIAVE: Invece di 'node.role==worker', usiamo 'node.hostname!=swarm09'.
        # Questo forza il container su swarm10 o swarm11, indipendentemente dal loro ruolo (Manager/Worker).
        subprocess.check_call(
            f"docker service create --name iperf-client --network {net_name} --constraint 'node.hostname!=swarm09' networkstatic/iperf3 -c iperf-server -J",
            shell=True)

        print("4. Attesa esecuzione test (30s)...")
        # Loop visivo per l'attesa
        for i in range(30):
            sys.stdout.write(f"\r   Attesa completamento e download... {30 - i}s")
            sys.stdout.flush()
            time.sleep(1)
        print("\n")

        # 3. Recupero logs dal client
        print("5. Recupero risultati...")
        cmd = "docker service logs iperf-client --no-task-ids --raw"
        try:
            output = subprocess.check_output(cmd, shell=True).decode()
        except subprocess.CalledProcessError:
            output = ""

        # Debug: se l'output è vuoto
        if not output.strip():
            print("ATTENZIONE: Output vuoto. Controllo stato servizio...")
            subprocess.run("docker service ps iperf-client", shell=True)
            gbps = 0
        else:
            # Pulizia output per trovare il JSON
            json_match = re.search(r'\{.*\}', output, re.DOTALL)
            if json_match:
                try:
                    iperf_data = json.loads(json_match.group(0))
                    # Estrazione dati dal JSON di iperf3
                    bits_per_second = iperf_data.get('end', {}).get('sum_received', {}).get('bits_per_second', 0)
                    gbps = bits_per_second / 1e9
                except Exception as e:
                    print(f"Errore parsing JSON interno: {e}")
                    gbps = 0
            else:
                gbps = 0
                print("Impossibile trovare JSON valido nell'output.")
                print(f"Log parziali:\n{output[:300]}...")

    except subprocess.CalledProcessError as e:
        print(f"Errore esecuzione comando Docker: {e}")
        gbps = -1
    except KeyboardInterrupt:
        print("\nTest interrotto manualmente.")
        gbps = -1
    except Exception as e:
        print(f"Errore generico: {e}")
        gbps = -1
    finally:
        # 4. Cleanup Finale
        cleanup()

    results = {
        "test_name": "Network Overhead Test",
        "network_type": "Overlay",
        "throughput_gbps": round(gbps, 3),
        "notes": "Traffic routed swarm09 <-> Remote Node (Anti-Affinity)"
    }

    print("\nRISULTATO TEST RETE:")
    print(json.dumps(results, indent=4))


if __name__ == "__main__":
    run_test()