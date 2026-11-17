# IntentLead AI — Frequently Asked Questions (FAQ)

---

### General & Architecture

#### What is IntentLead AI?
IntentLead AI is an autonomous, open-source B2B lead intelligence, acquisition, and cold outreach platform. It combines automated local business discovery, website reconnaissance, evidence-based intent scoring, AI pitch generation, multi-mailbox email rotation, and conversation tracking with Telegram operator controls.

#### Is IntentLead AI free and open source?
Yes! IntentLead AI is licensed under the Apache License 2.0. You are free to self-host, customize, modify, and integrate it into your own workflows.

#### Does IntentLead AI require n8n or external automation tools?
No. IntentLead AI runs as an entirely self-contained system. All workflows—scraping, audit scoring, email dispatch, follow-up sequencing, and Telegram interactions—are executed natively in Python using FastAPI, SQLAlchemy, PostgreSQL, and Redis.

---

### Telegram Operator Interface

#### Do I need a public domain or ngrok tunnel to run the Telegram bot?
No. The Telegram poller operates via long-polling (`getUpdates`). It initiates outbound HTTPS requests to the official Telegram Bot API, meaning it runs behind NAT, firewalls, and local development environments without needing open inbound ports.

#### Can unauthorized people interact with my bot?
No. IntentLead AI enforces strict single-operator whitelisting via `TELEGRAM_ALLOWED_USER_ID`. Messages or inline button clicks from any other account are rejected.

---

### Outreach & Deliverability

#### How do I avoid burning my main domain?
Never send cold emails from your primary corporate domain. Register 2–3 dedicated secondary domains, authenticate them with SPF, DKIM, and DMARC, and rotate multiple mailboxes using the built-in mailbox pool (`mailboxes.json`).

#### What happens if a prospect replies?
When an inbound reply is detected via webhook, the system matches the conversation thread, marks it `replied`, immediately cancels all pending follow-up messages for that prospect, and sends a priority notification to the operator.

#### What happens if a prospect unsubscribes?
Every outbound email includes a signed one-click unsubscribe link. Clicking it immediately adds the prospect's email to the permanent `SuppressionEntry` registry, blocking any future messages across all campaigns.
