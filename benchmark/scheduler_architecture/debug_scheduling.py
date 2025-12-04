"""
Script di debug per capire dove si blocca il test
"""
import subprocess
import time
import sys

STACK_NAME = "cob-service"
TEST_SERVICE_NAME = "debug-test"
TEST_IMAGE = "cob-service-backend:latest"


def log(msg):
    print(f"[DEBUG] {msg}", file=sys.stderr)


# Step 1: Cleanup
log("Cleanup servizio esistente...")
subprocess.run(f"docker service rm {TEST_SERVICE_NAME}", shell=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2)

# Step 2: Verifica rete
log("Verifica rete overlay...")
cmd = f"docker network ls --filter name={STACK_NAME} --format '{{{{.Name}}}}'"
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
log(f"Reti trovate: {result.stdout.strip()}")

# Step 3: Crea servizio
log("Creazione servizio...")
create_cmd = f"""docker service create \
    --name {TEST_SERVICE_NAME} \
    --replicas 1 \
    --restart-condition none \
    {TEST_IMAGE}"""

log(f"Comando: {create_cmd}")
proc = subprocess.run(create_cmd, shell=True, capture_output=True, text=True)
log(f"Return code: {proc.returncode}")
log(f"Stdout: {proc.stdout}")
log(f"Stderr: {proc.stderr}")

if proc.returncode != 0:
    log("ERRORE nella creazione!")
    sys.exit(1)

# Step 4: Polling stato
log("Inizio polling stato...")
for i in range(30):
    # Metodo 1: service ps
    cmd1 = f"docker service ps {TEST_SERVICE_NAME} --format '{{{{.CurrentState}}}} {{{{.Error}}}}'"
    r1 = subprocess.run(cmd1, shell=True, capture_output=True, text=True)
    log(f"[{i}] service ps: '{r1.stdout.strip()}' (err: {r1.stderr.strip()})")

    # Metodo 2: service inspect
    cmd2 = f"docker service inspect {TEST_SERVICE_NAME} --format '{{{{.Spec.Mode.Replicated.Replicas}}}}'"
    r2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
    log(f"[{i}] replicas spec: {r2.stdout.strip()}")

    # Check se running
    if 'running' in r1.stdout.lower():
        log("SUCCESSO: container running!")
        break

    time.sleep(1)

# Step 5: Cleanup
log("Cleanup finale...")
subprocess.run(f"docker service rm {TEST_SERVICE_NAME}", shell=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

log("Fine debug")