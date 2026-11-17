# IntentLead AI — Backup, Restore & Disaster Recovery Guide

This guide details how to perform automated backups, manual snapshots, and full disaster recovery for IntentLead AI.

---

## 1. Quick Backup & Restore Scripts

IntentLead AI includes tested, cross-platform backup and restore scripts located in the `scripts/` directory.

### Linux / macOS
```bash
# Create a backup (detects Docker PostgreSQL or local SQLite automatically)
./scripts/backup_db.sh

# Restore from a backup file
./scripts/restore_db.sh ./backups/intentlead_pg_20261117_120000.sql.gz
```

### Windows (PowerShell)
```powershell
# Create a backup
.\scripts\backup_db.ps1

# Restore from a backup file
.\scripts\restore_db.ps1 -BackupFile .\backups\intentlead_pg_20261117_120000.sql
```

---

## 2. Docker PostgreSQL Backup Details

When running under Docker Compose, backups are performed via `pg_dump` executed inside the `intentlead-db` container.
- Clean SQL dump: Includes drop statements (`--clean --if-exists`) for atomic restores.
- Gzip compression: Reduces backup footprint by up to 90%.
- Zero downtime: PostgreSQL MVCC guarantees consistent snapshots without locking production tables.

### Manual One-Liner Backup:
```bash
docker exec intentlead-db pg_dump -U intentlead -d intentlead | gzip > ./backups/manual_backup_$(date +%Y%m%d).sql.gz
```

### Manual One-Liner Restore:
```bash
gunzip -c ./backups/manual_backup_20261117.sql.gz | docker exec -i intentlead-db psql -U intentlead -d intentlead
```

---

## 3. Recommended Automated Backup Schedule

On Linux / VPS deployments, add a daily cron job:
```bash
crontab -e
```
Add:
```text
# Daily backup at 03:00 UTC with 14-day retention cleanup
0 3 * * * cd /opt/IntentLead-AI && ./scripts/backup_db.sh && find ./backups -type f -mtime +14 -delete
```

---

## 4. Disaster Recovery Procedure

In the event of total server loss:
1. Provision a new VPS or local machine.
2. Clone the repository and copy your `.env` file.
3. Launch the database container:
   ```bash
   docker compose up -d db
   ```
4. Restore the latest backup:
   ```bash
   ./scripts/restore_db.sh ./backups/latest_backup.sql.gz
   ```
5. Launch the remaining services:
   ```bash
   docker compose up -d
   ```
6. Verify database health:
   ```bash
   curl http://localhost:8000/health/ready
   ```
