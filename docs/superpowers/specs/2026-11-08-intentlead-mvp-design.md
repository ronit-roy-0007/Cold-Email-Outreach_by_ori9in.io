# IntentLead AI — Phase 0–2 MVP Design

Date: 2026-11-08
Status: approved for implementation planning
Scope: discovery, enrichment, deterministic scoring, dry-run drafts, operator web UI

## 1. Goal

Build the first working IntentLead AI application from the existing specification pack. The MVP must take an operator campaign request, discover businesses, audit public websites, store evidence, score leads deterministically, and present dry-run outreach drafts for human review.

This phase does **not** send messages, connect Telegram, sync Google Sheets, book calendar events, call an LLM, or run n8n.

Business objective context (not a product guarantee): support an agency offering websites, real-estate listing portals, AI chatbots, process automation, lead follow-up, and CRM/appointment automation.

## 2. Non-goals

- Live outreach of any kind (email, WhatsApp, SMS, social)
- Telegram bot, approval callbacks, or n8n workflows
- Google Sheets CRM sync
- Google Calendar meeting booking
- LLM-based extraction, scoring, or draft writing
- Bypassing logins, CAPTCHAs, paywalls, robots.txt, rate limits, or access controls
- Claiming live Google Maps scraping works until it has been tested against a real gosom service
- Any send/dispatch code path

## 3. Architecture

One FastAPI process serves both the operator UI and JSON APIs so the preview environment can expose a single port.

```mermaid
flowchart TD
    UI["Operator Web UI"] --> API["FastAPI Intelligence Service"]
    API --> PARSE["Campaign Parser"]
    PARSE --> CLIENT["Scraper Client"]
    CLIENT --> MOCK["In-process Mock Scraper"]
    CLIENT --> LIVE["External gosom API"]
    CLIENT --> IMPORT["CSV/JSON Import"]
    MOCK --> NORM["Normalize and Dedupe"]
    LIVE --> NORM
    IMPORT --> NORM
    NORM --> PG[("PostgreSQL")]
    PG --> AUDIT["Website Audit"]
    AUDIT --> EVID[("Evidence")]
    EVID --> SCORE["Deterministic Scorer"]
    SCORE --> LEADS[("Leads and Service Scores")]
    LEADS --> DRAFT["Dry-run Draft Generator"]
    DRAFT --> UI
```

Runtime rules:

- PostgreSQL is the default and production source of truth.
- The scraper client is independent of audit and scoring.
- Provider mode is explicit: `mock`, `import`, or `live`.
- Never silently substitute mock data when live scraping fails.
- Every business record stores `discovery_source` (`mock` | `import` | `live`) and the scrape job id.
- `OUTREACH_DRY_RUN` defaults to true and this MVP contains no send/dispatch code.
- Scoring arithmetic lives only in Python. The UI cannot edit numeric scores.

### 3.1 Process and ports

- FastAPI listens on `0.0.0.0:8000`.
- Operator UI: `/`
- JSON API: `/api/...`
- In-process mock scraper: `/scraper/...` (gosom-shaped REST)
- Health: `/health`

Provider selection is only `DISCOVERY_PROVIDER`. Do not infer mock mode from a missing base URL.

- `mock`: client calls in-process `/scraper`. `GOOGLE_MAPS_SCRAPER_BASE_URL` is ignored.
- `import`: no scraper call; operator upload required.
- `live`: client calls `GOOGLE_MAPS_SCRAPER_BASE_URL`. If that URL is missing, the job fails immediately with a configuration error. Never fall back to mock.

### 3.2 Preview reverse proxy

The operator UI is served by the same FastAPI process, so no separate frontend proxy is required. Browser JavaScript, if any, calls `/api` on the same origin.

## 4. Repository layout

Preserve existing root documents. Add application code under the structure already suggested in `github.md`.

```text
intentlead-ai/
├── README.md
├── architecture.md
├── prompt.md
├── github.md
├── SOURCES.md
├── .env.example
├── docker-compose.yml
├── start.sh
├── apps/intelligence-api/
│   ├── alembic/
│   ├── alembic.ini
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── api/
│   │   ├── services/
│   │   ├── scoring/
│   │   ├── providers/
│   │   └── web/
│   ├── tests/
│   └── requirements.txt
├── database/schema/
├── integrations/google-maps-scraper/
├── prompts/
├── tests/fixtures/
└── docs/superpowers/specs/
```

