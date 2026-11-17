# Changelog

All notable changes to IntentLead AI are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] - 2026-11-17

### Added
- **Universal Multi-Stage Docker Architecture**: Production (`docker-compose.prod.yml`) and development (`docker-compose.yml`) Compose configurations featuring unprivileged user `appuser` (UID 10001), healthchecks for all services, and internal network isolation for PostgreSQL and Redis.
- **Automated Container Migration Entrypoint**: Created `docker-entrypoint.sh` applying Alembic migrations (`alembic upgrade head`) before API startup with clean signal forwarding.
- **Standalone Background Worker Daemon**: Implemented `scripts/worker.py` for continuous, concurrency-safe processing of scheduled multi-touch follow-ups, reply handling, and suppression checks.
- **Cross-Platform Database Backup & Restore**: Added `scripts/backup_db.sh`, `scripts/backup_db.ps1`, `scripts/restore_db.sh`, and `scripts/restore_db.ps1` supporting both PostgreSQL (via `pg_dump`/`pg_restore`) and SQLite.
- **Comprehensive Documentation Suite**: Authored 15 detailed guides in `docs/` covering architecture, OS-specific installation (Windows, Linux, macOS, Ubuntu VPS), configuration, DNS email authentication (SPF/DKIM/DMARC), Telegram operator setup, AI personalization, security, privacy, and backup recovery.
- **Open-Source Governance & CI/CD**: Added Apache License 2.0 (`LICENSE`), third-party dependency notice (`NOTICE`), `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, GitHub Actions CI workflow, and issue/PR templates.
- **Automated Secret Scanning**: Added `scripts/scan_tracked_secrets.py` and `scripts/scan_history_secrets.py` to prevent accidental credential leakage in Git commits and pull requests.

### Changed
- **Default Branding & Credentials Portability**: Replaced developer-specific personal defaults with generic, user-configurable branding and environment variables (`AGENCY_NAME`, `AGENCY_SENDER_NAME`, `SENDER_EMAIL`).
- **Enforced Outbound Dry-Run by Default**: Ensured `OUTREACH_DRY_RUN=true` is strictly enforced in all example environment templates to prevent accidental cold email dispatch on fresh installations.
- **Enhanced Production Security Gates**: Startup validation strictly verifies that `FIELD_ENCRYPTION_KEY`, non-wildcard `CORS_ORIGINS`, and unique `UNSUBSCRIBE_SECRET` are configured when `APP_ENV=production`.

### Fixed
- **Credential Redaction in Logs**: Silenced verbose HTTP client logging (`httpx`/`httpcore`) and masked bot tokens in Telegram poller exceptions.
- **SQLite vs UTC Timezone Normalization**: Standardized naive vs aware datetime handling across automated testing runners.

---

## [0.1.0] - 2026-11-08

### Added
- Initial B2B lead discovery engine via Google Maps and Scrapling.
- Evidence-based scoring engine and heuristic website gap detection.
- Google Gemini-powered hyper-personalized pitch generation.
- Human-in-the-loop Gate 0 lead approval workflow.
- Multi-mailbox SMTP pool rotation with pacing and daily limits.
- Telegram operator bot with command interface (`/findleads`, `/status`, `/export_csv`).
- Unified Inbox and conversation thread matching.
