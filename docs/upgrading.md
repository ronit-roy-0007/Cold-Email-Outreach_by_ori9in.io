# IntentLead AI — Upgrading & Migration Guide

This guide covers updating your IntentLead AI installation to new releases without downtime or data loss.

---

## 1. Upgrading with Docker Compose

Upgrading is completely automated through the container entrypoint:

```bash
# 1. Pull the latest release code
git pull origin main

# 2. Rebuild and launch updated containers
docker compose up -d --build
```

### What Happens Automatically:
1. Docker builds the new application image.
2. The container entrypoint executes `alembic upgrade head`, applying any newly released schema migrations.
3. The old container is stopped and replaced with the updated version.
4. Persistent database volumes (`postgres_data`) and Redis caches are preserved.

---

## 2. Upgrading Standalone Python Installations

```bash
# 1. Pull latest code
git pull origin main

# 2. Activate virtual environment and update packages
source .venv/bin/activate   # (or .\.venv\Scripts\Activate.ps1 on Windows)
pip install --upgrade -r requirements.txt

# 3. Apply Alembic database migrations
export PYTHONPATH=apps/intelligence-api
cd apps/intelligence-api
alembic upgrade head
cd ../..

# 4. Restart services
sudo systemctl restart intentlead-api
sudo systemctl restart intentlead-worker
```

---

## 3. Database Migration Rollback Procedures

If an upgrade needs to be reverted:
```bash
# View current database revision
alembic current

# Rollback one migration revision
alembic downgrade -1

# Rollback to a specific target revision
alembic downgrade 0003_outreach_mailboxes
```

---

## 4. Best Practices for Production Updates

1. **Always take a backup before upgrading**:
   ```bash
   ./scripts/backup_db.sh
   ```
2. **Review the [CHANGELOG.md](../CHANGELOG.md)** for any breaking environment variable changes or deprecated parameters.
3. **Verify post-upgrade health**:
   ```bash
   curl http://localhost:8000/health/ready
   ```