Keep modules small and independently testable:

| Module | Responsibility | Depends on |
|---|---|---|
| `providers.scraper_client` | Create/poll jobs, map provider JSON to normalized businesses | config, httpx |
| `providers.mock_scraper` | In-process gosom-shaped REST using fixtures | fixtures |
| `providers.import_loader` | CSV/JSON import | schemas |
| `services.campaigns` | Validate request, create campaign, start discovery | parser, scraper client |
| `services.identity` | Canonical `identity_key`, campaign-scoped lead uniqueness | models |
| `services.audit` | Public website inspection with SSRF, robots, and limits | evidence store |
| `scoring.engine` | Overall and service-fit scores from evidence IDs | evidence records |
| `services.drafts` | Template dry-run drafts from verified evidence | leads, evidence, agency config |
| `web` | Server-rendered operator pages | services |

## 5. Data model

MVP tables only. Later entities (`approvals`, `outbound_messages`, `inbound_messages`, `followup_tasks`, `meetings`, `calendar_events`, `channel_permissions`) are deferred.

Schema changes ship as Alembic migrations under `apps/intelligence-api/alembic/`. `Base.metadata.create_all()` is allowed only inside isolated tests. Application startup and docker-compose never call `create_all`.

### 5.1 Entities

- `campaigns` — niche, location, quantity, target services, filters, provider mode, dry_run, status
- `scrape_jobs` — provider, external_job_id, status, error, raw snapshot path/id, started/finished timestamps; unique per campaign
- `businesses` — normalized listing, original source fields JSON, discovery_source, scrape timestamps, `identity_key` (unique)
- `contacts` — public contact routes with source URL/scope; never treated as consent
- `evidence` — claim, evidence_type, source_url, checked_at, inspected_scope, confidence, excerpt, caveat
- `leads` — overall_score, priority, confidence, recommended_service, outreach_status=`draft`, crm_stage; unique `(campaign_id, business_id)`
- `dimension_scores` — one row per overall-score dimension per lead: points, max_points, evidence_ids, reason_code
- `service_scores` — one row per service per lead: points, evidence_ids, reason_code
- `message_drafts` — channel=`preview`, body or `draft_not_recommended`, evidence_ids, never sent
- `audit_log` — campaign/job/score/draft events; no secrets

### 5.2 Identity and deduplication

All primary keys are UUIDs.

One identity strategy, applied the same way in mock, import, and live, and across campaigns:

1. If the provider supplies a non-empty `place_id`, `identity_key = "place:" + strip(place_id)`.
2. Otherwise `identity_key = "nameaddr:" + sha256_hex(norm(name) + "|" + norm(address) + "|" + norm(locality))`.
   - `norm(s)` = Unicode NFKC, lower-case, collapse whitespace, strip punctuation except alphanumerics and spaces.
   - Website, phone, and email are **not** part of `identity_key`. They are attributes that may change.

Rules:

- `businesses.identity_key` is unique. A later listing with the same key updates source fields on the existing row; it does not insert a second business.
- `leads` has a unique constraint on `(campaign_id, business_id)`. Duplicate listings in one campaign do not create duplicate leads; the existing lead is reused and re-scored after audit.
- Across campaigns, reuse the business row and create a new lead for the new campaign. Re-audit rather than copy stale evidence.

### 5.3 Evidence contract

Every finding:

```json
{
  "claim": "No property search was visible on the inspected website pages",
  "evidence_type": "verified_observation",
  "source_url": "https://example.com/",
  "source_published_at": null,
  "checked_at": "2026-11-08T10:00:00Z",
  "inspected_scope": "homepage and navigation-linked pages inspected",
  "confidence": "medium",
  "supporting_excerpt": "",
  "caveat": "Absence on inspected pages is not proof the feature does not exist elsewhere"
}
```

Allowed `evidence_type` values: `verified_observation`, `inference`, `explicit_intent`.

Google Maps listing fields are discovery data. They may support suitability or contactability. They cannot create `explicit_intent` or buying-intent points.

Access failures, robots disallows, SSRF blocks, 401/403, CAPTCHA, and paywalls are stored as evidence of type `verified_observation` with a caveat that page content was not inspected. Those rows must not be treated as proof a feature is absent.

