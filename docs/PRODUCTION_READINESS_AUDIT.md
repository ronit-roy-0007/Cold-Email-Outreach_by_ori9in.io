# IntentLead AI — Production Readiness & Architecture Audit

**Target Repository:** `Cold-Email-Outreach_by_ori9in.io`  
**Date:** 2026-11-16  
**Auditor:** Antigravity Autonomous Engineering Agent  
**Scope:** Complete Codebase, Security, Reliability, Compliance, Testing & Observability Inspection

---

## 1. Executive Summary

IntentLead AI is an evidence-led B2B client acquisition platform combining stealth Google Maps scraping, automated website intelligence extraction, deterministic qualification scoring, plain-text cold email generation, and multi-mailbox Gmail pool rotation—all orchestrated via Telegram.

While the core functionality (stealth scraping, scoring, delivery gate, sub-campaign loops, and Telegram wizard) is highly innovative and operational, this audit identifies critical gaps required for enterprise production readiness:
1. **API Security:** REST endpoints (`/api/campaigns`, `/api/leads`) lack authentication/API key enforcement, CORS restrictions, rate limiting, and structured request validation models.
2. **Database Resilience:** Database migrations are out of sync with `app/models.py` (missing migration for `OperatorProfile`, `OutboundMessage`, `SuppressionEntry`, `DailyDispatchQuota`, `MailboxAccount`, `CampaignLeftoverLead`), and high-traffic query columns lack composite indexes.
3. **Observability:** Healthcheck endpoints are rudimentary (`/health` returns static `{"status": "ok"}` without testing database connectivity), structured JSON logging is absent, and background worker monitoring is limited to stdout prints.
4. **CI/CD:** No automated GitHub Actions workflow exists for linting, security scanning, dependency vulnerability checking, and regression testing.
5. **Container Hardening:** `Dockerfile` runs as the root user and lacks built-in healthchecks and headless browser dependencies for containerized environments.

---

## 2. Component & Architecture Inventory

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            IntentLead AI Engine                             │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼                             ▼                             ▼
┌─────────────────┐           ┌─────────────────┐           ┌─────────────────┐
│ Telegram Poller │           │   FastAPI API   │           │ n8n Automation  │
│ (Command Center)│           │ (Intelligence)  │           │   (Workflows)   │
└────────┬────────┘           └────────┬────────┘           └────────┬────────┘
         │                             │                             │
         └─────────────────────────────┼─────────────────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │         Pipeline Service          │
                     └─────────────────┬─────────────────┘
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼                             ▼                             ▼
┌─────────────────┐           ┌─────────────────┐           ┌─────────────────┐
│ Stealth Scraper │           │ Website Auditor │           │ Intent Scorer   │
│   (Scrapling)   │           │ (Contacts/Tech) │           │  (7 Dimensions) │
└─────────────────┘           └─────────────────┘           └─────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │   Deliverability Pre-Flight Gate  │
                     │  (DNS MX / RFC 7505 Null MX Check)│
                     └─────────────────┬─────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │     Multi-Mailbox Dispatcher      │
                     │  (Round-Robin + Survivor Pacing)  │
                     └─────────────────┬─────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │        PostgreSQL / SQLite        │
                     │   (SQLAlchemy ORM + Alembic Head) │
                     └───────────────────────────────────┘
