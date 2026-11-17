# IntentLead AI — Open-Source Baseline Assessment Report

**Report Date:** 2026-11-17  
**Git Baseline Commit:** `26098c2 — merge: feat(ai-draft-studio) into main`  
**Repository:** `Cold-Email-Outreach_by_ori9in.io`  
**Lead Auditor & Architect:** Principal Software Architect, Application Security Engineer & Open-Source Release Manager  

---

## 1. Executive Summary

IntentLead AI is an independent, self-hostable B2B lead intelligence and outreach platform designed for marketing agencies, freelancers, and B2B growth teams. It discovers leads via search/maps scraping, conducts rigorous automated website audits and evidence qualification, drafts personalized outreach proposals with Google Gemini, queues messages for strict human operator approval, manages multi-mailbox rotation and follow-up cadence, and processes inbound prospect replies.

This baseline assessment documents the architectural, operational, and security posture of the repository at commit `26098c2` prior to the comprehensive open-source and security remediation.

---

## 2. Architecture & Runtime Topology

The application operates as an event-driven, decoupled system built primarily in Python (FastAPI):

```
+-----------------------------------------------------------------------------------+
|                                 OPERATOR SURFACES                                 |
|  +----------------------------------+       +----------------------------------+  |
|  |       Telegram Bot Poller        |       |        Web Dashboard (HTML)      |  |
|  |     (scripts/telegram_poller)    |       |         (FastAPI Jinja2)         |  |
|  +-----------------+----------------+       +-----------------+----------------+  |
+--------------------|------------------------------------------|-------------------+
                     |                                          |
                     v                                          v
+--------------------+------------------------------------------+-------------------+
|                        FASTAPI CORE APPLICATION (PORT 8000)                       |
|                                                                                   |
|  [REST API: /api/leads, /campaigns, /mailboxes, /webhooks/telegram, /inbox]       |
|  [AI Draft Studio: /api/leads/{id}/ai-draft, /ai-generate, /preview-lead]         |
|  [Email Gate & Dispatcher: Strict approval, suppression, dry-run enforcement]     |
|  [Scoring Engine: Evidence-based qualification (Score 0-100, threshold default)]  |
+--------------------+---------------------+--------------------+-------------------+
                     |                     |                    |
                     v                     v                    v
         +-----------+---------+  +--------+-------+  +---------+-----------+
         |     PostgreSQL      |  |     Redis      |  |  External Services  |
         | (Production RDBMS)  |  | (Cache/Queue)  |  | - Google Gemini 1.5 |
         | SQLite (Dev only)   |  |                |  | - Scrapers/Maps API |
         +---------------------+  +----------------+  | - SMTP / Resend     |
                                                      +---------------------+
```

### Directory Structure:
- `apps/intelligence-api/app/`: Core application package:
  - `main.py`: FastAPI app initialization, middleware, lifecycle events, and route mounting.
  - `config.py`: Pydantic settings loading environment variables with defaults.
  - `db.py`: SQLAlchemy database engine and session management.
  - `models.py`: Declarative ORM models (`Lead`, `Campaign`, `Business`, `Evidence`, `MailboxAccount`, `MessageDraft`, `Conversation`, `FollowUpExecution`, `OperatorProfile`, `AuditLog`, `SuppressionEntry`, etc.).
  - `security.py`: API key verification, proxy header resolution, origin checks.
  - `api/`: REST API routers (`leads.py`, `campaigns.py`, `mailboxes.py`, `analytics.py`, `inbox.py`, `ai_draft_studio.py`).
  - `web/`: Server-rendered HTML dashboard routes (`routes.py`) and Jinja2 templates (`app/web/templates/`).
  - `services/`: Business logic engines (`pipeline.py`, `scoring.py`, `gemini_personalizer.py`, `email_gate.py`, `email_dispatcher.py`, `followup_engine.py`, `telegram_bot.py`, `scraper_client.py`, `mailbox_manager.py`, `audit_service.py`).
  - `alembic/`: Alembic migrations directory.