## 6. Discovery providers

### 6.1 Configuration

```dotenv
DISCOVERY_PROVIDER=mock
GOOGLE_MAPS_SCRAPER_BASE_URL=http://localhost:8000/scraper
GOOGLE_MAPS_SCRAPER_API_TOKEN=
```

`DISCOVERY_PROVIDER` is one of `mock`, `import`, `live`.

Rules:

- `mock` uses in-process fixtures and labels every record `discovery_source=mock`.
- `import` requires an uploaded CSV/JSON file. Records are labeled `import`.
- `live` calls the external gosom REST API. Records are labeled `live` only after a successful provider response.
- If live mode fails, the job status is `failed` with the error. The system must not fall back to mock data.
- UI and CSV export always show the discovery source.

### 6.2 Mock scraper API

Match a small, stable gosom-like surface so the client can switch later:

- `POST /scraper/jobs` — `{ query, location, limit, filters }` → `{ job_id, status }`
- `GET /scraper/jobs/{job_id}` — `{ status, results[] | error }`

Fixture set: at least 8 realistic Dallas-area real-estate agencies covering:

1. No website
2. Unreachable / HTTP error website
3. Simple brochure site, no listing search, no inquiry form
4. Site with listing search and contact form
5. Visible WhatsApp link, no chatbot
6. Visible booking/chat widget
7. Low rating / few reviews (suitability only; not buying intent)
8. Explicit public hiring/request snippet in supplied page HTML (only this may earn buying-intent points)

Include at least one duplicate pair (same `place_id`, different payload) to prove campaign-scoped lead uniqueness.

### 6.3 Live client

Typed httpx client with timeout, bounded retries on 502/503/429, pagination if the upstream job returns pages, and raw JSON snapshot stored on the scrape job. Do not claim this path is operational until a real scraper is tested.

### 6.4 Import

Accept CSV/JSON with columns/keys: `name`, `category`, `address`, `city`, `website`, `phone`, `email`, `rating`, `review_count`, `place_id` (optional). Missing required `name` + location fields reject the row with an error list; valid rows still import.

## 7. Campaign request parsing

Parse operator form fields in application code, not with an LLM.

Required:

- `niche`
- `location`
- `requested_quantity` (positive integer, MVP max 25)
- `target_services` (non-empty subset of the seven agency services)

Optional filters: `include_website`, `minimum_rating`, `minimum_review_count`, `radius`, `notes`.

Always set `dry_run=true`. Do not infer that the operator wants messages sent.

Invalid input returns field errors to the UI. Do not invent missing values.

## 8. Website audit

Use only publicly reachable http/https URLs from the listing or import. Mock-provider audits read local fixture HTML through an internal fixture loader, never through `file://` or operator-supplied paths.

### 8.1 Hard limits

| Limit | Value |
|---|---|
| Max pages per business | 5 including the homepage |
| Max response bytes | 1_048_576 (1 MiB); truncate and stop parsing |
| Connect timeout | 5 seconds |
| Read timeout | 10 seconds |
| Per-host concurrent requests | 1 |
| Max redirects | 3 |
| Allowed schemes | `http`, `https` |
| Allowed ports | 80, 443 |
| Allowed content types | `text/html`, `application/xhtml+xml`; charset optional. Other types are recorded as skipped, not parsed |

Exceeding a limit stores evidence of the skip and stops further fetches for that business.

### 8.2 SSRF protection

Before every request, including every redirect:

1. Parse the URL. Reject credentials in the userinfo component, non-http(s) schemes, and ports other than 80/443.
2. Resolve the hostname with the system resolver. If resolution fails, record `dns_failure` and do not connect.
3. Reject the connection if **any** resolved address is not a globally routable unicast address. Block at least:
   - IPv4: 0.0.0.0/8, 10.0.0.0/8, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10, 192.0.0.0/24, 192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24, 224.0.0.0/4, 240.0.0.0/4, 255.255.255.255/32
   - IPv6: ::/128, ::1/128, fc00::/7, fe80::/10, ff00::/8, 2001:db8::/32, IPv4-mapped addresses that decode to a blocked IPv4 range
   - Cloud metadata hostnames and IPs, including `169.254.169.254`, `fd00:ec2::254`, `metadata.google.internal`, `metadata.google.com`
