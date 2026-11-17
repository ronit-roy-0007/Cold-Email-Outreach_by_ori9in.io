#!/bin/sh
set -e

# ==============================================================================
# IntentLead AI - Universal Docker Entrypoint
# ==============================================================================

echo "[entrypoint] Initializing IntentLead AI container..."

# Apply database migrations when launching API web service
if [ "$1" = "uvicorn" ] || [ "$1" = "gunicorn" ] || [ "$APP_RUN_MIGRATIONS" = "true" ]; then
    echo "[entrypoint] Waiting for database readiness..."
    python -c "
import time, sys
from app.config import get_settings, resolve_database_url
from sqlalchemy import create_engine, text
settings = get_settings()
url = resolve_database_url(settings)
engine = create_engine(url, pool_pre_ping=True)
for i in range(30):
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print('[entrypoint] Database connection verified.')
        sys.exit(0)
    except Exception as e:
        print(f'[entrypoint] Waiting for database ({i+1}/30)...')
        time.sleep(1)
print('[entrypoint] FATAL: Database connection timed out after 30 seconds.', file=sys.stderr)
sys.exit(1)
" || exit 1

    echo "[entrypoint] Checking and applying database migrations via Alembic..."
    alembic upgrade head || {
        echo "[entrypoint] FATAL: Database migration failed. Failing closed to prevent data corruption." >&2
        exit 1
    }
fi

echo "[entrypoint] Executing: $@"
exec "$@"
