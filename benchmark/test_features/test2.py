import subprocess
import json
import time
import re
import sys


def cleanup():
    """Rimuove servizi e reti residui per evitare errori"""
    print("   -> Esecuzione pulizia risorse pre/post test...")
    subprocess.run("docker service rm iperf-server iperf-client", shell=True, stderr=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL)
    subprocess.run("docker network rm bench-net", shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    time.sleep(2)  # Dai tempo a Docker di recepire la rimozione


def run_test():
    print("--- Inizio Test Network Overhead (Overlay) ---")

    net_name = "bench-net"

    # 1. Pulizia Preventiva
    cleanup()

    try:
        # 2. Setup Rete e Servizi
        print("1. Creazione rete overlay...")
        # Rimuovi stdout=subprocess.DEVNULL per vedere se si blocca qui
        subprocess.check_call(f"docker network create -d overlay {net_name}", shell=True)

        print("2. Avvio Server iperf3 (su Manager)...")
        subprocess.check_call(
            f"docker service create --name iperf-server --network {net_name} --constraint 'node.role==manager' networkstatic/iperf3 -s",
            shell=True)

        print("3. Avvio Client iperf3 (su Worker)...")
        # Il client deve partire dopo che il server è pronto, ma docker gestisce il retry.
        # Aggiungiamo constraint worker per forzare traffico di rete reale
        subprocess.check_call(
            f"docker service create --name iperf-client --network {net_name} --constraint 'node.role==worker' networkstatic/iperf3 -c iperf-server -J",
            shell=True)

        print("4. Attesa esecuzione test (30s per pull immagini e test)...")
        # Aumentato a 30s perché se deve scaricare l'immagine ci mette tempo
        for i in range(30):
            sys.stdout.write(f"\r   Attesa... {30 - i}s")
            sys.stdout.flush()
            time.sleep(1)
        print("\n")

        # 3. Recupero logs dal client
        print("5. Recupero risultati...")
        cmd = "docker service logs iperf-client --no-task-ids --raw"
        output = subprocess.check_output(cmd, shell=True).decode()

        # Debug: se l'output è vuoto, significa che il container non è partito o è in errore
        if not output.strip():
            print("ATTENZIONE: Output dei log vuoto. Il container client potrebbe essere in stato 'Pending' o 'Error'.")
            subprocess.run("docker service ps iperf-client", shell=True)
            gbps = 0
        else:
            # Pulizia output per trovare il JSON
            json_match = re.search(r'\{.*\}', output, re.DOTALL)
            if json_match:
                try:
                    iperf_data = json.loads(json_match.group(0))
                    # iperf3 JSON structure: end -> sum_received -> bits_per_second
                    bits_per_second = iperf_data.get('end', {}).get('sum_received', {}).get('bits_per_second', 0)
                    gbps = bits_per_second / 1e9
                except Exception as e:
                    print(f"Errore parsing JSON interno: {e}")
                    gbps = 0
            else:
                gbps = 0
                print("Impossibile trovare JSON valido nell'output.")
                print(f"Output Grezzo:\n{output[:200]}...")  # Stampa i primi 200 carattteri per debug

    except subprocess.CalledProcessError as e:
        print(f"Errore esecuzione comando Docker: {e}")
        gbps = -1
    except Exception as e:
        print(f"Errore generico: {e}")
        gbps = -1
    finally:
        # 4. Cleanup Finale (sempre eseguito)
        cleanup()

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