4. Connect only to an allowed resolved address (do not let the HTTP client re-resolve independently if that would skip the check).
5. On redirect, repeat steps 1–4 on the Location URL. A blocked redirect is an access failure, not a page audit.

DNS rebinding: the address used for the TCP connection must be the address that passed the blocklist for that fetch. Do not follow a hostname to a newly resolved private address after an earlier public lookup.

Literal IP URLs are subject to the same blocklist.

### 8.3 Robots and access restrictions

- Fetch `/robots.txt` for the origin first (also subject to SSRF and limits). If it cannot be fetched, treat robots as unknown and continue with the page fetch; record `robots_unknown`.
- Honor `Disallow` for a conservative user-agent (`IntentLeadBot`). Do not fetch disallowed paths. Record `robots_disallow`.
- On HTTP 401, 403, or 407: stop. Record `access_restricted`. Do not retry with different headers, cookies, or credentials.
- If the response body or headers indicate a CAPTCHA, challenge page, or paywall: stop. Record `challenge_or_paywall`. Never attempt to solve or bypass.
- Do not send cookies, stored sessions, or Authorization headers to audited sites.

### 8.4 What to inspect when a page is allowed and HTML

- HTTP status and redirect target
- Mobile viewport / responsive meta evidence
- Title, nav, service copy
- Property listing/search/filter controls
- Inquiry forms and CTAs
- Visible WhatsApp/contact links
- Visible chatbot or booking widget

Rules:

- If a URL is inaccessible, blocked, or disallowed, store that access result. Do not infer page contents and do not apply absence-of-feature scoring rules for uninspected pages.
- An absent feature on inspected pages is an observation about inspected scope, not proof the business has no such feature anywhere.
- Do not store full HTML in PostgreSQL. Short excerpts only. Optional raw snapshots may go under gitignored `data/`.
- Do not follow login, CAPTCHA, or paywall challenges.

## 9. Scoring

The application calculates all numbers. No UI or prompt may override them.

Three independent outputs:

| Output | Meaning | Must not mean |
|---|---|---|
| Overall score 0–100 | Prioritization of prospect **opportunity** given current evidence | Probability of closing, budget, or intent to buy |
| Service-fit scores 0–100 | Opportunity **for that service**, independently | That the business will buy that service |
| Confidence high/medium/low | Reliability of the evidence set | A modifier of the numeric scores |

They are stored separately and never mixed. A high overall score with low confidence is allowed. A high service-fit with overall D is allowed.

### 9.1 Traceability

Every dimension score and every service-fit score stores:

- `points`
- `max_points` (dimensions only)
- `evidence_ids` (list of evidence row UUIDs; empty only when reason_code is `unknown_not_inspected` or `unknown_no_listing_fields`, and then a dedicated evidence or reason row still explains the zero)
- `reason_code` (stable string, e.g. `no_website_url`, `robots_disallow`, `unknown_not_inspected`, `explicit_intent_present`)

Do not award opportunity points merely because a field is missing, except where a rule below **explicitly** scores a documented absence (for example, listing website URL empty after a successful scrape). If the audit did not inspect the site (SSRF, robots, 401/403, CAPTCHA, paywall, timeout without a listing-level absence), that dimension or service-fit component is **0** with `reason_code=unknown_not_inspected`.

### 9.2 Overall score (0–100)

| Dimension | Max |
|---|---:|
| website_opportunity | 25 |
| lead_capture_opportunity | 20 |
| automation_opportunity | 20 |
| business_suitability | 15 |
| buying_intent_evidence | 15 |
| contactability | 5 |

Priority bands: A 80–100, B 65–79, C 45–64, D below 45. Bands are operational filters, not predicted close rates.

Scoring rules:

- Each dimension is 0 to its max, summed.
- Unknown / not inspected → 0 for that dimension, with reason and evidence of the skip when available.
- Buying-intent points require `explicit_intent` with a source URL. Maps data alone scores 0 on this dimension.
- Score is a prioritization heuristic, not a close probability.

Deterministic mapping. Apply the first matching rule in each list. Points never exceed the dimension max.

**website_opportunity** (max 25)

