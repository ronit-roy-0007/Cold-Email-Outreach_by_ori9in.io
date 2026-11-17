# IntentLead AI — Technical Architecture & System Design

IntentLead AI is an autonomous, event-driven B2B lead intelligence, acquisition, and outreach orchestration system.

---

## 1. High-Level System Architecture

```mermaid
flowchart TD
    subgraph "External World"
        GMaps["Google Maps & Web"]
        Prospects["Prospect Mailboxes"]
        Operator["Telegram Operator Mobile"]
    end

    subgraph "IntentLead AI Platform"
        subgraph "Ingestion & Discovery"
            Disc["Scrapling / Google Maps Scraper"]
            SSRF["SSRF Guard & Robots Filter"]
            Parser["Web Page & Social Parser"]
        end

        subgraph "Intelligence Core"
            Scorer["Evidence-Based Scoring Engine"]
            AuditLog["Tamper-Evident Audit Log"]
            Gemini["AI Personalization (Gemini 1.5)"]
        end

        subgraph "Operator Interfaces"
            WebUI["FastAPI Web Dashboard (Jinja2)"]
            TGPoller["Telegram Poller (7-Step Wizard)"]
            UnifiedInbox["Unified Inbox (PostgreSQL)"]
        end

        subgraph "Outreach & Dispatch"
            MailboxPool["Mailbox Rotation Pool (Fernet)"]
            Gate["Gate 0 Approval & Pacing"]
            Dispatcher["Email Dispatcher (SMTP/Resend)"]
            FollowUpEngine["Follow-Up Scheduler Engine"]
            InboundRouter["Inbound Webhooks (Replay Protected)"]
        end

        subgraph "Data Storage"
            Postgres[("PostgreSQL 16")]
            Redis[("Redis 7 (Atomic SET NX)")]
        end
    end

    GMaps --> Disc
    Disc --> SSRF --> Parser --> Scorer
    Scorer --> Postgres
    Scorer --> TGPoller
    Operator <--> TGPoller
    Operator <--> WebUI
    TGPoller --> Gate
    WebUI --> Gate
    Gate --> MailboxPool --> Dispatcher
    Dispatcher --> Prospects
    Dispatcher --> FollowUpEngine
    Prospects --> InboundRouter
    InboundRouter --> Redis
    InboundRouter --> UnifiedInbox
    InboundRouter -.->|Cancel due follow-ups| FollowUpEngine
    AuditLog --> Postgres
```

---

## 2. Component Lifecycles & Responsibilities

### A. FastAPI Web & API Application (`app/main.py`)
- **Process**: ASGI process powered by Uvicorn.
- **Port**: `8000` (internal or reverse-proxied).
- **Duties**:
  - Serves administrative Web UI (`app/web/routes.py`, `app/web/templates/`).
  - Implements REST APIs (`/api/leads`, `/api/campaigns`, `/api/outreach`, `/api/inbound`).
  - Enforces API authentication, rate limiting, and CORS allowlisting.
  - Exposes health probes (`/health/live`, `/health/ready`).

### B. Autonomous Telegram Operator Poller (`scripts/telegram_poller.py`)
- **Process**: Independent daemon process or container service.
- **Protocol**: Long-polling (`getUpdates`) with Telegram Bot API.
- **Duties**:
  - Whitelists authorized numeric Telegram Operator ID (`TELEGRAM_ALLOWED_USER_ID`).
  - Guides operator through the interactive 7-step onboarding wizard.
  - Delivers real-time lead discovery alerts and inline approval cards.
  - Persists state across restarts in `state/telegram_sessions.json`.

### C. Background Follow-Up Worker (`scripts/worker.py`)
- **Process**: Independent daemon process or container service.
- **Duties**:
  - Periodically queries `FollowUpExecution` table with `with_for_update(skip_locked=True)`.
  - Evaluates business-day vs calendar-day delays, skipping weekends.
  - Checks suppression list and conversation reply status before dispatch.
  - Dispatches due follow-up touches or marks them cancelled.

### D. Inbound Processing & Replay Protection (`app/api/inbound.py`)
- **Endpoints**: `/api/inbound/sendgrid`, `/api/inbound/postmark`, `/api/inbound/webhook`.
- **Security**:
  - Atomic distributed replay deduplication via Redis `SET key '1' EX ttl NX`.
  - Fails closed in production if Redis is unavailable.
  - Cryptographic signature / shared secret verification.
  - Strict HTML sanitization against XSS and script injection.

### E. AI Personalization & Draft Studio (`app/services/gemini_personalizer.py` & `app/api/leads.py`)
- **Unified Engine**: Shared by Telegram bot and Web Dashboard. Both interfaces consume the same structured JSON output (`{"subject": "...", "body": "..."}`).
- **Endpoints**:
  - `POST /api/leads/{lead_id}/ai-generate`: On-demand preview generation without DB mutation.
  - `POST /api/leads/{lead_id}/ai-generate/regenerate`: Refreshed preview generation with unsaved-change safeguard.
  - `PUT /api/leads/{lead_id}/ai-draft`: Optimistic concurrency persistence (`version += 1`) into PostgreSQL `message_drafts`.
  - `GET /api/leads/{lead_id}/ai-draft`: Draft and version inspection endpoint.
- **Auditing**: Every manual draft save writes an immutable audit record to `audit_logs` tracking actor, draft ID, subject, and version.
- **Safety Invariant**: Manual generation and saving never trigger email dispatches or bypass Gate 0 human approval.

---

## 3. Lead Discovery & Qualification Workflow

```mermaid
flowchart LR
    A["Operator: /findleads"] --> B["Discovery Engine"]
    B --> C["Fetch Public Sites"]
    C --> D["SSRF & IP Validation"]
    D --> E["Extract Contacts & Socials"]
    E --> F["Evaluate Evidence & Score"]
    F --> G{"Score >= Benchmark?"}
    G -- No --> H["Discarded / Below Threshold"]
    G -- Yes --> I["Awaiting Approval (Gate 0)"]
    I --> J["Generate AI Pitch"]
```

---

## 4. Multi-Touch Follow-Up Engine State Machine

```mermaid
stateDiagram-v2
    [*] --> Scheduled: Initial Dispatch Created
    Scheduled --> InProgress: Due Time Reached & Worker Acquires Lock
    InProgress --> Dispatched: Preflight Passed & Dispatched
    InProgress --> Cancelled: Prospect Replied
    InProgress --> Cancelled: Prospect Opted Out / Suppressed
    InProgress --> Cancelled: Campaign Stopped
    InProgress --> Failed: Temporary Delivery Failure (Retry with Backoff)
    Dispatched --> Scheduled: Next Step in Cadence Exists
    Dispatched --> Completed: All Sequence Steps Finished
    Completed --> [*]
    Cancelled --> [*]
```
