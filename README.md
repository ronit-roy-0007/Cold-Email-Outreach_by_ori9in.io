# IntentLead AI 🚀

**Autonomous Google Maps Lead Discovery, Website Intelligence & Multi-Mailbox Gmail Outreach Platform**

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Framework FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Scraper Scrapling](https://img.shields.io/badge/Scraper-Scrapling%20%2B%20Patchright-ff69b4.svg)](https://github.com/D4Vinci/Scrapling)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Maxxy%20Bot-2CA5E0.svg)](https://telegram.org/)
[![License MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

IntentLead AI is an open-source, evidence-led prospect discovery and outreach engine. Unlike generic scrapers that blast unverified lists, IntentLead combines stealth Google Maps discovery, concurrent website reconnaissance (extracting verified emails, social profiles, and missing tech gaps), AI/plain-text pitch generation, and an interactive Telegram bot command center—all safely dispatched through a multi-mailbox Gmail pool with automated rate limiting and deliverability gates.

---

## 🏗️ Architecture Overview

```
                      ┌──────────────────────────────────────┐
                      │      Telegram Command Center         │
                      │   (/findleads, /status, /addemail)   │
                      └──────────────────┬───────────────────┘
                                         │
                                         ▼
                      ┌──────────────────────────────────────┐
                      │    Stealth Discovery & Scraping      │
                      │ (Scrapling + Patchright + curl_cffi) │
                      │   - Google Maps listing harvester    │
                      │   - Multi-ring geographic expansion  │
                      └──────────────────┬───────────────────┘
                                         │
                                         ▼
                      ┌──────────────────────────────────────┐
                      │     Concurrent Website Crawler       │
                      │   - Verified Email & Social links    │
                      │   - Tech stack & gap detection       │
                      │   - Review sentiment & rating audit  │
                      └──────────────────┬───────────────────┘
                                         │
                                         ▼
                      ┌──────────────────────────────────────┐
                      │     Scoring & Copywriting Engine     │
                      │   - 0–100 benchmark qualification    │
                      │   - Clean 1-on-1 casual outreach     │
                      │   - Gemini AI 3-sentence pain-point  │
                      └──────────────────┬───────────────────┘
                                         │
                                         ▼
                      ┌──────────────────────────────────────┐
                      │   Deliverability Pre-Flight Gate     │
                      │   - Syntax & suppression blacklist   │
                      │   - DNS MX + RFC 7505 Null MX check  │
                      └──────────────────┬───────────────────┘
                                         │
                                         ▼
                      ┌──────────────────────────────────────┐
                      │     Multi-Mailbox Dispatcher         │
                      │   - Sequential round-robin rotation  │
                      │   - Survivor mailbox pacing guard    │
                      │   - 50 emails/day per Gmail account  │
                      └──────────────────────────────────────┘
```

---

## ✨ Key Features

* **Stealth Google Maps Scraper:** Built with [Scrapling](https://github.com/D4Vinci/Scrapling) and `patchright` (stealth Playwright chromium) with `curl_cffi` impersonation to bypass Google bot checks and scrape listings without getting blocked.
* **Concurrent Website Reconnaissance:** Automatically visits discovered business websites to extract contact emails, about pages, and social media profiles (Instagram, LinkedIn, Facebook, Twitter, YouTube).
* **Concentric Geographic Radius Expansion:** When a primary search location (e.g. *New York*) reaches saturation, the system automatically expands across concentric geographic rings (e.g. *Brooklyn → Queens → Jersey City*) to fulfill lead quotas.
* **Multi-Mailbox Pool Rotation:** Distributes outreach sequentially across an unlimited pool of connected Gmail accounts (`smtp.gmail.com:587`), preventing burst spikes and maintaining healthy domain reputation.
* **Smart Deliverability Pre-Flight Gate:** Pre-validates every recipient before dispatch. Checks email syntax, suppression blacklists, DNS MX records, and automatically blocks domains with **RFC 7505 Null MX** records.
* **Survivor Mailbox Pacing & Jitter Guard:** Applies randomized human delays (5–8s in normal pool; 30–40s cooldown if fewer than 3 mailboxes remain active) to eliminate automated sending patterns.
* **High-Converting Plain-Text Copywriting:** Delivers 100% human-looking emails. Strips out corporate marketing disclaimers, fake Delaware addresses, and tracking links that trigger spam filters.
* **Interactive Telegram Bot:** Control entire outreach campaigns from your phone using Telegram: start campaigns, approve batches, toggle Auto Mode, inspect leads, and download CSV reports directly in chat.
* **Optional Gemini AI Personalization:** Deeply personalizes pitches using Google Gemini based on specific audited website pain points (missing appointment calendars, lack of 24/7 chat support, outdated mobile layout).

---

## 📋 Prerequisites

* **Operating System:** Windows 10/11, macOS, or Linux
* **Python:** 3.12 or newer
* **Gmail Accounts:** 1 or more Gmail accounts with **2-Step Verification** and a generated **16-character Google App Password**
* **Telegram Bot:** A bot token from [@BotFather](https://t.me/BotFather) and your numeric Telegram user ID from [@userinfobot](https://t.me/userinfobot)

---

## 🚀 Installation & Setup Guide

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/intentlead-ai.git
cd intentlead-ai
```

### 2. Create Virtual Environment & Install Dependencies

```bash
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Install Browser & Stealth Fetcher Dependencies

```bash
scrapling install
python -m patchright install chromium
```

### 4. Configure Environment Variables

Copy the example environment template:

```bash
cp .env.example .env
```

Open `.env` and fill in your details:

```env
# Application Mode & Database
APP_ENV=development
DATABASE_URL=sqlite:///./intentlead.db
DISCOVERY_PROVIDER=scrapling

# Agency Identity
AGENCY_NAME=YourAgency.io
AGENCY_SENDER_NAME=YourName

# Outreach Safety (set to false for live sending)
OUTREACH_DRY_RUN=false

# Telegram Bot Credentials
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_ALLOWED_USER_ID=6107263210

# Primary Mailbox Settings (Fallback)
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=youremail@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop
SMTP_USE_TLS=true
MAX_EMAILS_PER_DAY=40
ENABLE_DISPATCH_PACING=true

# Optional: Google Gemini API (for AI personalization)
USER_LLM_API_KEY=AIzaSy...
USER_LLM_MODEL=gemini-1.5-flash
```

### 5. Configure Your Mailbox Pool (Optional)

You can define multiple Gmail sending accounts in `mailboxes.json`:

```bash
cp mailboxes.example.json mailboxes.json
```

Edit `mailboxes.json`:
```json
[
  {
    "email": "outreach1@gmail.com",
    "password": "abcd efgh ijkl mnop",
    "sender_name": "Ronit",
    "daily_limit": 40,
    "is_active": true
  },
  {
    "email": "outreach2@gmail.com",
    "password": "qrst uvwx yzab cdef",
    "sender_name": "Ronit",
    "daily_limit": 40,
    "is_active": true
  }
]
```

*(Note: You can also add mailboxes dynamically from Telegram at any time using `/addemailaddress`!)*

---

## 🤖 Starting the Telegram Bot Daemon

To launch the background Telegram bot poller:

```powershell
# Windows (PowerShell)
$env:PYTHONPATH = "apps/intelligence-api"
python scripts/telegram_poller.py

# Linux / macOS
export PYTHONPATH="apps/intelligence-api"
python3 scripts/telegram_poller.py
```

Once running, you will see:
```text
[INFO] Synced native Telegram commands menu: {"ok":true,"result":true}
[INFO] Starting Telegram Poller for agency 'YourAgency.io'...
[INFO] Waiting for Telegram commands (/findleads, /status, /export_csv)...
```

---

## 📱 Telegram Commands Reference

Open your Telegram bot chat and use the following commands:

| Command | Usage | Description |
| :--- | :--- | :--- |
| `/findleads` | `/findleads [Niche] in [City] [TargetCount] [MinScore]` | Launches a lead generation campaign (e.g. `/findleads Real Estate in Brooklyn 50 40`). |
| `/status` | `/status` | Displays real-time progress of active campaigns and mailbox usage. |
| `/export_csv` | `/export_csv` | Generates and sends a CSV of all qualified and contacted prospects. |
| `/addemailaddress` | `/addemailaddress <email> <app_password>` | Dynamically tests and adds a new Gmail account into your live sending pool. |
| `/showpriority` | `/showpriority` | Lists top-scored leads waiting for review. |

### Interactive Campaign Workflow:
1. **Interactive Wizard:** Choose niche, location, quantity, and outreach mode (Generic High-Reply or AI-Personalized).
2. **Review & Preview:** Maxxy delivers a preview CSV with all discovered leads and evidence scores.
3. **Dispatch Options:**
   * **Approve Batch 1:** Dispatches the first batch of leads and pauses for review.
   * **🤖 Auto Mode:** Continuously discovers, scrapes, audits, and delivers emails until your exact target (e.g. 50 sent emails) is fulfilled.
4. **Final Deliverables:** Automatically sends the final campaign CSV deliverables to your chat upon completion.

---

## 🛡️ Deliverability & Safe Sending Guidelines

To maintain **100% inbox placement** and keep your Gmail accounts in peak standing:

1. **Volume Scaling:**
   * **New Accounts (< 3 months old):** Keep at 10–20 emails/day.
   * **Aged Accounts (6+ months old):** Can safely send 30–40 emails/day.
   * *Formula:* If you need 500 emails/day, use **12 to 15 Gmail accounts** rather than overloading 2 accounts.
2. **Sequential Spacing:** The system automatically cycles across all active accounts. With 7 accounts, each account naturally rests for ~45–75 seconds between dispatches.
3. **App Passwords:** Always generate dedicated App Passwords from Google Account Settings > Security > 2-Step Verification > App Passwords.

---

## 🧪 Running the Test Suite

The project includes comprehensive test suites covering scraper deduplication, geo-expansion, mailbox rotation, MX preflight gates, and interactive subcampaign loops:

```bash
# Run all unit and integration tests
cd apps/intelligence-api
$env:PYTHONPATH = "."
pytest -v
```

---

## 📁 Repository Structure

```text
├── apps/
│   └── intelligence-api/
│       ├── app/
│       │   ├── api/             # FastAPI REST endpoints
│       │   ├── providers/       # Scrapling Google Maps client & fetchers
│       │   ├── scoring/         # Deterministic lead qualification engine
│       │   ├── services/        # Email dispatcher, mailbox pool, telegram bot
│       │   ├── config.py        # Centralized settings & environment loader
│       │   ├── db.py            # SQLAlchemy database engine
│       │   └── models.py        # Database ORM models
│       ├── tests/               # 80+ unit and integration test fixtures
│       └── requirements.txt     # Python dependencies
├── scripts/
│   └── telegram_poller.py       # Telegram polling daemon
├── .env.example                 # Example configuration template
├── mailboxes.example.json       # Example mailbox pool structure
├── requirements.txt             # Root requirements pointer
└── README.md                    # Project documentation
```

---

## ⚖️ License & Ethical Usage

This software is released under the [MIT License](LICENSE).

**Ethical Scraping & Outreach Notice:** This tool is intended for B2B relationship building and legitimate business inquiries. Always respect local privacy and communications regulations (including CAN-SPAM, GDPR, and CASL). Never use this system for unsolicited bulk consumer spam.