- Listing website URL empty after successful scrape: 25 (`no_website_url`)
- URL present but unreachable / timeout / HTTP 4xx–5xx (not 401/403): 22 (`website_unreachable`)
- 401/403/robots/CAPTCHA/paywall/SSRF: 0 (`unknown_not_inspected`)
- Reachable, no mobile viewport meta, and thin or missing service content: 16 (`thin_unresponsive_site`)
- Reachable real-estate niche site with no listing search/filter on inspected pages: 12 (`missing_listing_search`)
- Reachable site with listing search and adequate service content: 4 (`listing_capable_site`)
- Else if reachable HTML inspected: 8 (`reachable_other`)
- Else: 0 (`unknown_not_inspected`)

**lead_capture_opportunity** (max 20)

- Listing website URL empty after successful scrape: 18 (`no_website_url`)
- URL present but unreachable / timeout / HTTP 4xx–5xx (not 401/403): 18 (`website_unreachable`)
- 401/403/robots/CAPTCHA/paywall/SSRF: 0 (`unknown_not_inspected`)
- Reachable, no form, no CTA, no phone/email/WhatsApp on inspected pages: 20 (`no_inquiry_path`)
- Reachable, phone/email/WhatsApp only, no form and no booking CTA: 12 (`contact_only`)
- Form present but action missing or submission URL returns 4xx/5xx: 14 (`broken_form`)
- Working inquiry form or clear booking CTA: 4 (`working_capture`)
- Else: 0 (`unknown_not_inspected`)

**automation_opportunity** (max 20)

- Two or more supplied public review excerpts complaining about slow response, missed follow-up, or booking friction: 16 (`public_process_friction`)
- Site not inspected: 0 (`unknown_not_inspected`)
- No chatbot and no booking widget on inspected pages: 8 (`no_visible_chat_or_booking`, evidence_type=`inference`, caveat required)
- Chatbot or booking widget visible, but not both: 2 (`partial_automation_visible`)
- Both chatbot and booking widget visible: 0 (`automation_already_visible`)
- Else: 0 (`unknown_not_inspected`)
- Do not infer internal CRM failure from absence

**business_suitability** (max 15)

- Category matches campaign niche and listing is open/active with a location: 15 (`niche_active`)
- Category matches but listing status is closed: 3 (`niche_closed`)
- Category unrelated to campaign niche: 0 (`unrelated_category`)
- Else (insufficient listing fields): 6 (`insufficient_listing_fields`)

**buying_intent_evidence** (max 15)

- One `explicit_intent` evidence row with source_url: 15 (`explicit_intent_present`)
- Otherwise: 0 (`no_explicit_intent`)

**contactability** (max 5)

- Public email with source: 5 (`public_email`)
- Else public phone with source: 4 (`public_phone`)
- Else website contact path with source: 3 (`website_contact_path`)
- Else: 0 (`no_public_contact`)
- Public contact is not consent

**confidence** (independent of score)

- `high`: at least two `verified_observation` rows with source_url from the current audit
- `medium`: one `verified_observation` with source_url
- `low`: otherwise

### 9.3 Service-fit scores (0–100 each)

Independent scores. Start at 0, apply matching adds, cap at 100. Each add cites evidence_ids.

- `website_development`: +70 if listing website URL empty; +50 if URL unreachable; else 0. Uninspected restricted sites: 0 (`unknown_not_inspected`).
- `website_redesign`: +40 if reachable with no mobile viewport; +30 if thin service content; +20 if no listing search on a real-estate niche site; 0 if no/unreachable website (development owns that case); 0 if uninspected.
- `real_estate_listing_portal`: +80 if real-estate niche and no listing search/filter on inspected pages; +20 if listing search exists; 0 if niche is not real-estate; 0 if uninspected.
- `ai_chatbot`: +55 if reachable inspected site and no chatbot on inspected pages; +10 if a chatbot widget is visible (see 9.4); 0 if uninspected.
- `business_process_automation`: +40 if automation_opportunity reason is `public_process_friction`; +20 if reason is `no_visible_chat_or_booking`; else 0.
- `lead_management_followup`: +50 if inspected and no working form and no booking CTA; +25 if form exists but chatbot/booking absent; 0 if uninspected.
- `crm_appointment_automation`: +60 if inspected and no booking widget; +15 if a booking widget is visible (see 9.4); 0 if uninspected.

