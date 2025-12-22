job "cob-service" {
  datacenters = ["dc1"]
  type        = "service"

  # --- GRUPPO DATABASE ---
  group "db-group" {
    count = 1

    network {
      mode = "bridge" # Ogni allocazione ha il suo IP isolato
      port "mongo" { to = 27017 }
    }

    # Definiamo il servizio per la discovery interna
    service {
      name = "mongodb"
      port = "mongo"
      provider = "nomad" # Nomad Native Service Discovery (disponibile da Nomad 1.3+)
    }

    task "mongodb" {
      driver = "docker"

      volume_mount {
        volume      = "nfs-storage" # Si riferisce all'host_volume nel client config
        destination = "/data/db"
        read_only   = false
      }

      config {
        image = "mongo:5.0"
        ports = ["mongo"]
      }

      resources {
        cpu    = 500
        memory = 512
      }
    }
  }

  # --- GRUPPO BACKEND ---
  group "backend-group" {
    count = 2 # Scaliamo a 2 repliche

    network {
      mode = "bridge"
      port "http" { to = 5000 }
    }

    service {
      name = "cob-backend"
      port = "http"
      provider = "nomad"
    }

    task "api" {
      driver = "docker"

      config {
        # Sostituisci con la tua immagine buildata e pushata al registry locale
        image = "192.168.15.9:5000/cob-backend:latest"
        ports = ["http"]
      }

      env {
        # Nomad service discovery magic: cerca il servizio "mongodb"
        MONGO_URI = "mongodb://{{ range nomadService \"mongodb\" }}{{ .Address }}:{{ .Port }}{{ end }}/cobdb"
      }

      # Necessario per renderizzare la stringa di connessione dinamica
      template {
        data = <<EOH
        MONGO_URI="mongodb://{{ range nomadService "mongodb" }}{{ .Address }}:{{ .Port }}{{ end }}/cobdb"
        EOH
        destination = "local/env"
        env         = true
      }

      resources {
        cpu    = 300
        memory = 256
      }
    }
  }

  # --- GRUPPO FRONTEND ---
  group "frontend-group" {
    count = 2

    network {
      mode = "bridge"
      port "http" {
        to = 80
        # Espone la porta 80 del container su una porta statica dell'host?
        # Meglio usare porta dinamica e un load balancer, ma per ora usiamo una porta statica per test
        static = 8080
      }
    }

    service {
      name = "cob-frontend"
      port = "http"
      provider = "nomad"
    }

    task "web" {
      driver = "docker"

      config {
        image = "192.168.15.9:5000/cob-frontend:latest"
        ports = ["http"]
      }

      env {
        # Il frontend deve chiamare il backend.
        # Nota: In un setup reale useresti un Ingress (es. Traefik o Nginx) davanti a tutto.
        # Qui puntiamo direttamente a una delle istanze backend o usiamo un sidecar proxy.
        REACT_APP_API_URL = "http://192.168.15.9:5000" # Esempio semplificato
      }

      resources {
        cpu    = 200
        memory = 128
      }
    }
  }
}