```

### Source Code Module Directory

| Directory / File | Role | State | Audit Finding |
| :--- | :--- | :--- | :--- |
| `app/main.py` | FastAPI application factory | Functional | Needs CORS, rate-limiting, error handler, structured healthchecks. |
| `app/config.py` | Pydantic BaseSettings | Operational | Needs API key setting, rate limit settings, CORS origins setting. |
| `app/db.py` | Engine & session maker | Operational | Needs pool pre-ping, connection recycle, and timeout hardening. |
| `app/models.py` | SQLAlchemy declarative ORM | Rich Schema | Needs explicit composite indexes on search and lookup fields. |
| `app/api/campaigns.py` | Campaign management endpoints | Functional | Accepts untyped dict payloads; needs Pydantic schema validation & auth. |
| `app/api/leads.py` | Lead & prospect query endpoints | Functional | Lacks auth token protection; needs pagination boundary validation. |
| `app/api/orchestrator.py` | Webhooks and approval endpoints | Functional | Telegram webhook accepts updates; needs optional secret token validation. |
| `app/api/outreach.py` | Unsubscribe & outreach endpoints | Functional | HTML unsubscribe page working; needs complaint/feedback webhook stub. |
| `app/services/ssrf.py` | Website URL safety validator | Hardened | Blocks loopback, private RFC 1918/4193 IPs, userinfo, and internal clouds. |
| `app/services/email_gate.py` | Pre-flight deliverability gate | Hardened | Syntax validation, suppression list check, DNS MX + RFC 7505 Null MX. |
| `app/services/email_dispatcher.py`| Multi-mailbox dispatch engine | Hardened | Round-robin rotation, survivor pacing guard (30–40s cooldown), quota check. |
| `app/services/email_compliance.py`| CAN-SPAM formatting & tokens | Hardened | HMAC-SHA256 unsubscribe tokens; casual outreach footer suppression. |
| `app/services/mailbox_pool.py`| Pool loader & dynamic adding | Functional | Loads `mailboxes.json` and DB accounts; SMTP connection validation. |
| `app/services/sub_campaign_service.py`| Concentric geo & loops | Hardened | Triple-layer deduplication, rollover leads, 3 distinct deliverable CSVs. |
| `app/services/telegram_bot.py` | Telegram bot command engine | Hardened | Wizard, commands, `/provider` live switcher, approval workflows. |
| `scripts/telegram_poller.py` | Polling daemon for Telegram | Operational | Auto-syncs `setMyCommands`, handles connection drop recovery. |

---

## 3. Security Posture Audit

### 3.1 Authentication & Authorization
* **Current Status:** Telegram webhook enforces `TELEGRAM_ALLOWED_USER_ID` to block unauthorized chat IDs. However, the REST endpoints under `/api/campaigns`, `/api/leads`, and `/api/orchestrator/approvals` accept requests without an API key or Bearer token.
* **Remediation:** Introduce an optional `API_KEY` header security dependency (`X-API-Key`) so production deployments can gate administrative REST calls.

### 3.2 Input Validation
* **Current Status:** Campaign creation in `app/api/campaigns.py` receives a raw `dict[str, Any]` payload, relying on downstream dictionary lookups with fallback defaults.
* **Remediation:** Introduce typed Pydantic models (`CampaignCreateRequest`, `LeadFilterRequest`, `ApprovalRequest`) with field boundaries, string sanitization, and min/max integer constraints.

### 3.3 Rate Limiting & Denial of Service Protection
* **Current Status:** No global or IP-based rate limiting on the FastAPI server.
* **Remediation:** Implement in-memory token-bucket / sliding window rate limiting middleware to prevent brute-force attacks on webhook and API routes.

### 3.4 SSRF Protection
* **Current Status:** `app/services/ssrf.py` validates URLs before website scraping. It checks against `BLOCKED_HOSTNAMES` (`localhost`, `metadata.google.internal`) and resolves IPs to ensure they do not fall within private IPv4/IPv6 ranges (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1`).
* **Evaluation:** High quality. Verified working with unit tests.

### 3.5 Secret Protection & Leak Prevention
* **Current Status:** `.gitignore` excludes `.env`, `mailboxes.json`, `*.db`, `*.sqlite`. Scratch files with test API keys have been purged. Clean `.env.example` and `mailboxes.example.json` templates exist.
* **Evaluation:** Staged commits are clean.

---

## 4. Email Compliance & Deliverability Audit

### 4.1 CAN-SPAM & International Safeguards
* **Unsubscribe Mechanism:** Cryptographic HMAC-SHA256 tokens (`/api/outreach/unsubscribe?email=...&token=...`) record unsubscribes in `suppression_list` permanently.
* **Suppression Enforcement:** The pre-flight gate in `app/services/email_gate.py` queries `SuppressionEntry` before any message can be dispatched.
* **Sender Quotas & Limits:** `DailyDispatchQuota` enforces a strict 40–50 email/day cap per mailbox.
* **Pacing Guards:** 5–8 second human jitter delay normally; automatically ramps to 30–40 second cooldown when fewer than 3 mailboxes remain active in the pool.
* **Pre-Flight Deliverability Gate:** Resolves DNS MX records and detects **RFC 7505 Null MX** records (`.` target), preventing bounces before sending.

