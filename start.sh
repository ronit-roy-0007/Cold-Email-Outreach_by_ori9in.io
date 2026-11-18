#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Check if first-time setup is needed
if [ ! -f "$ROOT_DIR/.env" ] && [ ! -f "$ROOT_DIR/apps/intelligence-api/.env" ]; then
  echo "[!] No configuration (.env) detected. Launching setup wizard..."
  python3 "$ROOT_DIR/scripts/setup.py"
  if [ ! -f "$ROOT_DIR/.env" ] && [ ! -f "$ROOT_DIR/apps/intelligence-api/.env" ]; then
    echo "Setup was not completed. Exiting."
    exit 1
  fi
fi

if [ "$1" == "--poller" ]; then
  cd "$ROOT_DIR"
  export PYTHONPATH="apps/intelligence-api"
  echo "Starting IntentLead AI Telegram Poller Daemon..."
  exec python3 -u scripts/telegram_poller.py
fi

cd "$ROOT_DIR/apps/intelligence-api"
export PYTHONPATH="."

# Check database configuration
if [ -z "$DATABASE_URL" ]; then
  if [ -f "$ROOT_DIR/.env" ]; then
    # loaded by dotenv
    :
  else
    export DATABASE_URL="sqlite:///./intentlead.db"
  fi
fi

echo "Applying Alembic database migrations..."
alembic upgrade head

if [ "$1" == "--both" ]; then
  echo "Launching Telegram Poller in background..."
  (cd "$ROOT_DIR" && PYTHONPATH="apps/intelligence-api" python3 -u scripts/telegram_poller.py) &
fi

echo "Starting IntentLead AI operator API on http://localhost:8000..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
