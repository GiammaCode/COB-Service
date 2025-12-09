from locust import HttpUser, task, between

class APIUser(HttpUser):
    # Pausa tra una richiesta e l'altra (simula un utente reale, o togli per stress puro)
    # Per stress test puro mettiamo wait_time = 0 o molto basso
    wait_time = between(0.1, 0.5)

    @task
    def get_assignments(self):
        self.client.get("/api/assignments")