---

## 5. Database Reliability Audit

### 5.1 Alembic Migration Gap
* `alembic/versions/` only contains `0001_initial.py` and `0002_approvals.py`.
* Models added later (`OperatorProfile`, `OutboundMessage`, `SuppressionEntry`, `DailyDispatchQuota`, `MailboxAccount`, `CampaignLeftoverLead`) currently depend on `Base.metadata.create_all()`.
* **Remediation:** Generate migration `0003_outreach_compliance_and_mailboxes.py` to ensure PostgreSQL production databases can be initialized and upgraded reproducibly via `alembic upgrade head`.

### 5.2 Indexing Strategy
* Frequent queries in `dispatch_subcampaign_batch`, `record_campaign_leftovers`, and `is_business_duplicate` perform lookups on:
  - `leads(campaign_id, outreach_status)`
  - `leads(overall_score)`
  - `businesses(place_id)`
  - `businesses(website)`
  - `outbound_messages(campaign_id, status)`
  - `daily_dispatch_quotas(sender_mailbox, dispatch_date)`
* **Remediation:** Add composite indexes in `models.py` and migration 0003.

---

## 6. Automated Test Suite Audit

Existing test coverage:
* `tests/test_scoring.py`: 12 tests passing (Scoring criteria, dimensions, thresholds).
* `tests/test_drafts.py`: 8 tests passing (Hook subject lines, gap intros, service displays).
* `tests/test_email_dispatcher.py`: 10 tests passing (Pre-flight MX, Null MX, daily quota, CAN-SPAM, HMAC unsubscribe).
* `tests/test_mailbox_pool.py`: 8 tests passing (Pool loading, rotation, dynamic adding/removal).
* `tests/test_social_links.py`: 6 tests passing (Domain sanitization, platform matching).
* `tests/test_sub_campaigns.py`: 11 tests passing (Triple deduplication, radius expansion, auto-mode, rollover, CSV partitioning).
* `tests/test_telegram.py`: 14 tests passing (Interactive 6-step wizard, `/provider`, commands, inline callbacks).
* **Total existing tests:** 69 passing unit and integration tests.
* **Gaps to address in Phase 6:** Comprehensive API integration tests for auth enforcement, rate limiting, and structured health check endpoints.

---

## 7. Action Plan Summary

| Phase | Core Objective | Key Deliverables |
| :--- | :--- | :--- |
| **Phase 2 — Docs** | Fix inconsistent claims and align commands | Update `README.md`, `architecture.md`, Windows/Linux deployment steps. |
| **Phase 3 — Security** | Restrict API, add rate limiting & CORS | Add CORS middleware, rate-limit middleware, API Key auth dependency, typed schemas. |
| **Phase 4 — Compliance** | Formalize bounce/complaint handling | Add complaint tracking webhook endpoint, enforce suppression auditing. |
| **Phase 5 — Database** | Sync Alembic migrations & add indexes | Add migration 0003, add composite indexes to `models.py`, harden DB connection pool. |
| **Phase 6 — Testing** | Expand automated test suite | Add security, rate-limiting, and healthcheck test coverage; maintain 100% pass rate. |
| **Phase 7 — CI/CD** | Automated GitHub Actions workflow | Create `.github/workflows/ci.yml` running linting, formatting, security, and pytest. |
| **Phase 8 — Observability** | Enhanced healthcheck & logging | Add `/health/ready` with DB ping, JSON request logging middleware, daemon metrics. |
| **Phase 9 — DevEx** | Container & setup polish | Add non-root user and healthcheck to `Dockerfile`, polish `.env.example`. |
| **Phase 10 — Presentation**| GitHub Presentation & Polish | Polish README with badge matrix, architecture diagram, and contribution guidelines. |
| **Phase 11 — Validation**| Complete end-to-end verification | Run full test suite, lint check, migration check, ensure zero regressions. |
| **Phase 12 — Git Commit** | Final local commit | Clean `git status`, verify no secret leaks, commit with required commit message. |
