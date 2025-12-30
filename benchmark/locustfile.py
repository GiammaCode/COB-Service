from locust import HttpUser, task, constant

class APIUser(HttpUser):
    # Pausa tra una richiesta e l'altra (simula un utente reale, o togli per stress puro)
    # Per stress test puro mettiamo wait_time = 0 o molto basso
    wait_time = constant(0)

    @task
    def get_assignments(self):
        self.client.get("/api/assignments")