`recommended_service` is the highest service-fit score among the campaign's `target_services`, minimum 40. Below that, recommended_service is null and draft generation returns `draft_not_recommended`. Ties pick the first service in the list above.

### 9.4 Residual points when a chatbot or booking widget is already visible

A visible chatbot may still receive `ai_chatbot = 10`. A visible booking widget may still receive `crm_appointment_automation = 15`.

These residual points mean only: the agency could still offer integration, replacement, or multi-channel automation around a tool that already exists. They are **not**:

- a claim the business lacks a chatbot or booking flow
- buying intent
- a close probability
- permission to write a draft that says the business has no chatbot or no booking

Drafts must mention a verified gap, not a residual enhancement score. If the only service above threshold is a residual-only score and no verified gap exists, return `draft_not_recommended`.

## 10. Dry-run drafts

Template generator, not an LLM.

Agency identity is configuration, never invented:

```dotenv
AGENCY_NAME=
AGENCY_SENDER_NAME=
```

Both must be non-empty operator-supplied values. `.env.example` leaves them blank. Do not ship a fictional person or agency name as a default.

If either is empty, do not generate a message body. Store `draft_not_recommended` with reason `agency_identity_not_configured`. Never fill in a guessed sender.

When identity is configured and a draft is allowed:

- Identify the sender using only `AGENCY_SENDER_NAME` at `AGENCY_NAME`.
- Mention one specific verified observation with its source scope and evidence id.
- One relevant service offer, matching `recommended_service`.
- One low-pressure CTA.
- No fabricated portfolio, results, prices, or internal process claims.
- No send. Persist as `message_drafts.status=preview`.

If evidence is insufficient, recommended_service is null, or the only fit is residual (section 9.4), store `draft_not_recommended` and a reason. The UI must not show a send control.

## 11. Operator web UI

Server-rendered HTML (Jinja2 + a small amount of CSS). No separate Node frontend in this phase.

Pages:

1. **Home / New Campaign** — form for niche, location, quantity, services, filters, provider mode
2. **Jobs** — campaign/job status, provider, counts, errors
3. **Leads** — table with name, location, overall score, priority, recommended service, discovery source, confidence
4. **Lead detail** — listing fields, evidence list, score breakdown with evidence ids and reason codes, service-fit bars, draft or `draft_not_recommended`
5. **Export** — CSV of selected campaign leads

UI rules:

- Persistent banner: `Dry-run mode. Outreach is disabled.`
- Show discovery source on every lead.
- Filter leads by priority band and campaign.
- No Approve & Send button.
- Empty and error states must be explicit (failed live scrape, inaccessible website, insufficient evidence, agency identity not configured).

## 12. API surface

- `POST /api/campaigns` — create and start
- `GET /api/campaigns` — list
- `GET /api/campaigns/{id}` — detail + job status
- `POST /api/campaigns/{id}/import` — CSV/JSON when provider=`import`
- `GET /api/leads?campaign_id=&priority=`
- `GET /api/leads/{id}` — lead, evidence, dimension_scores, service_scores, draft
- `GET /api/campaigns/{id}/export.csv`
- `GET /health`

All mutating endpoints are idempotent where retries are likely. One scrape job per campaign.

## 13. Database configuration

PostgreSQL is the default and the production source of truth.

```dotenv
APP_ENV=development
DATABASE_URL=postgresql://intentlead:change-me@localhost:5432/intentlead
```

Rules:

- Application startup runs Alembic migrations, then serves traffic. It never calls `create_all`.
- If `DATABASE_URL` is a PostgreSQL URL and the server is unreachable, **abort**. Do not switch to SQLite.
- SQLite is permitted only when `APP_ENV=development` **and** `DATABASE_URL` uses the `sqlite:` scheme. On that path, print a visible startup warning to stderr and the log: `WARNING: Using SQLite because APP_ENV=development and DATABASE_URL is sqlite. PostgreSQL is the production source of truth.`
- If `APP_ENV` is not `development` and `DATABASE_URL` is sqlite, abort.
- Isolated pytest runs may use in-memory SQLite with `create_all` or test-only Alembic. That path is not a runtime fallback.

docker-compose runs PostgreSQL. README documents Postgres as default and the explicit sqlite URL as a dev-only option.

