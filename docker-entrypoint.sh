#!/bin/sh
set -e

# ==============================================================================
# IntentLead AI - Universal Docker Entrypoint
# ==============================================================================

echo "[entrypoint] Initializing IntentLead AI container..."

# Apply database migrations when launching API web service
if [ "$1" = "uvicorn" ] || [ "$APP_RUN_MIGRATIONS" = "true" ]; then
    echo "[entrypoint] Checking and applying database migrations via Alembic..."
    alembic upgrade head || {
        echo "[entrypoint] WARNING: Alembic migration encountered an issue or database already at head."
    }
fi

echo "[entrypoint] Executing: $@"
exec "$@"
