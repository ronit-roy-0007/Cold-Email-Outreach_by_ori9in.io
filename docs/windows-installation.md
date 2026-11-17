# IntentLead AI — Windows 10/11 Installation Guide

This guide details running IntentLead AI natively on Windows using Docker Desktop or local Python.

---

## Method A: Docker Desktop (Recommended)

### 1. Prerequisites
1. **Windows 10 (Build 19041+) or Windows 11**.
2. **WSL2 (Windows Subsystem for Linux)**:
   Open PowerShell as Administrator and run:
   ```powershell
   wsl --install
   ```
   Restart your computer if prompted.
3. **Docker Desktop for Windows**:
   - Download and install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
   - In Docker Desktop settings, ensure **"Use the WSL 2 based engine"** is enabled.

### 2. Setup & Execution
Open **PowerShell** or **Windows Terminal**:
```powershell
# 1. Clone the repository
git clone https://github.com/your-org/IntentLead-AI.git
cd IntentLead-AI

# 2. Copy the example configuration
Copy-Item .env.example .env

# 3. Edit .env with your favorite editor (e.g. Notepad or VS Code)
notepad .env

# 4. Start all containers
docker compose up -d --build
```

### 3. Verify
Open your browser and visit:
```text
http://localhost:8000
```

---

## Method B: Standalone Local Setup (Without Docker)

If you prefer running directly on Windows with Python and SQLite:

### 1. Prerequisites
- **Python 3.12+** installed from [python.org](https://www.python.org/downloads/) (Check *"Add python.exe to PATH"* during install).
- **Git for Windows**.

### 2. Virtual Environment & Dependencies
```powershell
cd IntentLead-AI

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

> [!NOTE]
> If PowerShell blocks script activation, run:
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
> ```

### 3. Database Initialization (SQLite)
```powershell
# Copy environment file
Copy-Item .env.example .env

# Set PYTHONPATH and apply migrations
$env:PYTHONPATH="apps/intelligence-api"
cd apps/intelligence-api
alembic upgrade head
cd ../..
```

### 4. Running Services Locally
Launch the API server:
```powershell
$env:PYTHONPATH="apps/intelligence-api"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

In a second PowerShell window, launch the Telegram Poller daemon:
```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH="apps/intelligence-api"
python scripts/telegram_poller.py
```

In a third PowerShell window, launch the Background Worker:
```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH="apps/intelligence-api"
python scripts/worker.py
```

---

## Windows Troubleshooting

- **Line Ending Issues (CRLF vs LF)**: If shell scripts fail inside containers with `\r: command not found`, run:
  ```powershell
  git config --global core.autocrlf input
  ```
- **Port 8000 in use**: If another process is using port 8000, specify an alternative port in `.env`:
  ```bash
  API_BIND_IP=127.0.0.1
  API_PORT=8085
  ```
