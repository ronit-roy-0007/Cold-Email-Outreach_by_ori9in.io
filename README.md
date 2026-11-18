# IntentLead AI 🚀

**Autonomous B2B Lead Intelligence, Evidence-Based Qualification & Multi-Mailbox Outreach Platform**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%2016-336791.svg)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Cache-Redis%207-DC382D.svg)](https://redis.io/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Safety](https://img.shields.io/badge/Safety-Dry--Run%20Enforced-green.svg)](#-outreach-safety-controls)

IntentLead AI is an open-source, **100% self-hosted and independent** B2B lead acquisition and cold outreach automation platform. Each installation operates entirely autonomously within your own infrastructure without any dependency on external proprietary cloud backends.

Unlike generic bulk scrapers that blast unverified lists, IntentLead AI gathers concrete technical evidence, scores lead intent, generates hyper-personalized pitches via Google Gemini, and provides full operator approval gates via an interactive web dashboard and mobile Telegram bot.

---

## 🌟 Key Capabilities

- **Autonomous Business Discovery**: Discovers local businesses via Google Maps using Scrapling (Patchright + curl_cffi) or modular scraper backends.
- **Deep Website Reconnaissance**: Crawls prospect websites to detect concrete technical and conversion gaps (missing mobile responsiveness, lack of appointment booking, missing 24/7 AI chat, slow lead intake).
- **Evidence-Based Intent Scoring (0–100)**: Evaluates prospect friction and qualifies high-intent opportunities against configurable benchmark thresholds.
- **AI Draft Studio**: Operator-controlled individual lead draft studio embedded in the web dashboard (`/leads/{lead_id}`) with on-demand Gemini AI generation, independent subject & body editing, and optimistic concurrency versioning.
- **AI Pitch Personalization**: Crafts hyper-personalized pain-point pitches using Google Gemini 1.5 Flash (free tier supported) with structured JSON generation and sliding-window rate limiting.
- **Multi-Mailbox Pool Rotation**: Distributes outbound volume across multiple Gmail, Google Workspace, or SMTP accounts with daily volume limits (`MAX_EMAILS_PER_DAY=40`) and human deliverability pacing.
- **7-Step Telegram Command Center**: Full mobile control via an authorized Telegram bot—discover leads, approve pitches, review campaign metrics, and receive instant prospect reply alerts.
- **Intelligent Follow-Up Scheduler**: Persistent multi-touch follow-up sequences supporting business-day calculations (skipping weekends), calendar days, or single-touch outreach.
- **Inbound Reply Cancellation**: Webhooks with atomic Redis replay protection (`SET NX`) and strict XSS sanitization that automatically cancel pending follow-up touches the moment a prospect replies.
- **CAN-SPAM & Anti-Spam Compliance**: Enforces legitimate business postal address requirements via `BUSINESS_POSTAL_ADDRESS`, signed one-click unsubscribes, permanent suppression lists, and a default `OUTREACH_DRY_RUN=true` safety switch.

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

## 🧰 Technology Stack

| Layer | Technologies |
|---|---|
| **API & Web Server** | FastAPI, Uvicorn, Pydantic v2, Starlette |
| **Database & ORM** | PostgreSQL 16 (production/Docker) / SQLite (local dev), SQLAlchemy 2.0, Alembic |
| **Distributed Cache** | Redis 7 (replay protection, distributed rate limiting) |
| **Web Crawling** | Scrapling, Patchright, curl_cffi, BeautifulSoup4 |
| **AI Personalization** | Google Gemini API (gemini-1.5-flash), httpx |
| **Email Transport** | Python smtplib (STARTTLS), Resend API, Google Workspace SMTP |
| **Operator UI** | Jinja2 Neo-Brutalist Dashboard, Telegram Bot API |

---

## 📋 Prerequisites

- **Python**: Version 3.11 or 3.12
- **Git**: For cloning and revision management
- **Docker & Docker Compose** *(Recommended)*: For containerized PostgreSQL, Redis, API, and Worker deployment
- **Google Gemini API Key** *(Optional but recommended)*: Free key from [Google AI Studio](https://aistudio.google.com/)
- **Telegram Bot Token** *(Optional)*: Free bot token from [@BotFather](https://t.me/BotFather)

---

## ⚡ Quickstart

### 1. Clone the Repository
```bash
git clone https://github.com/ronit-roy-0007/Cold-Email-Outreach_by_ori9in.io.git
cd Cold-Email-Outreach_by_ori9in.io
```

### 2. Interactive Setup Wizard (Recommended — 60 Seconds)
Run the guided configuration wizard to automatically configure your database engine (PostgreSQL or SQLite), web operator credentials, Gemini AI key, and mailboxes:

```bash
python setup.py
```
*Note: Running `.\start.ps1` (Windows) or `./start.sh` (Linux) will automatically detect unconfigured installations and launch the setup wizard for you!*

---

## 🐳 Docker Compose Deployment

Docker Compose is the recommended deployment method for production and multi-service environments:

```bash
# 1. Copy the example configuration template
cp .env.example .env

# 2. Configure your environment variables (.env)
# (Ensure POSTGRES_PASSWORD, BOOTSTRAP_OPERATOR_PASSWORD, and USER_LLM_API_KEY are set)

# 3. Launch the container stack
docker compose up -d --build

# 4. Inspect container health and service status
docker compose ps

# 5. Monitor logs
docker compose logs -f api
docker compose logs -f worker
```

### Stopping and Data Persistence
- **Stop containers (preserve database volume):**
  ```bash
  docker compose down
  ```
- **Reset local test data (wipes PostgreSQL volume):**
  ```bash
  docker compose down -v
  ```

---

## 💻 Local Standalone Installation (Without Docker)

### Windows (PowerShell)
```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install -r apps/intelligence-api/requirements.txt

# 3. Launch IntentLead AI (runs migrations, API, and Telegram poller)
.\start.ps1 -Both
```

### Linux / macOS
```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install -r apps/intelligence-api/requirements.txt

# 3. Launch IntentLead AI
./start.sh --both
```

Access the dashboard at **`http://localhost:8000`** and log in with your configured operator credentials.

---

## ⚙️ Environment Configuration Reference

Key variables in `.env` (see [`.env.example`](.env.example) for complete documentation):

| Variable | Description | Default |
|---|---|---|
| `APP_ENV` | Application environment (`development` or `production`) | `development` |
| `DATABASE_URL` | SQLAlchemy database URL (PostgreSQL or SQLite) | `sqlite:///./intentlead.db` |
| `OUTREACH_DRY_RUN` | **Safety Switch**: simulated dispatches when `true` | `true` |
| `BUSINESS_POSTAL_ADDRESS` | **Mandatory for live outreach**: Real physical postal address | `""` |
| `USER_LLM_API_KEY` | Google Gemini API key for AI personalization | `""` |
| `USER_LLM_MODEL` | Gemini model name | `gemini-1.5-flash` |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | `""` |
| `TELEGRAM_ALLOWED_USER_ID` | Numeric Telegram user ID from @userinfobot | `""` |
| `SMTP_HOST` | Primary SMTP server host (e.g. `smtp.gmail.com`) | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port (e.g. `587` for STARTTLS) | `587` |
| `SMTP_USER` | SMTP username / email address | `""` |
| `SMTP_PASSWORD` | SMTP password or Google App Password | `""` |
| `MAILBOXES_FILE` | Multi-mailbox rotation pool JSON path | `mailboxes.json` |
| `MAX_EMAILS_PER_DAY` | Daily dispatch cap per mailbox account | `40` |

---

## 🔌 Integrations Setup Guide

### 1. Telegram Bot Setup
1. Message [@BotFather](https://t.me/BotFather) on Telegram and send `/newbot`. Follow prompts to get your **Bot Token**.
2. Message [@userinfobot](https://t.me/userinfobot) to get your numeric **User ID** (e.g., `123456789`).
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USER_ID` in your `.env`.
4. Start the poller: `python scripts/telegram_poller.py` (or use `.\start.ps1 -Both`).
5. Open your bot on Telegram and type `/start` or `/findleads`.

### 2. Gmail / SMTP Configuration
1. For Gmail accounts, enable 2-Factor Authentication and create an **App Password** at [Google Account App Passwords](https://myaccount.google.com/apppasswords).
2. Set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER=you@gmail.com`, and `SMTP_PASSWORD=your-app-password`.
3. For multiple sending accounts, populate [`mailboxes.json`](mailboxes.example.json) to enable automatic round-robin rotation and warmup pacing.

### 3. Google Gemini AI Setup
1. Create a free API key at [Google AI Studio](https://aistudio.google.com/).
2. Set `USER_LLM_API_KEY=your_key_here` and `USER_LLM_MODEL=gemini-1.5-flash`.
3. IntentLead AI uses Gemini to analyze prospect website evidence and generate concise, 3-sentence pain-point pitches.

### 4. Scrapling Discovery Engine
- **How It Works**: IntentLead AI uses Scrapling with headless anti-detect crawling to discover Google Maps listings and crawl prospect websites.
- **Honest Limitations**: Scrapling is **not an official Google Maps API**. Discovery yield depends on public listing density. Target websites may occasionally rate-limit or block scrapers.
- Read the full guide: [Lead Discovery with Scrapling](docs/discovery-scrapling.md).

---

## 🖼️ User Interface Screenshots

*Screenshots from the IntentLead AI v0.3.0 dashboard and operator tools:*

| View | Screenshot Placeholder |
|---|---|
| **Overview Dashboard** | `[Screenshot: docs/screenshots/dashboard_overview.png]`<br>*Real-time conversion pipeline, verified business counts, and human approval queues.* |
| **AI Draft Studio** | `[Screenshot: docs/screenshots/ai_draft_studio.png]`<br>*Individual lead view with on-demand Gemini AI pitch generation, live subject/body editor, and versioning.* |
| **Campaign Manager** | `[Screenshot: docs/screenshots/campaign_management.png]`<br>*Campaign status telemetry, CSV exports, and safe cascading campaign deletion.* |
| **Telegram Command Center** | `[Screenshot: docs/screenshots/telegram_bot.png]`<br>*Mobile Telegram bot interface with inline callback buttons for one-click approval.* |

---

## 🛡️ Outreach Safety Controls

IntentLead AI is engineered with defensive safeguards:
- **Default Simulation Dry-Run**: `OUTREACH_DRY_RUN=true` is strictly enabled by default. Outbound dispatches are simulated and recorded to the database without sending live emails.
- **Explicit Live Activation**: To dispatch real emails, an operator must deliberately set `OUTREACH_DRY_RUN=false` or send `/live` in Telegram.
- **Mandatory Postal Address Gate**: Live dispatch strictly fails closed if `BUSINESS_POSTAL_ADDRESS` is missing, preventing non-compliant outreach.
- **Pre-Flight Deliverability Gates**: Every recipient address is evaluated for syntax validity, disposable domain exclusion, MX record existence, and suppression list membership before dispatch.
- **Automatic Reply Cancellation**: Inbound prospect replies immediately cancel any scheduled follow-up touches to prevent accidental double-messaging.

---

## 🔧 Troubleshooting

| Issue | Cause | Solution |
|---|---|---|
| `Database connection failed` | PostgreSQL service not running | Start with `docker compose up -d db` or switch to SQLite `sqlite:///./intentlead.db` |
| `BUSINESS_POSTAL_ADDRESS missing` | Live mode active without address | Configure `BUSINESS_POSTAL_ADDRESS="Your Address"` in `.env` or set `OUTREACH_DRY_RUN=true` |
| `SMTPAuthenticationError` | Regular Gmail password used | Generate a 16-character Google Account App Password |
| `Telegram bot not responding` | Unauthorized user ID | Set `TELEGRAM_ALLOWED_USER_ID` in `.env` matching your ID from @userinfobot |
| `Gemini quota exceeded` | Free-tier rate limits reached | The built-in rate-limiter spaces requests; reduce batch size or configure billing on AI Studio |

---

## 🧪 Testing & Verification

Run the test suite locally:
```bash
# Run complete unit and integration test suite (200+ tests)
$env:PYTHONPATH="apps/intelligence-api"  # Windows
export PYTHONPATH="apps/intelligence-api"  # Linux / macOS
pytest apps/intelligence-api/tests -q

# Run automated secret scanning audit
python scripts/scan_tracked_secrets.py
```

---

## 🤝 Contributing

We welcome community contributions! Please review [CONTRIBUTING.md](CONTRIBUTING.md) and our [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before submitting pull requests.

---

## 📄 License & Attribution

IntentLead AI is open-source software licensed under the **[Apache License 2.0](LICENSE)**.
Third-party component notices and licenses are detailed in **[NOTICE](NOTICE)**.
