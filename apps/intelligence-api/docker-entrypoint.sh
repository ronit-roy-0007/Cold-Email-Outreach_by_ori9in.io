#!/bin/sh
set -e

# ==============================================================================
# IntentLead AI - Docker Container Entrypoint
# ==============================================================================

echo "[entrypoint] Initializing IntentLead AI service..."

# Run database migrations if command starts with uvicorn or web server
if [ "$1" = "uvicorn" ] || [ "$1" = "gunicorn" ] || [ "$APP_RUN_MIGRATIONS" = "true" ]; then
    echo "[entrypoint] Checking and applying database migrations via Alembic..."
    alembic upgrade head || {
        echo "[entrypoint] WARNING: Alembic migration encountered an error or already up-to-date."
    }
fi

echo "[entrypoint] Executing command: $@"
exec "$@"