- `scripts/`: Operational scripts (`telegram_poller.py`, `run_campaign.py`, `bootstrap_operator.py`, etc.).
- `docker-compose.yml` / `docker-compose.prod.yml`: Container orchestration specs.
- `docker-entrypoint.sh`: Container entrypoint script.

---

## 3. Database Schema & Migration State

The application uses SQLAlchemy with Alembic for migrations:
- **Development Engine:** SQLite (`sqlite:///./intentlead.db` or in-memory for testing).
- **Production Engine:** PostgreSQL 16 (enforced in `resolve_database_url` when `APP_ENV != "development"`).
- **Migration Head:** `0005_add_draft_subject` (located at `apps/intelligence-api/alembic/versions/0005_add_draft_subject.py`).
- **Migration History:**
  1. `0001_initial.py`: Base tables (`businesses`, `leads`, `evidence`, `audit_logs`).
  2. `0002_approvals.py`: Human approval workflows and outreach queues.
  3. `0003_outreach_mailboxes.py`: Mailbox pooling and rotation.
  4. `0004_conversations_and_followups.py`: Multi-step follow-up sequences and threading.
  5. `0005_add_draft_subject.py`: Independent draft subject field on `message_drafts`.

---

## 4. Current Security Posture & Vulnerability Findings

A preliminary inspection of the codebase reveals several critical security and operational gaps that must be remediated:

### A. Vulnerability 1 — Dashboard Route Authorization Void (High Severity)
All HTML dashboard endpoints in `apps/intelligence-api/app/web/routes.py` (`/`, `/overview`, `/leads`, `/approvals`, `/campaigns`, `/mailboxes`, `/analytics`, `/suppression`, `/activity`, `/settings`, `/inbox`) lack operator authentication. Any network client with access to port 8000 can access the dashboard, view lead intelligence, approve or reject outreach, create campaigns, and modify configuration.
- **Remediation Plan:** Implement operator authentication with secure password hashing (`bcrypt`), HttpOnly session cookies, CSRF protection, and login rate limiting.

### B. Vulnerability 2 — Referer & Sec-Fetch-Site Header Spoofing (High Severity)
In `app/security.py`, `verify_api_key_or_operator` accepted requests as authenticated if `Sec-Fetch-Site: same-origin` or if the `Referer` contained the request host. Browser headers can be forged by non-browser clients or manipulated in cross-origin scenarios, allowing API endpoints to be invoked without authentication.
- **Remediation Plan:** Remove header-based pseudo-authentication. Require either a valid `X-API-Key` / Bearer token or a cryptographically verified operator session cookie.

### C. Vulnerability 3 — Anonymous Fallback in Development & Weak Key Permissiveness (Medium Severity)
In `app/security.py`, if `API_KEY` was not configured in `Settings`, the system permitted `"development_anonymous"` access without requiring authentication. In production deployments with misconfigured `.env` files, this presents severe risk.
- **Remediation Plan:** In production, startup must fail closed if `API_KEY` is not set or uses a trivial placeholder (<16 characters or default values).

### D. Vulnerability 4 — Migration Failure Swallowing in Docker Entrypoint (Medium Severity)
In both `docker-entrypoint.sh` and `apps/intelligence-api/docker-entrypoint.sh`, database migrations are run with:
`alembic upgrade head || { echo "WARNING: Alembic migration failed..."; }`
This swallows migration failures and allows containers to start against an unmigrated or corrupt schema.
- **Remediation Plan:** Enforce strict error handling (`alembic upgrade head || exit 1`) and pre-migration database connectivity checks.

### E. Vulnerability 5 — Database Runtime Race Condition (`Base.metadata.create_all`)
In `app/main.py`, `Base.metadata.create_all(bind=engine)` was executed during application startup. In a multi-worker production environment, multiple processes attempting DDL concurrently can cause table locks or race conditions.
- **Remediation Plan:** Restrict `create_all` strictly to development/test environments. In production, Alembic migrations must be the sole mechanism for DDL.

---

## 5. Baseline Test Suite Execution Analysis

An automated run of the complete test suite (`pytest apps/intelligence-api/tests -q`) was executed against baseline commit `26098c2`.

