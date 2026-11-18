# Changelog

All notable changes to IntentLead AI are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.0] - 2026-11-18

### Added
- **Interactive Setup Wizard**: Guided CLI onboarding (`setup.py` & `scripts/setup.py`) for configuring database engine (PostgreSQL or SQLite), web operator account, Google Gemini AI API key, Telegram bot, and mailboxes. Automatically verifies schema and provisions operator account.
- **First-Run Detection Hooks**: Automated environment detection in `start.ps1` and `start.sh` that detects fresh repository clones and launches the onboarding wizard before service startup.
- **Legal Compliance Address Gate**: Introduced `BUSINESS_POSTAL_ADDRESS` configuration required by CAN-SPAM, GDPR, and CASL regulations. Live outreach fails closed if missing; dry-run simulations remain unrestricted.
- **Cascading Campaign Deletion**: Added modal-protected campaign deletion in UI and REST API (`DELETE /api/campaigns/{id}`) that cleanly deletes leads, evaluations, drafts, approvals, and unreferenced businesses.
- **Scrapling Engine Guide**: Authored comprehensive documentation in `docs/discovery-scrapling.md` explaining stealth discovery architecture, web crawling, rate limits, and responsible scraping practices.

### Changed
- **Dynamic Dashboard State Indicators**: Replaced static status labels across web dashboard templates with dynamic badges reflecting the active `OUTREACH_DRY_RUN` configuration.
- **Docker & Setup Database Alignment**: Standardized PostgreSQL as the default for Docker Compose deployments to ensure host tools and containers use identical database targets.
- **Repository Sanitization for Open-Source**: Replaced placeholder URLs (`your-org`) with repository references, removed personal Telegram IDs from test fixtures, and established clean generic defaults.

### Fixed
- **Real Estate Scoping Fix**: Scoped listing search audits and service fit rankings to real estate niches only, preventing unrelated campaigns (e.g. dental clinics) from displaying real estate portal audit evidence.
- **Overview Telemetry Metrics**: Scoped discovered target counts in the overview dashboard to active campaign businesses, eliminating orphaned records from deleted campaigns.
- **Strict MX Deliverability Gate**: Eliminated unsafe bare A-record and raw socket fallbacks in preflight email checks, enforcing standard DNS MX resolution.

---

## [0.2.1] - 2026-11-17

### Added
- **AI Draft Studio**: Operator-controlled individual lead draft studio embedded in the web dashboard (`/leads/{lead_id}`) with on-demand AI generation, independent subject & body editing, optimistic concurrency versioning, and PostgreSQL persistence.
- **Unified Gemini Personalization Engine**: Upgraded `gemini_personalizer.py` to produce structured JSON output (`{"subject": "...", "body": "..."}`) shared across Telegram bot review cards and web dashboard draft studio.
- **MessageDraft Subject & Version Schema**: Added Alembic migration `0005_add_draft_subject` adding `subject`, `version`, and `updated_at` columns to `message_drafts`.
- **FastAPI Endpoints**: Implemented `POST /api/leads/{lead_id}/ai-generate`, `POST /api/leads/{lead_id}/ai-generate/regenerate`, `PUT /api/leads/{lead_id}/ai-draft`, and `GET /api/leads/{lead_id}/ai-draft`.
- **Automated Verification Suite**: Added comprehensive test suite `apps/intelligence-api/tests/test_ai_draft_studio.py` testing mocked LLM generation, grounding, validation, optimistic concurrency conflict handling (409), rate limiting (429), and UI rendering.

### Changed
- **Lead Detail Web Interface**: Upgraded `lead_detail.html` with interactive AI Draft Studio card, real-time status badges, save spinners, and one-click copy utilities (`Copy Subject`, `Copy Email`, `Copy Full Email`).

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
