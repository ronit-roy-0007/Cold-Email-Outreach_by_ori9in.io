# IntentLead AI — Linux (Debian / Ubuntu / RHEL) Installation Guide

This guide details installing and running IntentLead AI on modern Linux systems.

---

## Method A: Docker & Docker Compose (Recommended)

### 1. Prerequisites
Install Docker Engine and Docker Compose v2 using official Docker packages:
```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Ensure your user is in the `docker` group:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### 2. Clone and Launch
```bash
git clone https://github.com/ronit-roy-0007/Cold-Email-Outreach_by_ori9in.io.git
cd Cold-Email-Outreach_by_ori9in.io

cp .env.example .env
nano .env

# Build and start services in background
docker compose up -d --build
```

### 3. Verify
```bash
docker compose ps
curl http://localhost:8000/health/ready
```

---

## Method B: Standalone Python & Systemd Service

For bare-metal Linux servers:

### 1. Install Dependencies
```bash
sudo apt-get update
sudo apt-get install -y python3-dev python3-venv postgresql postgresql-contrib redis-server libpq-dev
```

### 2. Set Up Virtual Environment
```bash
cd IntentLead-AI
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Database & Migrations
```bash
# Create database user and database
sudo -u postgres psql -c "CREATE USER intentlead WITH PASSWORD 'your_secure_password';"
sudo -u postgres psql -c "CREATE DATABASE intentlead OWNER intentlead;"

# Run migrations
export PYTHONPATH=apps/intelligence-api
export DATABASE_URL="postgresql://intentlead:your_secure_password@localhost:5432/intentlead"
alembic -c apps/intelligence-api/alembic.ini upgrade head
```

### 4. Create Systemd Service for API
Create `/etc/systemd/system/intentlead-api.service`:
```ini
[Unit]
Description=IntentLead AI FastAPI Service
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/IntentLead-AI
EnvironmentFile=/opt/IntentLead-AI/.env
Environment="PYTHONPATH=apps/intelligence-api"
ExecStart=/opt/IntentLead-AI/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now intentlead-api
sudo systemctl status intentlead-api
```