### Overall Results:
- **Total Tests:** 171
- **Passed:** 168 (98.2%)
- **Failed:** 3 (1.8%)
- **Execution Time:** ~178 seconds

### Root Cause Analysis of the 3 Baseline Failures:

1. **`test_agency_identity_defaults_empty`** (`apps/intelligence-api/tests/test_config_db.py:29`)
   - **Assertion:** `assert s.AGENCY_NAME == ""`
   - **Actual Value:** `'IntentLead'`
   - **Root Cause:** As part of open-source transformation, `app/config.py` was updated to provide sensible self-hosting defaults (`AGENCY_NAME = "IntentLead"`, `AGENCY_SENDER_NAME = "Outreach Team"`), whereas this unit test assumed empty string defaults.
   - **Action:** Update test assertion to reflect the intended self-hosting open-source defaults while verifying that environment variables can still override them.

2. **`test_six_step_wizard_best_response_template`** (`apps/intelligence-api/tests/test_sub_campaigns.py:545`)
   - **Assertion:** `assert "Step 1/6" in res.json()["reply"]`
   - **Actual String:** `"🎯 *Universal Client Discovery (Step 1/7)*"`
   - **Root Cause:** Obsolete test assertion. The Telegram onboarding wizard was expanded from 6 steps to 7 steps to accommodate Question 7 (Follow-Up Sequence Configuration). The legacy test in `test_sub_campaigns.py` was not updated to reflect the 7-step wizard.
   - **Action:** Update the test to follow the complete 7-step interactive wizard through Question 7 and confirmation.

3. **`test_six_step_wizard_personalized_choice`** (`apps/intelligence-api/tests/test_sub_campaigns.py:623`)
   - **Assertion:** `assert "Step 6/6" in res.json()["reply"]`
   - **Actual String:** `"💬 *Step 6/7: High-Converting Cold Outreach Template*"`
   - **Root Cause:** Same as failure #2; obsolete 6-step assertion on a 7-step wizard.
   - **Action:** Update assertion to `"Step 6/7"` and complete the Question 7 sequence.

---

## 6. Target State & Remediation Roadmap

The 13-phase remediation plan will transform IntentLead AI into an enterprise-grade, secure, portable open-source distribution:

| Phase | Objective | Scope |
|---|---|---|
| **Phase 0** | Baseline & Defect Classification | Complete baseline report; fix 3 obsolete test assertions. |
| **Phase 1** | Operator Authentication & Web Route Protection | Password hashing, session cookies, rate-limited `/login`, authenticated dashboard. |
| **Phase 2** | API Authentication Hardening | Strict API key validation, eliminate header spoofing, fail-closed production config. |
| **Phase 3** | CSRF, CORS & Request Security | CSRF double-submit cookies, strict CORS allowlist, request size limits. |
| **Phase 4** | Database Migration & Startup Reliability | Fail-closed entrypoint, `0006_operator_auth` migration, DB pre-flight checks. |
| **Phase 5** | Outbound Email & Approval Safety | Verify Gate 0 human approval invariant, suppression checks, dry-run enforcement. |
| **Phase 6** | AI Draft Studio Functional Verification | Verify manual on-demand generation, lead-specific context, and persistence. |
| **Phase 7** | Telegram Operator Workflow Verification | Verify 7-step wizard, callback handling, follow-up cadence persistence. |
| **Phase 8** | Follow-Up Scheduler & Inbound Webhook Reliability | Verify follow-up engine, replay protection, secret validation. |
| **Phase 9** | Docker Orchestration & Multi-Platform Portability | Verify non-root containers, healthchecks, internal network isolation. |
| **Phase 10** | Secret Hygiene & Repository Cleansing | Scan git history and working tree for credentials; harden `.gitignore`. |
| **Phase 11** | Open-Source Documentation & Packaging | Comprehensive README, deployment guide, architecture docs, LICENSE, NOTICE. |
| **Phase 12** | Full Test Suite Execution & Acceptance | Execute full test suite with 100% pass rate; compile final reports. |

---
*Report certified by Principal Reliability Engineer & Security Auditor.*