## 14. Configuration

Extend `.env.example` with placeholders only. User-project LLM variables are reserved but unused:

```dotenv
APP_ENV=development
LOG_LEVEL=INFO
DATABASE_URL=postgresql://intentlead:change-me@localhost:5432/intentlead
DISCOVERY_PROVIDER=mock
GOOGLE_MAPS_SCRAPER_BASE_URL=http://localhost:8000/scraper
GOOGLE_MAPS_SCRAPER_API_TOKEN=
AGENCY_NAME=
AGENCY_SENDER_NAME=
OUTREACH_DRY_RUN=true
USER_LLM_API_KEY=
USER_LLM_BASE_URL=
USER_LLM_MODEL=
```

Do not read agent-runtime LLM keys. Do not hardcode secrets. Do not default `AGENCY_SENDER_NAME` to a fictional identity.

## 15. Error handling and reliability

- Timeouts on all outbound HTTP.
- Bounded retries with exponential backoff for transient scraper errors only.
- Failed jobs go to `failed` and appear in the Jobs UI; they are not retried into a different provider.
- Deduplicate businesses before audit.
- Audit one host conservatively; skip remaining pages on robots/401/403/CAPTCHA/paywall/SSRF and record the access result.
- Structured logs without tokens, raw credentials, or unnecessary personal data.
- Health endpoint checks DB connectivity.

## 16. Testing

Must have automated tests before claiming the MVP works:

- Campaign parser rejects missing niche/location/quantity/services
- Dedupe merges same `place_id` and same normalized name+address+locality
- Duplicate listings in one campaign create one lead
- Scoring fixtures for the eight mock businesses; golden expected scores
- Buying-intent remains 0 without `explicit_intent`
- Maps-only record cannot produce buying-intent points
- Inaccessible website stores access-failure evidence, not invented content
- SSRF: localhost, RFC1918, link-local, and metadata IPs are blocked, including after redirect
- robots.txt disallow is honored; 401/403/CAPTCHA/paywall stop the audit
- Audit limits: page cap, byte cap, content-type skip
- Live provider failure does not insert mock businesses
- Postgres unreachable does not switch to SQLite
- SQLite is rejected when `APP_ENV` is not development
- Dry-run draft never sets a sent status
- Blank agency identity yields `draft_not_recommended`, not a fake name
- Visible chatbot does not produce a draft claiming they have no chatbot
- CSV export includes discovery_source, reason codes, and evidence-backed scores
- `recommended_service` respects campaign target_services and threshold
- Every dimension_score and service_score has reason_code and evidence_ids or an explicit unknown reason

Fixture HTML lives in `tests/fixtures/` so audits are hermetic.

## 17. Rollout inside this MVP

Implementation order:

1. Config, models, Alembic, health, database policy
2. Identity/dedupe + mock scraper + client
3. Campaign API + job polling
4. Website audit with SSRF, robots, limits, evidence persistence
5. Deterministic scoring + service fit + traceability
6. Dry-run drafts with configurable identity
7. Operator UI + CSV export
8. docker-compose / start script / README including Windows PowerShell

## 18. Acceptance criteria

The Phase 0–2 MVP is done when:

- An operator can create a mock campaign from the web UI
- The mock scraper returns structured businesses labeled `mock`
- Duplicates are consolidated to one business and one lead per campaign
- Each score dimension traces to evidence IDs or a declared unknown/zero reason
- Verified observations, inferences, and explicit intent are stored distinctly
- Service-fit scores are deterministic and covered by tests
- Insufficient evidence yields `draft_not_recommended` / no recommended service
- The UI has no send control and dry-run is visible
- Live mode errors are visible and do not swap in mock data
- Website audit cannot reach private or metadata addresses
- robots.txt and access restrictions are respected
- Schema is created via Alembic, not runtime `create_all`
- PostgreSQL is default; SQLite is explicit, development-only, and warned
- CSV export works
- No Telegram, n8n, Sheets, Calendar, LLM, or dispatch code ships in this phase

## 19. Deferred to later phases

- Telegram commands and approval cards
- Channel eligibility gates and authorized dispatch
- Reply classification and follow-ups
- Google Calendar
- Google Sheets sync
- Optional LLM adapters behind `USER_LLM_*`
- n8n orchestration
)
