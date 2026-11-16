#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

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
