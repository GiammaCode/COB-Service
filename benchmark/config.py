# Ora puntiamo alla porta 80 e usiamo il prefisso /api per i test del backend.yml
API_URL = "http://192.168.15.9:80/api"
STACK_NAME = "cob-service"
SERVICE_NAME = "backend.yml"
FULL_SERVICE_NAME = f"{STACK_NAME}_{SERVICE_NAME}"