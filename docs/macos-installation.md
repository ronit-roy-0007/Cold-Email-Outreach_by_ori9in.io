# IntentLead AI — macOS Installation Guide (Apple Silicon & Intel)

This guide covers installing and running IntentLead AI on macOS (macOS 12+ Monterey, Ventura, Sonoma, Sequoia).

---

## Method A: Docker Desktop for Mac (Recommended)

### 1. Prerequisites
1. Install [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/).
   - Choose the installer matching your processor architecture:
     - **Mac with Apple Silicon** (M1, M2, M3, M4)
     - **Mac with Intel chip**
2. Ensure Docker Desktop is running and the whale icon is visible in your menu bar.

### 2. Clone and Setup
Open **Terminal**:
```bash
# Clone the repository
git clone https://github.com/your-org/IntentLead-AI.git
cd IntentLead-AI

# Copy environment configuration
cp .env.example .env

# Edit .env
nano .env

# Launch containers
docker compose up -d --build
```

### 3. Verify
Open Safari, Chrome, or your browser:
```text
http://localhost:8000
```

---

## Method B: Native macOS Setup with Homebrew

If you want to run without Docker:

### 1. Prerequisites
Install dependencies via Homebrew:
```bash
brew install python@3.12 postgresql@16 redis libpq
brew services start postgresql@16
brew services start redis
```

### 2. Virtual Environment & Requirements
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Apply Alembic Migrations
```bash
export PYTHONPATH=apps/intelligence-api
cd apps/intelligence-api
alembic upgrade head
cd ../..
```

### 4. Run Services
In Terminal 1:
```bash
source .venv/bin/activate
export PYTHONPATH=apps/intelligence-api
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

In Terminal 2 (Telegram Bot Poller):
```bash
source .venv/bin/activate
export PYTHONPATH=apps/intelligence-api
python scripts/telegram_poller.py
```

In Terminal 3 (Background Worker):
```bash
source .venv/bin/activate
export PYTHONPATH=apps/intelligence-api
python scripts/worker.py
```
