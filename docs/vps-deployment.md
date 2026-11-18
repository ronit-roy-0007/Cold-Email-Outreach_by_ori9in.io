# IntentLead AI — Production Ubuntu VPS Deployment Guide

This guide provides end-to-end instructions for deploying IntentLead AI into production on an Ubuntu 22.04 or 24.04 LTS VPS (Hetzner, DigitalOcean, Linode, AWS EC2, Vultr).

---

## Architecture Overview

```text
  Internet
     │
     ▼
[ Cloudflare / DNS ]
     │ (HTTPS: 443)
     ▼
[ Nginx Reverse Proxy + Let's Encrypt SSL ]
     │ (HTTP: 127.0.0.1:8000)
     ▼
┌────────────────────────────────────────────────────────┐
│ Docker Network: intentlead-network                     │
│                                                        │
│  [ FastAPI API ] ──► [ PostgreSQL 16 ] (No host ports) │
│        ▲        ──► [ Redis 7 ]       (No host ports) │
│        │                                               │
│  [ Telegram Poller ]                                   │
│  [ Background Worker ]                                 │
└────────────────────────────────────────────────────────┘
```

---

## 1. VPS Server Hardening

### Step A: Create Unprivileged Sudo User
```bash
adduser deployer
usermod -aG sudo deployer
rsync --archive --chown=deployer:deployer ~/.ssh /home/deployer
```

### Step B: Configure UFW Firewall
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp comment 'SSH'
sudo ufw allow 80/tcp comment 'HTTP'
sudo ufw allow 443/tcp comment 'HTTPS'
sudo ufw enable
```
> [!IMPORTANT]
> Never open ports `5432` (PostgreSQL) or `6379` (Redis) on your firewall. They must remain strictly bound to Docker internal network.

---

## 2. Install Docker Engine & Nginx

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg nginx certbot python3-certbot-nginx

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker deployer
newgrp docker
```

---

## 3. Clone Repository & Configure Environment

```bash
cd /opt
sudo git clone https://github.com/ronit-roy-0007/Cold-Email-Outreach_by_ori9in.io.git IntentLead-AI
sudo chown -R deployer:deployer IntentLead-AI
cd IntentLead-AI

cp .env.example .env
nano .env
```

### Production `.env` Requirements:
```bash
APP_ENV=production
LOG_LEVEL=INFO

# PostgreSQL Credentials
POSTGRES_USER=intentlead_user
POSTGRES_PASSWORD=your_ultra_secure_generated_database_password
POSTGRES_DB=intentlead_prod

# Production Domain & Security
CORS_ORIGINS=https://intentlead.yourdomain.com
FIELD_ENCRYPTION_KEY=your_generated_fernet_32_byte_key
UNSUBSCRIBE_SECRET=your_unique_32_char_unsubscribe_secret
UNSUBSCRIBE_BASE_URL=https://intentlead.yourdomain.com/unsubscribe

# Telegram Operator
TELEGRAM_BOT_TOKEN=your_live_bot_token
TELEGRAM_ALLOWED_USER_ID=your_numeric_operator_id

# AI & Outreach
USER_LLM_API_KEY=AIzaSy...
OUTREACH_DRY_RUN=true
```

---

## 4. Launch Production Containers

```bash
docker compose -f docker-compose.prod.yml up -d --build
```
Verify container statuses:
```bash
docker compose -f docker-compose.prod.yml ps
```

---

## 5. Configure Nginx Reverse Proxy with SSL

Create `/etc/nginx/sites-available/intentlead`:
```nginx
server {
    server_name intentlead.yourdomain.com;

    client_max_body_size 25M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 90;
    }
}
```

Enable site and acquire free SSL certificate:
```bash
sudo ln -s /etc/nginx/sites-available/intentlead /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Issue Let's Encrypt Certificate
sudo certbot --nginx -d intentlead.yourdomain.com
```

---

## 6. Automated Daily Backups

Set up an automated cron job to back up the database daily at 03:00 UTC:
```bash
crontab -e
```
Add:
```text
0 3 * * * cd /opt/IntentLead-AI && ./scripts/backup_db.sh >> /var/log/intentlead_backup.log 2>&1
```

---

## 7. Production Upgrades (Zero Data Loss)

```bash
cd /opt/IntentLead-AI
git pull origin main
docker compose -f docker-compose.prod.yml up -d --build
```
The entrypoint script automatically checks and executes new Alembic migrations on startup.
