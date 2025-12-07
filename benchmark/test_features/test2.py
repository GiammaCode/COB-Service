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
        # Nota: iperf3 con -J produce JSON
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

        if not output.strip():
            print("ATTENZIONE: Output vuoto. Il container potrebbe essere crashato o pending.")
        else:
            # FIX ROBUSTEZZA:
            # I log potrebbero contenere output di riavvii precedenti (es. {...} {...}).
            # Cerchiamo l'ULTIMA occorrenza di '{"start":' che indica l'inizio dell'ultimo report JSON.
            json_start_index = output.rfind('{"start":')

            if json_start_index != -1:
                # Prendiamo tutto dall'ultimo '{"start":' fino alla fine
                clean_json_str = output[json_start_index:]

                try:
                    iperf_data = json.loads(clean_json_str)

                    if "error" in iperf_data:
                        print(f"ERRORE IPERF RILEVATO: {iperf_data['error']}")
                        gbps = -1
                    else:
                        bits_per_second = iperf_data.get('end', {}).get('sum_received', {}).get('bits_per_second', 0)
                        gbps = bits_per_second / 1e9

                except json.JSONDecodeError as e:
                    print(f"ERRORE PARSING JSON: {e}")
                    print("Suggerimento: L'output potrebbe essere tronco.")
                    gbps = 0
            else:
                print("IMPOSSIBILE TROVARE UN JSON 'START' VALIDO NEI LOG.")
                # Stampa solo l'inizio e la fine per debug senza intasare tutto
                print(f"Output Head:\n{output[:200]}...")
                print(f"Output Tail:\n...{output[-200:]}")
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