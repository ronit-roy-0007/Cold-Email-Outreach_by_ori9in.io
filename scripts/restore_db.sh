#!/bin/bash
set -e

# ==============================================================================
# IntentLead AI — Database Restore Script (Linux / macOS)
# ==============================================================================

if [ -z "$1" ]; then
    echo "Usage: $0 <path_to_backup_file>"
    echo "Example: $0 ./backups/intentlead_pg_20261117_120000.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file '$BACKUP_FILE' does not exist."
    exit 1
fi

if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs -0) 2>/dev/null || true
fi

DB_USER="${POSTGRES_USER:-intentlead}"
DB_NAME="${POSTGRES_DB:-intentlead}"
CONTAINER_NAME="${DB_CONTAINER:-intentlead-db}"

read -p "WARNING: Restoring will overwrite existing data in '${DB_NAME}'. Proceed? [y/N]: " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Restore cancelled."
    exit 0
fi

if [[ "$BACKUP_FILE" == *.sql.gz ]]; then
    echo "[restore] Restoring PostgreSQL from compressed dump '$BACKUP_FILE' into container '$CONTAINER_NAME'..."
    gunzip -c "$BACKUP_FILE" | docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME"
    echo "[restore] PostgreSQL restore completed successfully."
elif [[ "$BACKUP_FILE" == *.db ]] || [[ "$BACKUP_FILE" == *.sqlite* ]]; then
    echo "[restore] Restoring SQLite database from '$BACKUP_FILE' to './intentlead.db'..."
    cp "$BACKUP_FILE" ./intentlead.db
    echo "[restore] SQLite database restore completed successfully."
else
    echo "ERROR: Unrecognized backup file format. Expected .sql.gz or .db"
    exit 1
fi
