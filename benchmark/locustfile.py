from locust import HttpUser, task, constant

class APIUser(HttpUser):
    # Pause between requests (simulates a real user, or remove for pure stress)
    # For pure stress
    wait_time = constant(0)

    @task
    def get_assignments(self):
        self.client.get("/api/assignments")