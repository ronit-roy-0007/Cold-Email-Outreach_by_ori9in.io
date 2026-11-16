# Database Architecture & Operations Guide

This document outlines the database design, migration lifecycle, connection pooling, indexing strategy, and disaster recovery procedures for **IntentLead AI**.

---

## 1. Engine & Environment Topology

IntentLead AI supports dual database configurations:

| Environment | Engine | Connection URL / Path | Purpose |
| :--- | :--- | :--- | :--- |
| **Development / Local** | SQLite 3 | `sqlite:///./intentlead.db` | Zero-dependency local developer bootstrap, Telegram polling, rapid offline testing. |
| **Staging & Production** | PostgreSQL 16+ | `postgresql+psycopg2://user:pass@host:5432/intentlead` | High-concurrency lead queuing, ACID compliance, enterprise connection pooling. |

### Connection Pooling Parameters (Production)
In `app/db.py`, the SQLAlchemy engine applies connection pool guards:
- `pool_pre_ping=True`: Tests connections before checking them out to prevent stale connection exceptions after idle disconnects.
- `pool_recycle=300`: Refreshes connections every 5 minutes to prevent TCP socket drops behind cloud load balancers or AWS RDS.
- `pool_size=10`: Sustains 10 persistent worker connections.
- `max_overflow=20`: Allows burst traffic up to 30 concurrent connections.

---

## 2. Schema Migrations (Alembic)

Database schema revisions are managed in `apps/intelligence-api/alembic/versions/`:

1. **`0001_initial.py`**: Base core schema (`campaigns`, `scrape_jobs`, `businesses`, `contacts`, `evidence`, `leads`, `dimension_scores`, `service_scores`, `message_drafts`, `audit_log`).
2. **`0002_approvals.py`**: Human-in-the-loop approval tracking table (`approvals`).
3. **`0003_outreach_compliance_and_mailboxes.py`**:
   - Mailbox rotation: `mailbox_accounts`, `daily_dispatch_quotas`.
   - Outreach & deliverability tracking: `outbound_messages`, `operator_profiles`.
   - Compliance: `suppression_list`.
   - High-yield rollover: `campaign_leftover_leads`.
   - Composite performance indexes across all core high-volume query paths.

### Applying Migrations
```bash
# In Linux / Docker / CI:
cd apps/intelligence-api
alembic upgrade head

# In Windows PowerShell:
cd apps/intelligence-api
$env:PYTHONPATH="."
alembic upgrade head
```

---

## 3. High-Performance Indexing Strategy

To guarantee sub-second API responses and rapid sub-campaign batch queries, the following composite and unique indexes are maintained:

| Table | Index Name | Columns | Optimizes |
| :--- | :--- | :--- | :--- |
| `leads` | `uq_leads_campaign_business` | `(campaign_id, business_id)` | Prevents duplicate leads within the same campaign. |
| `leads` | `ix_leads_campaign_status` | `(campaign_id, outreach_status)` | Instant filtering of pending/approved/sent leads. |
| `leads` | `ix_leads_score` | `(overall_score)` | Rapid descending score ordering for top-tier outreach. |
| `businesses` | `ix_businesses_website` | `(website)` | Deduplication on domain extraction. |
| `businesses` | `ix_businesses_place_id` | `(place_id)` | Google Maps place identity matching. |
| `businesses` | `ix_businesses_email` | `(email)` | Reverse domain and contact lookup. |
| `outbound_messages` | `ix_outbound_camp_status` | `(campaign_id, status)` | Analytics and campaign completion tracking. |
| `outbound_messages` | `ix_outbound_sender` | `(sender_email)` | Hourly and daily per-mailbox quota enforcement. |
| `daily_dispatch_quotas` | `ix_daily_quotas_sender_date` | `(sender_mailbox, dispatch_date)` | O(1) daily mailbox cap validation. |
| `campaign_leftover_leads` | `ix_leftovers_niche_loc_avail` | `(niche, location, is_consumed)` | Instant harvesting of surplus scored leads into sub-campaigns. |
| `suppression_list` | `ix_suppression_list_email` | `(email)` (Unique) | Pre-flight deliverability gate check. |

---

## 4. Backup & Disaster Recovery Procedures

### 4.1 Production PostgreSQL Backup (Automated)
Run a consistent snapshot using `pg_dump` with custom compressed format:

```bash
# Backup command
pg_dump -h $DB_HOST -U $DB_USER -d $DB_NAME -Fc -f "/backups/intentlead_$(date +%Y%m%d_%H%M%S).dump"

# Restore command
pg_restore -h $DB_HOST -U $DB_USER -d $DB_NAME --clean --if-exists "/backups/intentlead_20261116.dump"
```

### 4.2 SQLite Local Backup
When running locally, SQLite hot backups must use the VACUUM INTO or sqlite3 `.backup` utility to avoid file locks:

```bash
# Safe atomic backup while application is live:
sqlite3 intentlead.db ".backup intentlead_backup_$(date +%Y%m%d).db"
```

---

## 5. Data Integrity & Idempotency Rules

1. **Never delete existing user data**: Leads and businesses are soft-flagged or marked with status transitions (`draft` -> `approved` -> `sent` / `rejected`).
2. **Atomic Transactions**: Batch scoring, sub-campaign provisioning, and outbound status changes must always occur within a single database transaction context (`session.commit()` / `session.rollback()`).
3. **Suppression Pre-Flight Guarantee**: Before any message leaves the server, `SuppressionEntry` is checked via indexed SQL lookup. If present, dispatch is rejected with error `suppressed_recipient`.
