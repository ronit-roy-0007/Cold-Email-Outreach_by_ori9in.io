#!/bin/bash
set -e

# ==============================================================================
# IntentLead AI — Database Backup Script (Linux / macOS)
# ==============================================================================

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"

if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs -0) 2>/dev/null || true
fi

DB_USER="${POSTGRES_USER:-intentlead}"
DB_NAME="${POSTGRES_DB:-intentlead}"
CONTAINER_NAME="${DB_CONTAINER:-intentlead-db}"

# Detect if Docker Postgres container is running
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    BACKUP_FILE="${BACKUP_DIR}/intentlead_pg_${TIMESTAMP}.sql.gz"
    echo "[backup] Backing up PostgreSQL database '${DB_NAME}' from container '${CONTAINER_NAME}'..."
    docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists | gzip > "$BACKUP_FILE"
    echo "[backup] Backup successfully created at: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
elif [ -f "./intentlead.db" ]; then
    BACKUP_FILE="${BACKUP_DIR}/intentlead_sqlite_${TIMESTAMP}.db"
    echo "[backup] Backing up local SQLite database './intentlead.db'..."
    sqlite3 ./intentlead.db ".backup '$BACKUP_FILE'" 2>/dev/null || cp ./intentlead.db "$BACKUP_FILE"
    echo "[backup] Backup successfully created at: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
else
    echo "[backup] ERROR: Neither Docker container '${CONTAINER_NAME}' nor './intentlead.db' found."
    exit 1
fi
