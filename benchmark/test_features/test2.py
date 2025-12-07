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
    time.sleep(3)


def run_test():
    print("--- Inizio Test Network Overhead (Overlay) ---")

    net_name = "bench-net"

    # 1. Pulizia Preventiva
    cleanup()

    try:
        # 2. Setup Rete e Servizi
        print("1. Creazione rete overlay...")
        subprocess.check_call(f"docker network create -d overlay {net_name}", shell=True)

        print("2. Avvio Server iperf3 (sul Manager)...")
        subprocess.check_call(
            f"docker service create --name iperf-server --network {net_name} --constraint 'node.role==manager' networkstatic/iperf3 -s",
            shell=True)

        print("3. Avvio Client iperf3 (su un Worker)...")
        # Nota: iperf3 con -J produce JSON, ma se fallisce la connessione stampa testo semplice.
        subprocess.check_call(
            f"docker service create --name iperf-client --network {net_name} --constraint 'node.role==worker' networkstatic/iperf3 -c iperf-server -J",
            shell=True)

        print("4. Attesa esecuzione test (30s)...")
        for i in range(30):
            sys.stdout.write(f"\r   Attesa completamento... {30 - i}s")
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

        gbps = 0

        # Debug: se l'output è vuoto
        if not output.strip():
            print("ATTENZIONE: Output vuoto. Il container potrebbe essere crashato o pending.")
        else:
            # FIX: Regex più specifica. Iperf3 JSON inizia sempre con un oggetto che ha la chiave "start"
            # Cerchiamo '{' seguito da spazi/a-capo e poi "start":
            json_match = re.search(r'(\{.*"start":.*\}\s*$)', output, re.DOTALL)

            # Se il primo tentativo fallisce, proviamo la vecchia regex ma stampiamo l'errore se fallisce
            if not json_match:
                json_match = re.search(r'\{.*\}', output, re.DOTALL)

            if json_match:
                json_str = json_match.group(0)
                try:
                    iperf_data = json.loads(json_str)

                    # Verifica se c'è un errore riportato nel JSON (es. "error": "connection refused")
                    if "error" in iperf_data:
                        print(f"ERRORE IPERF RILEVATO: {iperf_data['error']}")
                        gbps = -1
                    else:
                        bits_per_second = iperf_data.get('end', {}).get('sum_received', {}).get('bits_per_second', 0)
                        gbps = bits_per_second / 1e9

                except json.JSONDecodeError as e:
                    print(f"ERRORE PARSING JSON: {e}")
                    print(f"--- OUTPUT GREZZO (DEBUG) ---\n{output}\n-----------------------------")
                    gbps = 0
            else:
                print("IMPOSSIBILE TROVARE JSON VALIDO NEI LOG.")
                print(f"--- OUTPUT GREZZO (DEBUG) ---\n{output}\n-----------------------------")
                gbps = 0

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
        "notes": "Traffic routed Manager (Leader) <-> Worker"
    }

    print("\nRISULTATO TEST RETE:")
    print(json.dumps(results, indent=4))


if __name__ == "__main__":
    run_test()