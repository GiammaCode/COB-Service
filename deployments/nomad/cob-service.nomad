job "cob-service" {
  datacenters = ["dc1"]
  type        = "service"

  # --- GRUPPO DATABASE ---
  group "db-group" {
    count = 1

    network {
      mode = "bridge"
      port "mongo" { to = 27017 }
    }

    # 1. AGGIUNGI QUESTO BLOCCO (Il ponte tra Host e Gruppo)
    volume "mongodb-data" {      # Nome interno per il gruppo
      type      = "host"
      source    = "nfs-storage"  # <-- Questo deve coincidere con la config del Client (host_volume)
      read_only = false
    }

    service {
      name = "mongodb"
      port = "mongo"
      provider = "nomad"
    }

    task "mongodb" {
      driver = "docker"

      # 2. AGGIORNA IL MOUNT (Usa il nome interno definito sopra)
      volume_mount {
        volume      = "mongodb-data" # <-- Qui usi "mongodb-data", NON "nfs-storage"
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

  group "proxy-group" {
    count = 1

    network {
      mode = "bridge"
      port "http" {
        static = 80
      }
    }

    service {
      name = "cob-lb"
      port = "http"
      provider = "nomad"
    }

    task "nginx" {
      driver = "docker"

      config {
        image = "nginx:alpine"
        ports = ["http"]
        # Montiamo il file generato in sola lettura
        volumes = [
          "local/nginx.conf:/etc/nginx/nginx.conf"
        ]
      }

      # Qui avviene la magia: trasformiamo il tuo file statico in dinamico
      template {
        change_mode   = "signal"
        change_signal = "SIGHUP"
        destination   = "local/nginx.conf"

        data = <<EOF
events {
    worker_connections 1024;
}

http {
    # --- ADATTAMENTO NOMAD: Upstream Dinamici ---

    upstream frontend {
        # Invece di "server frontend:3000", chiediamo a Nomad chi offre questo servizio
        {{ range nomadService "cob-frontend" }}
        server {{ .Address }}:{{ .Port }};
        {{ else }}server 127.0.0.1:65535; # Fallback per non far crashare Nginx se vuoto
        {{ end }}
    }

    upstream backend {
        # Invece di "server backend:5000"
        {{ range nomadService "cob-backend" }}
        server {{ .Address }}:{{ .Port }};
        {{ else }}server 127.0.0.1:65535;
        {{ end }}
    }

    server {
        listen 80;

        # --- LA TUA CONFIGURAZIONE ORIGINALE (Invariata) ---

        # 1. Rotta API
        location /api/ {
            proxy_pass http://backend/; # Nota: lo slash finale è importante, lo mantengo
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # 2. Rotta Default (Frontend)
        location / {
            proxy_pass http://frontend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

            # Supporto WebSocket
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }
    }
}
EOF
      }
    }
  }
}