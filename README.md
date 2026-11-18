# IntentLead AI 🚀

**Autonomous B2B Lead Intelligence, Evidence-Based Qualification & Multi-Mailbox Outreach Platform**

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%2016-336791.svg)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Cache-Redis%207-DC382D.svg)](https://redis.io/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Safety](https://img.shields.io/badge/Safety-Dry--Run%20Enforced-green.svg)](#outreach-safety-controls)

IntentLead AI is an open-source, self-hosted lead acquisition and cold outreach automation platform. Unlike generic mass-email tools that blast unverified lists, IntentLead combines stealth Google Maps discovery, concurrent website reconnaissance, evidence-based intent scoring, hyper-personalized AI pitch generation, and an interactive 7-step Telegram operator bot—all safely dispatched through a rotating multi-mailbox pool with automated deliverability pacing and multi-touch follow-up scheduling.

---

## 🌟 Key Capabilities

- **Stealth Business Discovery**: Harvests local businesses via Google Maps using Scrapling (Patchright + curl_cffi) or modular scraper backends.
- **Deep Website Reconnaissance**: Crawls prospect websites to detect concrete technical and conversion gaps (missing mobile responsiveness, lack of appointment booking, missing 24/7 AI chat, slow lead intake).
- **Evidence-Based Intent Scoring (0–100)**: Evaluates prospect friction and qualifies high-intent opportunities against configurable benchmark thresholds.
- **AI-Powered Personalization**: Crafts hyper-personalized 3-sentence pain-point pitches using Google Gemini 1.5 Flash (with sliding-window rate limiting) or OpenAI-compatible gateways.
- **Proven High-Converting Template Option**: Allows operators to toggle between bespoke AI audits and proven conversion-tested outreach copy.
- **Multi-Mailbox Pool Rotation**: Distributes outbound volume across multiple Gmail / Google Workspace / SMTP accounts with daily volume limits (`MAX_EMAILS_PER_DAY=40`) and human pacing.
- **7-Step Telegram Command Center**: Full mobile control via an authorized Telegram bot—discover leads, approve pitches, review campaign metrics, and receive instant reply alerts.
- **Intelligent Follow-Up Scheduler**: Persistent multi-touch sequences supporting business-day calculations (skipping weekends), calendar days, or single-touch outreach.
- **Inbound Conversation Management**: Integrates SendGrid Inbound Parse, Postmark, and generic webhooks with atomic Redis replay protection (`SET NX`) and strict XSS sanitization.
- **Regulatory Compliance & Safety**: Enforces CAN-SPAM and GDPR requirements with signed one-click unsubscribes, physical agency address footers, permanent suppression lists, and a default `OUTREACH_DRY_RUN=true` safety switch.

---

## 🏗️ System Architecture

```text
                           ┌────────────────────────────────────────┐
                           │      Telegram Operator Bot             │
                           │   (/findleads, /status, /review)       │
                           └───────────────────┬────────────────────┘
                                               │
                                               ▼
                           ┌────────────────────────────────────────┐
                           │      Stealth Discovery Engine          │
                           │   (Scrapling + Google Maps Scraper)    │
                           └───────────────────┬────────────────────┘
                                               │
                                               ▼
                           ┌────────────────────────────────────────┐
                           │     Website Reconnaissance Crawler     │
                           │   - Verified Email & Social extraction │
                           │   - SSRF Guard & IP Range Blocker      │
                           │   - Technical Gap & Friction Detection │
                           └───────────────────┬────────────────────┘
                                               │
                                               ▼
                           ┌────────────────────────────────────────┐
                           │    Scoring & Personalization Engine    │
                           │   - 0–100 Evidence-Based Score         │
                           │   - Gemini 1.5 Pitch Generation        │
                           │   - Gate 0 Human Approval Review       │
                           └───────────────────┬────────────────────┘
                                               │
                                               ▼
                           ┌────────────────────────────────────────┐
                           │     Multi-Mailbox Dispatch Pool        │
                           │   - Round-robin mailbox rotation       │
                           │   - Daily sending caps (40/day)        │
                           │   - Warmup pacing & jitter delays      │
                           └───────────────────┬────────────────────┘
                                               │
                                               ▼
                           ┌────────────────────────────────────────┐
                           │    Multi-Touch Follow-Up Engine        │
                           │   - Calendar & Business day schedules  │
                           │   - Auto-cancel on reply or opt-out    │
                           │   - Unified Inbox & Conversation sync  │
                           └────────────────────────────────────────┘
```

---

## ⚡ Quickstart & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/ronit-roy-0007/Cold-Email-Outreach_by_ori9in.io.git
cd Cold-Email-Outreach_by_ori9in.io
```

### 2. Interactive Setup Wizard (Recommended - 60 Seconds)
Run the guided configuration wizard to automatically configure your database (SQLite or PostgreSQL), admin login credentials, Google Gemini AI key, and Telegram bot:

```bash
python setup.py
```
*Note: If you run `.\start.ps1` (Windows) or `./start.sh` (Linux), it will automatically detect a new installation and launch the setup wizard for you!*

---

### Alternative: Docker Compose Setup

```bash
# 1. Copy configuration template
cp .env.example .env

# 2. Launch container stack
docker compose up -d --build

# 3. Create your admin operator account
docker compose exec api python scripts/bootstrap_operator.py --username admin --password "YourSecurePassword!"
```

### 3. Launching IntentLead AI

- **Windows (PowerShell):**
  ```powershell
  .\start.ps1 -Both
  ```
- **Linux / macOS:**
  ```bash
  ./start.sh --both
  ```

### 4. Authenticate to the Operator Dashboard
Navigate to:
```text
http://localhost:8000/login
```
Log in using the operator username and password you configured during setup.

---

## 📚 Documentation Directory

Complete setup, operational, and architectural documentation is available in the [`docs/`](docs/) directory:

- **Deployment & Installation**:
  - [Universal Installation Guide](docs/installation.md)
  - [Windows 10/11 Guide](docs/windows-installation.md)
  - [Linux (Debian/Ubuntu/RHEL) Guide](docs/linux-installation.md)
  - [macOS (Apple Silicon & Intel) Guide](docs/macos-installation.md)
  - [Ubuntu VPS Production Deployment Guide](docs/vps-deployment.md)
- **Configuration & Integrations**:
  - [Full Configuration Reference (.env)](docs/configuration.md)
  - [Telegram Bot Operator Guide](docs/telegram-setup.md)
  - [AI Provider & Personalization Guide](docs/ai-provider-setup.md)
  - [Email Provider & Mailbox Pool Guide](docs/email-provider-setup.md)
  - [DNS Email Authentication (SPF, DKIM, DMARC)](docs/dns-email-setup.md)
- **Security, Privacy & Operations**:
  - [Security Architecture & Threat Model](docs/security.md)
  - [Privacy & Regulatory Compliance (CAN-SPAM/GDPR)](docs/privacy.md)
  - [Backup, Restore & Disaster Recovery](docs/backup-restore.md)
  - [Upgrading & Database Migrations](docs/upgrading.md)
  - [Troubleshooting & Diagnostics](docs/troubleshooting.md)
  - [Frequently Asked Questions (FAQ)](docs/faq.md)
  - [Technical Architecture Specification](docs/architecture.md)

---

## 🛡️ Outreach Safety Controls

IntentLead AI is engineered with defensive safeguards:
- **Default Simulation Dry-Run**: `OUTREACH_DRY_RUN=true` is strictly enabled by default. Outbound dispatches are simulated and recorded to the database without sending live emails.
- **Explicit Live Activation**: To dispatch real emails, an operator must deliberately set `OUTREACH_DRY_RUN=false` or send `/live` in Telegram.
- **Pre-Flight Deliverability Gates**: Every recipient address is evaluated for syntax validity, disposable domain exclusion, MX record existence, and suppression list membership before dispatch.
- **Automatic Reply Cancellation**: Inbound prospect replies immediately cancel any scheduled follow-up touches to prevent accidental double-messaging.

---

## 🧪 Testing & Verification

Run the test suites locally:
```bash
# Telegram Bot test suite
$env:PYTHONPATH="apps/intelligence-api"
pytest apps/intelligence-api/tests/test_telegram.py

# Complete 15-Workflow Operational Acceptance Suite
python scripts/test_operational_acceptance.py

# Telegram Live Runtime Requirements & Secret Audit
python scripts/verify_telegram_runtime_requirements.py
```

---

## 📄 License & Attribution

IntentLead AI is open-source software licensed under the **[Apache License 2.0](LICENSE)**.
Third-party component notices and licenses are detailed in **[NOTICE](NOTICE)**.
