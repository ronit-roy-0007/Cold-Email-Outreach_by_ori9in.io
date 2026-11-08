# IntentLead AI

**Evidence-led prospect discovery, qualification, personalized outreach, reply handling, and sales operations for a real-estate-focused automation agency.**

IntentLead AI is designed to find businesses that are a plausible fit for services—not to scrape a list and blast generic messages. Google Maps discovery supplies the initial business dataset. A separate intelligence layer audits public business information, records evidence, scores service fit, drafts personalized outreach, and routes actions through Telegram approval.

## Project status

**Phase 0–2 MVP is fully implemented and verified.**
All 69 unit and integration tests are passing. The Phase 0–2 MVP is an operator application with offline fixtures, mock/import/live discovery providers, SSRF and robots.txt audit protection, deterministic evidence scoring, dry-run draft previews, CSV export, Alembic migrations, and PostgreSQL persistence.

> Per Section 6 of the MVP design, live outreach, Telegram bots, n8n workflows, Google Sheets, and Google Calendar are strictly deferred to later phases. Outreach is permanently kept in dry-run preview mode.

See the detailed specifications and plans:
- MVP Design: `docs/superpowers/specs/2026-11-08-intentlead-mvp-design.md`
- Implementation Plan: `docs/superpowers/plans/2026-11-08-intentlead-mvp.md`

## Running the Phase 0–2 MVP

### Option 1: Docker Compose (PostgreSQL + API)

```bash
docker compose up --build
```
This spins up PostgreSQL 16 on port 5432 and the IntentLead API/Operator UI on `http://localhost:8000`.

### Option 2: Local Windows Development (PowerShell)

1. Make sure Python 3.12 is installed.
2. Install dependencies:
   ```powershell
   python -m pip install -r apps\intelligence-api\requirements.txt
   ```
3. Run with SQLite in development mode:
   ```powershell
   $env:APP_ENV = "development"
   $env:DATABASE_URL = "sqlite:///./dev.db"
   .\start.ps1
   ```
4. Or run with a local PostgreSQL instance:
   ```powershell
   $env:DATABASE_URL = "postgresql://intentlead:change-me@localhost:5432/intentlead"
   .\start.ps1
   ```
5. Open your browser at `http://localhost:8000` to access the Operator Dashboard.

### Running Tests

```powershell
cd apps\intelligence-api
$env:PYTHONPATH = "."
pytest -v
```

## Primary and reference repositories

| Role | Repository | How it is used |
|---|---|---|
| Primary discovery engine | [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper) | Run searches and collect public business listing data. Integrate through its REST API or supported output. |
| Reference / learning source | [Kappaemme-git/codex-first-customer-finder-skill](https://github.com/Kappaemme-git/codex-first-customer-finder-skill) | Study evidence-first research, weighted qualification, source verification, feedback/history, deduplication, and structured reports. Do not make it a runtime dependency. |

The second repository is **not** the scraper and does not replace the first repository. Its logic may be independently reimplemented where appropriate; do not copy code blindly. Review both upstream repositories' current licenses, notices, and terms before redistributing or modifying their source.

### Why the repositories are not bundled as source code here

This ZIP includes the project documents and upstream repository references, not full copies of either Git repository. The GitHub hosts could not be reached from the file-generation environment. Clone each upstream repository from its official URL when setting up the project. This avoids shipping incomplete or stale source trees.

## Product goals

1. Discover businesses by niche, geography, and requested quantity.
2. Enrich each business using public, accessible information.
3. Separate verified facts from inferred opportunities and explicit buying-intent signals.
4. Calculate an overall lead-priority score and individual service-fit scores.
5. Generate evidence-specific outreach drafts.
6. Send approval cards to Telegram before outreach.
7. Dispatch only through channels that are technically supported and legally/platform eligible.
8. Detect replies, classify intent, stop follow-ups when required, and prepare suggested responses.
9. When a meeting is explicitly agreed and confirmed, create/update the Google Calendar event.
10. Keep a PostgreSQL source of truth and synchronize useful CRM fields to Google Sheets.

## Agency services

- Professional website development and redesign
- Real-estate property-listing websites and portals
- AI chatbots
- Business-process automation
- Automated lead management and customer follow-ups
- CRM and appointment-booking automation

## Core design principles

- Evidence before score; score before pitch.
- No fabricated problems, buying intent, contacts, or source URLs.
- A public phone number or email is not blanket consent for promotional messaging.
- A lead score never overrides channel eligibility, consent, opt-out, or platform rules.
- Human approval is required for initial campaign sends and AI-suggested replies.
- Every action is logged and idempotent; repeated webhook events must not create duplicate sends or calendar events.
- Return fewer qualified prospects rather than filling a quota with weak candidates.

## Repository contents

- `architecture.md` — components, data flow, scoring, workflows, safeguards, and rollout.
- `prompt.md` — system prompts and structured-output contracts for the AI stages.
- `github.md` — repository setup, source handling, branch conventions, and GitHub workflow.
- `SOURCES.md` — upstream repository roles, learning boundaries, and clone commands.

## Suggested implementation stack

- Orchestration: local n8n (user's current environment is Windows; n8n 2.39.6 was reported).
- Discovery: Go Google Maps Scraper REST API.
- Intelligence service: Python + FastAPI.
- Primary database: PostgreSQL.
- CRM/export: Google Sheets + CSV.
- User interface/control plane: Telegram bot with inline approval buttons.
- Calendar: Google Calendar API / OAuth.
- LLM: configurable existing model provider; no model training required.

## Quick start (high level)

1. Clone the primary Google Maps scraper repository.
2. Follow its current official setup guide and start its REST API/web UI.
3. Verify one small, permitted test query and inspect the returned JSON/CSV.
4. Create the IntentLead application services described in `architecture.md`.
5. Configure PostgreSQL, Telegram, Google Sheets, Google Calendar, and an LLM provider using environment variables and least-privilege credentials.
6. Import/build the n8n workflows in the order described in `architecture.md`.
7. Run the offline fixtures and end-to-end tests before enabling any live outreach.

Do not start with a 100-lead campaign. First validate 5–10 records and manually inspect the evidence.

## Important limitations

- Google Maps data is business discovery data; it does not prove buying intent.
- Website audits can identify visible gaps, but cannot prove hidden internal CRM or follow-up failures.
- Platform access, scraping, API terms, privacy law, and anti-spam rules vary by source and jurisdiction.
- Email delivery to an inbox cannot be guaranteed.
- Use official APIs or authorized integrations for dispatch and reply monitoring. Where automation is not permitted or supported, produce a draft for manual handling.
- Keep API keys and tokens out of Git, Telegram messages, prompts, and logs.
