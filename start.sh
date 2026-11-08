#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/apps/intelligence-api"

export PYTHONPATH="."

# Check database configuration
if [ -z "$DATABASE_URL" ]; then
  export DATABASE_URL="postgresql://intentlead:change-me@localhost:5432/intentlead"
fi

if [[ "$DATABASE_URL" == sqlite:* ]]; then
  if [ "$APP_ENV" != "development" ]; then
    echo "ERROR: SQLite is only permitted when APP_ENV=development. Current APP_ENV=$APP_ENV"
    exit 1
  fi
  echo "WARNING: Using SQLite in development mode. PostgreSQL is the production source of truth."
fi

echo "Applying Alembic database migrations..."
alembic upgrade head

echo "Starting IntentLead AI operator API on http://localhost:8000..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
