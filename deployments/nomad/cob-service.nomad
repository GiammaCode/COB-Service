job "cob-service" {
  datacenters = ["dc1"]
  type        = "service"

  # --- GRUPPO DATABASE ---
  group "db-group" {
    count = 1

    reschedule {
      delay          = "5s"
      delay_function = "constant"
      unlimited      = true
      interval       = "1m"
    }

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
    count = 2

    #Altrimenti nomad non riavvia i container
    reschedule {
      delay          = "5s"       # Aspetta solo 5s prima di tentare il riavvio
      delay_function = "constant" # Non aumentare il tempo a ogni tentativo (esponenziale)
      unlimited      = true       # Riprova all'infinito finché non trovi un nodo
      interval       = "1m"
    }

    update {
      # Aggiorna 1 container alla volta (fondamentale per non andare offline)
      max_parallel      = 1
      # Aspetta che il nuovo task sia "sano" prima di procedere
      health_check      = "checks"
      # Una volta che il task risponde, aspetta altri 10 secondi per sicurezza
      # prima di spegnere la vecchia replica.
      min_healthy_time  = "10s"
      # Tempo massimo per considerare l'aggiornamento fallito
      healthy_deadline  = "5m"
      progress_deadline = "10m"
      # Se l'aggiornamento fallisce, torna automaticamente alla versione precedente
      auto_revert       = true
      # Canary a 0 significa "fai l'update diretto", senza fase di test manuale
      canary            = 0
    }

    network {
      mode = "bridge"
      port "http" {
        to = 5000
      }
    }

    service {
      name = "cob-backend"
      port = "http"
      provider = "nomad"
    }

    task "api" {
      driver = "docker"

      config {
        image = "192.168.15.9:5000/cob-backend:latest"
        ports = ["http"]
      }

      env {
        MONGO_URI = "mongodb://{{ range nomadService \"mongodb\" }}{{ .Address }}:{{ .Port }}{{ end }}/cobdb"
        FLASK_RUN_HOST = "0.0.0.0"
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

    reschedule {
      delay          = "5s"
      delay_function = "constant"
      unlimited      = true
      interval       = "1m"
    }

    network {
      mode = "bridge"
      port "http" {
        to = 3000
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
        REACT_APP_API_URL = "/api"
        HOST = "0.0.0.0"
        DANGEROUSLY_DISABLE_HOST_CHECK = "true"
      }

      resources {
        cpu    = 400
        memory = 1024
      }
    }
  }

  group "proxy-group" {
    count = 1

    reschedule {
      delay          = "5s"
      delay_function = "constant"
      unlimited      = true
      interval       = "1m"
    }

    network {
      mode = "bridge"
      port "http" {
        static = 80
        to = 80
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
        volumes = [
          "local/nginx.conf:/etc/nginx/nginx.conf"
        ]
      }

      # Qui avviene la magia: trasformiamo il tuo file statico in dinamico
      template {
        change_mode   = "restart"
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