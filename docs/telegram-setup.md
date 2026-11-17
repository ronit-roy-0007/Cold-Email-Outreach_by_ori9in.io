# IntentLead AI — Telegram Operator Bot Setup Guide

This guide walks you through configuring and operating your own private Telegram bot for IntentLead AI.
The Telegram bot acts as an autonomous mobile command center for discovering leads, triggering audits, approving pitches, and receiving inbound lead alerts.

---

## 1. Creating Your Telegram Bot

1. Open Telegram and search for the official **[@BotFather](https://t.me/BotFather)**.
2. Send `/start`, then send `/newbot`.
3. Choose a display name (e.g., `My Agency Lead Bot`).
4. Choose a username ending in `bot` (e.g., `myagency_lead_bot`).
5. BotFather will provide an HTTP API token formatted like:
   ```text
   7123456789:AAFlkBZ..._example_token_do_not_share
   ```
6. Copy this token. This is your `TELEGRAM_BOT_TOKEN`.

---

## 2. Finding Your Numeric Operator User ID

For security, IntentLead AI strictly enforces **single-operator whitelisting**. Only your personal numeric Telegram account ID can interact with the bot.

1. In Telegram, search for **[@userinfobot](https://t.me/userinfobot)** or **[@RawDataBot](https://t.me/RawDataBot)**.
2. Send `/start`.
3. The bot will reply with your profile info, including your numeric `Id` (e.g., `123456789`).
4. Copy this number. This is your `TELEGRAM_ALLOWED_USER_ID`.

---

## 3. Configuring Your Environment

Add your bot credentials to your `.env` file:

```bash
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=7123456789:AAFlkBZ...
TELEGRAM_ALLOWED_USER_ID=123456789
```

> [!IMPORTANT]
> Never share or commit your bot token. The application automatically redacts bot tokens in logs, tracebacks, and error outputs to prevent accidental disclosure.

---

## 4. Running the Telegram Poller

IntentLead AI uses **long-polling** (`getUpdates`), meaning you **do not need** a public IP, domain name, or ngrok tunnel to run the bot locally or in development.

### Option A: Via Docker Compose (Recommended)
```bash
docker compose up -d telegram-poller
```
To view live poller logs:
```bash
docker compose logs -f telegram-poller
```

### Option B: Directly with Python
From the repository root:
```bash
# Windows PowerShell:
$env:PYTHONPATH="apps/intelligence-api"
python scripts/telegram_poller.py

# Linux / macOS:
export PYTHONPATH="apps/intelligence-api"
python scripts/telegram_poller.py
```

Upon startup, the poller automatically synchronizes native bot commands with Telegram:
```text
[INFO] Synced native Telegram commands menu: {"ok":true,"result":true}
[INFO] Starting Telegram Poller for agency 'IntentLead'...
[INFO] Authorized Telegram User ID: 123456789
[INFO] Waiting for Telegram commands (/findleads, /status, /export_csv, /showpriority)...
```

---

## 5. Available Commands

| Command | Description |
|---|---|
| `/findleads` | Starts the 7-step campaign wizard for client discovery in any city or niche. |
| `/status` | Displays progress, dispatched counts, and open rates of recent campaigns. |
| `/review` | Step-by-step 1-by-1 manual approval for audited leads and AI pitches. |
| `/export_csv` | Generates a downloadable CSV export of qualified leads. |
| `/showpriority` | Surfaces urgent unreplied high-score leads requiring immediate attention. |
| `/mode` | Displays current outreach dispatch mode (`DRY-RUN` vs `LIVE`). |
| `/live` | Switches engine to live outbound email dispatch (requires confirmation). |
| `/dryrun` | Reverts engine to safe simulation dry-run mode. |
| `/help` | Lists all operator commands and syntax. |

---

## 6. The 7-Step Campaign Onboarding Wizard

When you send `/findleads`, the bot guides you through interactive configuration:

1. **Step 1/7 — Target Niche / Category**: (e.g. `Real Estate Agents`, `Dental Clinics`, `Roofing Contractors`).
2. **Step 2/7 — Target Location**: (e.g. `Austin, TX`, `Miami, FL`, `London, UK`).
3. **Step 3/7 — Search Radius / Breadth**: (e.g. `5 km`, `15 km`, `25 km`).
4. **Step 4/7 — Minimum Lead Intent Score**: (Threshold between 0 and 100; default `40`).
5. **Step 5/7 — Recommended Service Pitch**: (e.g. `AI Chatbot`, `Website Redesign`, `Appointment Automation`).
6. **Step 6/7 — Outreach Copy Selection**:
   - `[YES (Best-Response Template)]`: Uses our proven, universal high-converting cold outreach copy.
   - `[NO (Personalized AI Proposals)]`: Triggers deep website audit and AI personalization for each prospect.
7. **Step 7/7 — Follow-Up Cadence Configuration**:
   - `[Standard (Days 2, 5)]`: 2 automated touches (Calendar day intervals).
   - `[Business Days (Days 3, 7)]`: 2 touches skipping Saturdays and Sundays.
   - `[Single Touch (No follow-up)]`: Initial email only; follow-up engine disabled for this campaign.
   - `[Custom Intervals]`: Operator enters custom delay days (e.g. `3, 7, 14`).

---

## 7. Security & Safeguards

- **Access Enforcement**: Only requests originating from `TELEGRAM_ALLOWED_USER_ID` are processed. Messages or button clicks from other users are silently dropped or rejected with a permission notice.
- **Session Persistence**: Active wizard sessions and draft selections are stored locally in `state/telegram_sessions.json`. Restarting the poller or container does not erase in-progress onboarding state.
- **Outreach Safety**: Outbound email dispatch is locked in `DRY_RUN` mode by default. Switching to live sending via `/live` requires explicit confirmation.
