# IntentLead AI — Universal Installation & Quickstart Guide

This guide covers getting IntentLead AI up and running locally or on a server using Docker Compose or standalone Python.

---

## 1. Prerequisites

- **Docker Desktop** (Windows / macOS) or **Docker Engine 24+ with Compose v2** (Linux).
- **Git** (for cloning the repository).
- *(Optional for bare-metal setup)*: **Python 3.12+**, **PostgreSQL 16**, **Redis 7**.

---

## 2. Quickstart with Docker Compose (Recommended)

### Step 1: Clone Repository
```bash
git clone https://github.com/your-org/IntentLead-AI.git
cd IntentLead-AI
```

### Step 2: Initialize Environment File
- **Linux / macOS**:
  ```bash
  cp .env.example .env
  ```
- **Windows (PowerShell)**:
  ```powershell
  Copy-Item .env.example .env
  ```

### Step 3: Configure Credentials (Minimal Setup)
Open `.env` in your text editor and set:
```bash
# Telegram Operator Bot
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_from_botfather
TELEGRAM_ALLOWED_USER_ID=your_numeric_telegram_user_id

# AI Auditing & Personalization
USER_LLM_API_KEY=your_gemini_api_key_from_google_ai_studio

# Secret Keys
FIELD_ENCRYPTION_KEY=replace_with_32_char_secret_passphrase
UNSUBSCRIBE_SECRET=replace_with_32_char_secret_token
```

### Step 4: Build and Launch Containers
```bash
docker compose up -d --build
```

Docker Compose will automatically:
1. Initialize the PostgreSQL 16 container (`intentlead-db`).
2. Initialize the Redis 7 container (`intentlead-redis`).
3. Build the application image, apply Alembic database migrations, and launch FastAPI on port `8000` (`intentlead-api`).
4. Start the autonomous Telegram bot poller (`intentlead-telegram-poller`).
5. Start the background follow-up worker (`intentlead-worker`).

---

## 3. Verifying Installation

Open your browser and navigate to:
```text
http://localhost:8000
```
You should see the IntentLead AI Dashboard.

### Health Check Endpoint
```bash
curl http://localhost:8000/health/ready
```
Expected response:
```json
{
  "status": "ready",
  "database": "connected",
  "environment": "development",
  "provider": "scrapling",
  "outreach_mode": "dry-run"
}
```

---

## 4. Managing Containers

| Action | Command |
|---|---|
| View container status | `docker compose ps` |
| View live logs | `docker compose logs -f` |
| View API logs only | `docker compose logs -f api` |
| View Telegram poller logs | `docker compose logs -f telegram-poller` |
| Restart services | `docker compose restart` |
| Stop all containers | `docker compose down` |
| Stop and remove data volumes | `docker compose down -v` *(Caution: wipes database)* |

---

## 5. Platform-Specific Guides

For deep, OS-tailored instructions and troubleshooting, see:
- [Windows Installation Guide](windows-installation.md)
- [Linux Installation Guide](linux-installation.md)
- [macOS Installation Guide](macos-installation.md)
- [Ubuntu VPS Production Deployment Guide](vps-deployment.md)
