# IntentLead AI Phase 0–2 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Ship a dry-run IntentLead operator app that discovers businesses (mock/import/live client), audits public sites with SSRF and robots protections, scores leads deterministically with evidence IDs, and shows preview drafts — no Telegram, n8n, Sheets, Calendar, LLM, or send path.

**Architecture:** One FastAPI process on port 8000 serves Jinja2 UI at `/` and JSON at `/api`. PostgreSQL is the source of truth via Alembic. A gosom-shaped mock scraper lives at `/scraper`. Website audit, scoring, and drafts are pure Python modules with tests first.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Jinja2, httpx, pytest, docker-compose.

## Global Constraints

- Phase 0–2 only: no Telegram, n8n, Google Sheets, Google Calendar, LLM calls, or live message dispatch.
- `OUTREACH_DRY_RUN` is always treated as true; no send/dispatch module exists.
- Scoring arithmetic lives only in Python; UI cannot edit scores.
- `DISCOVERY_PROVIDER` is `mock` | `import` | `live`. Live failure never falls back to mock.
- PostgreSQL is default and production. SQLite only when `APP_ENV=development` and `DATABASE_URL` starts with `sqlite:`; abort otherwise. Never silently switch databases.
- Schema changes via Alembic. `create_all` only in isolated tests.
- Agency identity (`AGENCY_NAME`, `AGENCY_SENDER_NAME`) has empty defaults; never invent a sender.
- Website audit: SSRF blocklist, robots.txt, 401/403/CAPTCHA/paywall stop, max 5 pages, 1 MiB, connect 5s, read 10s, 1 inflight per host, 3 redirects, html content-types only.
- Identity: `place:{place_id}` else `nameaddr:{sha256(norm(name)|norm(address)|norm(locality))}`. Unique `businesses.identity_key`. Unique `leads(campaign_id, business_id)`.
- Overall score = opportunity. Service-fit = per-service opportunity. Confidence = evidence reliability. Independent. Not close probability.
- Every dimension_score and service_score stores `reason_code` and `evidence_ids` (or explicit unknown reason).
- Do not read agent-runtime LLM keys. Use `USER_LLM_*` placeholders only, unused.
- Commits use conventional messages. Do not commit secrets.

### File map

Create:

- `apps/intelligence-api/requirements.txt`
- `apps/intelligence-api/alembic.ini`
- `apps/intelligence-api/alembic/env.py`
- `apps/intelligence-api/alembic/script.py.mako`
- `apps/intelligence-api/alembic/versions/0001_initial.py`
- `apps/intelligence-api/app/__init__.py`
- `apps/intelligence-api/app/config.py`
- `apps/intelligence-api/app/db.py`
- `apps/intelligence-api/app/models.py`
- `apps/intelligence-api/app/schemas.py`
- `apps/intelligence-api/app/main.py`
- `apps/intelligence-api/app/identity.py`
- `apps/intelligence-api/app/providers/__init__.py`
- `apps/intelligence-api/app/providers/types.py`
- `apps/intelligence-api/app/providers/mock_scraper.py`
- `apps/intelligence-api/app/providers/scraper_client.py`
- `apps/intelligence-api/app/providers/import_loader.py`
- `apps/intelligence-api/app/services/campaigns.py`
- `apps/intelligence-api/app/services/pipeline.py`
- `apps/intelligence-api/app/services/audit.py`
- `apps/intelligence-api/app/services/ssrf.py`
- `apps/intelligence-api/app/services/robots.py`
- `apps/intelligence-api/app/services/drafts.py`
- `apps/intelligence-api/app/scoring/engine.py`
- `apps/intelligence-api/app/scoring/reasons.py`
- `apps/intelligence-api/app/api/campaigns.py`
- `apps/intelligence-api/app/api/leads.py`
- `apps/intelligence-api/app/web/routes.py`
- `apps/intelligence-api/app/web/templates/*.html`
- `apps/intelligence-api/tests/conftest.py`
- `apps/intelligence-api/tests/test_config_db.py`
- `apps/intelligence-api/tests/test_identity.py`
- `apps/intelligence-api/tests/test_parser.py`
- `apps/intelligence-api/tests/test_mock_scraper.py`
- `apps/intelligence-api/tests/test_scraper_client.py`
- `apps/intelligence-api/tests/test_import_loader.py`
- `apps/intelligence-api/tests/test_ssrf.py`
- `apps/intelligence-api/tests/test_robots.py`
- `apps/intelligence-api/tests/test_audit.py`
- `apps/intelligence-api/tests/test_scoring.py`
- `apps/intelligence-api/tests/test_drafts.py`
- `apps/intelligence-api/tests/test_pipeline.py`
- `apps/intelligence-api/tests/test_api.py`
- `tests/fixtures/businesses.json`
- `tests/fixtures/sites/*.html`
- `docker-compose.yml`
- `start.sh`
- `start.ps1`

Modify:

- `.env.example`
- `README.md`

---

### Task 1: Config, database policy, Alembic models

**Files:**
- Create: `apps/intelligence-api/requirements.txt`
- Create: `apps/intelligence-api/app/__init__.py`
- Create: `apps/intelligence-api/app/config.py`
- Create: `apps/intelligence-api/app/db.py`
- Create: `apps/intelligence-api/app/models.py`
- Create: `apps/intelligence-api/alembic.ini`
- Create: `apps/intelligence-api/alembic/env.py`
- Create: `apps/intelligence-api/alembic/script.py.mako`
- Create: `apps/intelligence-api/alembic/versions/0001_initial.py`
- Create: `apps/intelligence-api/tests/conftest.py`
- Create: `apps/intelligence-api/tests/test_config_db.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: nothing
- Produces: `Settings` from `get_settings()`; `resolve_database_url(settings) -> str` that may raise `DatabaseConfigError`; SQLAlchemy models listed below; Alembic revision `0001_initial`

- [x] **Step 1: Write the failing tests**

```python
# apps/intelligence-api/tests/test_config_db.py
import os
import pytest
from app.config import Settings, DatabaseConfigError, resolve_database_url, SQLITE_WARNING


def test_postgres_url_unchanged_in_development():
    s = Settings(APP_ENV="development", DATABASE_URL="postgresql://intentlead:x@localhost:5432/intentlead")
    assert resolve_database_url(s) == s.DATABASE_URL


def test_sqlite_allowed_only_in_development(capsys):
    s = Settings(APP_ENV="development", DATABASE_URL="sqlite:///./data/dev.db")
    assert resolve_database_url(s).startswith("sqlite:")
    err = capsys.readouterr().err
    assert "WARNING: Using SQLite" in err
    assert "PostgreSQL is the production source of truth" in err


def test_sqlite_rejected_when_not_development():
    s = Settings(APP_ENV="production", DATABASE_URL="sqlite:///./data/dev.db")
    with pytest.raises(DatabaseConfigError, match="SQLite"):
        resolve_database_url(s)


def test_agency_identity_defaults_empty():
    s = Settings()
    assert s.AGENCY_NAME == ""
    assert s.AGENCY_SENDER_NAME == ""


def test_outreach_dry_run_defaults_true():
    s = Settings()
    assert s.OUTREACH_DRY_RUN is True
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd apps/intelligence-api && pip install --break-system-packages pytest pydantic-settings && PYTHONPATH=. pytest tests/test_config_db.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`

- [x] **Step 3: Write requirements, settings, models, Alembic**

`apps/intelligence-api/requirements.txt`:

```text
fastapi==0.115.6
uvicorn==0.32.1
sqlalchemy==2.0.36
alembic==1.14.0
psycopg==3.2.3
psycopg[binary]==3.2.3
pydantic==2.10.3
pydantic-settings==2.6.1
httpx==0.28.1
jinja2==3.1.4
python-multipart==0.0.19
pytest==8.3.4
```

`app/config.py` must:

- Load env with `pydantic-settings`, `env_file=".env"` optional
- Fields: `APP_ENV` default `"development"`, `LOG_LEVEL`, `DATABASE_URL` default postgres URL from spec, `DISCOVERY_PROVIDER` default `"mock"`, `GOOGLE_MAPS_SCRAPER_BASE_URL` default `""`, `GOOGLE_MAPS_SCRAPER_API_TOKEN` default `""`, `AGENCY_NAME=""`, `AGENCY_SENDER_NAME=""`, `OUTREACH_DRY_RUN=True`, `USER_LLM_API_KEY=""`, `USER_LLM_BASE_URL=""`, `USER_LLM_MODEL=""`
- `resolve_database_url`: if url scheme is sqlite and APP_ENV != development → raise; if sqlite and development → print `SQLITE_WARNING` to stderr and return url; else return url unchanged. Never rewrite a postgres URL to sqlite.

`app/models.py` SQLAlchemy 2 models:

- `Campaign`: id UUID pk, niche, location, requested_quantity, target_services JSON, filters JSON, provider, dry_run bool default True, status, created_at
- `ScrapeJob`: id UUID pk, campaign_id FK unique, provider, external_job_id, status, error, raw_snapshot JSON nullable, started_at, finished_at
- `Business`: id UUID pk, identity_key unique, place_id nullable, name, category, address, locality, website, phone, email, rating, review_count, listing_status, source_fields JSON, discovery_source, scrape_job_id FK nullable
- `Contact`: id UUID pk, business_id FK, kind, value, source_url, source_scope
- `Evidence`: id UUID pk, business_id FK, campaign_id FK, claim, evidence_type, source_url, source_published_at, checked_at, inspected_scope, confidence, supporting_excerpt, caveat
- `Lead`: id UUID pk, campaign_id FK, business_id FK, overall_score int, priority, confidence, recommended_service nullable, outreach_status default `"draft"`, crm_stage, UniqueConstraint campaign_id+business_id
- `DimensionScore`: id UUID pk, lead_id FK, dimension, points, max_points, evidence_ids JSON, reason_code
- `ServiceScore`: id UUID pk, lead_id FK, service, points, evidence_ids JSON, reason_code
- `MessageDraft`: id UUID pk, lead_id FK, channel default `"preview"`, status default `"preview"`, body nullable, not_recommended_reason nullable, evidence_ids JSON
- `AuditLog`: id UUID pk, created_at, action, entity_type, entity_id, payload JSON

`app/db.py`: engine from `resolve_database_url`, session factory. No `create_all` here.

Alembic `0001_initial` creates all tables and unique indexes. `env.py` imports `app.models.Base` and uses `DATABASE_URL` from settings.

`.env.example` match spec section 14 (blank agency names).

`tests/conftest.py`: set `APP_ENV=development`, `DATABASE_URL=sqlite:///:memory:`, create engine, `Base.metadata.create_all` **only in this fixture**, yield Session, drop_all.

- [x] **Step 4: Run tests**

Run: `cd apps/intelligence-api && pip install --break-system-packages -r requirements.txt && PYTHONPATH=. pytest tests/test_config_db.py -v`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add .env.example apps/intelligence-api
git commit -m "feat: add settings, models, and Alembic database policy"
```

---

### Task 2: Identity keys and campaign-scoped lead uniqueness

**Files:**
- Create: `apps/intelligence-api/app/identity.py`
- Create: `apps/intelligence-api/tests/test_identity.py`

**Interfaces:**
- Consumes: `Business`, `Lead` models
- Produces: `normalize_identity_part(value: str) -> str`; `identity_key(*, place_id: str | None, name: str, address: str, locality: str) -> str`; `upsert_business(session, listing: NormalizedListing, scrape_job_id) -> Business`; `get_or_create_lead(session, campaign_id, business_id) -> Lead`

- [x] **Step 1: Write the failing test**

```python
# apps/intelligence-api/tests/test_identity.py
from app.identity import identity_key, normalize_identity_part


def test_place_id_preferred():
    a = identity_key(place_id="ChIJabc", name="Acme", address="1 Main", locality="Dallas")
    b = identity_key(place_id="ChIJabc", name="ACME REALTY", address="other", locality="Austin")
    assert a == b == "place:ChIJabc"


def test_nameaddr_hash_is_stable_under_punctuation_and_case():
    a = identity_key(place_id=None, name="Acme Realty!", address="100 Main St.", locality="Dallas, TX")
    b = identity_key(place_id=None, name="acme realty", address="100 main st", locality="dallas tx")
    assert a == b
    assert a.startswith("nameaddr:")


def test_website_not_in_key():
    a = identity_key(place_id=None, name="Acme", address="1 Main", locality="Dallas")
    b = identity_key(place_id=None, name="Acme", address="1 Main", locality="Dallas")
    assert a == b
```

Add session tests in the same file using the conftest db:

```python
def test_duplicate_place_id_one_business_one_lead_per_campaign(db):
    from app.identity import upsert_business, get_or_create_lead
    from app.models import Campaign, Lead, Business
    from app.providers.types import NormalizedListing
    campaign = Campaign(niche="Real Estate Agencies", location="Dallas, Texas", requested_quantity=10, target_services=["website_redesign"], filters={}, provider="mock", dry_run=True, status="running")
    db.add(campaign)
    db.flush()
    listing = NormalizedListing(place_id="ChIJ1", name="Acme", category="Real estate agency", address="1 Main", locality="Dallas", website=None, phone=None, email=None, rating=4.1, review_count=10, listing_status="open", source_fields={}, discovery_source="mock")
    b1 = upsert_business(db, listing, scrape_job_id=None)
    listing2 = listing.model_copy(update={"website": "https://example.com"})
    b2 = upsert_business(db, listing2, scrape_job_id=None)
    assert b1.id == b2.id
    l1 = get_or_create_lead(db, campaign.id, b1.id)
    l2 = get_or_create_lead(db, campaign.id, b1.id)
    assert l1.id == l2.id
    assert db.query(Lead).filter_by(campaign_id=campaign.id).count() == 1
    assert db.query(Business).count() == 1
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd apps/intelligence-api && PYTHONPATH=. pytest tests/test_identity.py -v`

Expected: FAIL `ModuleNotFoundError: No module named 'app.identity'`

- [x] **Step 3: Implement identity**

`normalize_identity_part`: NFKC, lower, replace punctuation with space, collapse whitespace, strip.

`identity_key`: if `place_id` stripped non-empty → `"place:" + stripped`; else `"nameaddr:" + sha256_hex(norm(name)+"|"+norm(address)+"|"+norm(locality))`.

`upsert_business`: select by identity_key; insert or update attributes; return row.

`get_or_create_lead`: select by campaign_id+business_id; insert with overall_score=0, priority="D", confidence="low", outreach_status="draft", crm_stage="discovered" if missing.

Define `NormalizedListing` pydantic model in `app/providers/types.py` with the fields used above plus `reviews: list[str] = []`.

- [x] **Step 4: Run tests**

Run: `cd apps/intelligence-api && PYTHONPATH=. pytest tests/test_identity.py tests/test_config_db.py -v`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add apps/intelligence-api
git commit -m "feat: add stable business identity and campaign-scoped lead uniqueness"
```

---

### Task 3: Campaign parser

**Files:**
- Create: `apps/intelligence-api/app/services/parser.py`
- Create: `apps/intelligence-api/app/schemas.py`
- Create: `apps/intelligence-api/tests/test_parser.py`

**Interfaces:**
- Consumes: nothing
- Produces: `SERVICES = ("website_development", "website_redesign", "real_estate_listing_portal", "ai_chatbot", "business_process_automation", "lead_management_followup", "crm_appointment_automation")`; `parse_campaign(payload: dict) -> CampaignInput | ParseError`

- [x] **Step 1: Write the failing test**

```python
from app.services.parser import parse_campaign, ParseError

def test_rejects_missing_required():
    err = parse_campaign({})
    assert isinstance(err, ParseError)
    assert "niche" in err.fields
    assert "location" in err.fields
    assert "requested_quantity" in err.fields
    assert "target_services" in err.fields

def test_quantity_bounds():
    err = parse_campaign({"niche": "n", "location": "Dallas, Texas", "requested_quantity": 0, "target_services": ["ai_chatbot"]})
    assert isinstance(err, ParseError)
    ok = parse_campaign({"niche": "n", "location": "Dallas, Texas", "requested_quantity": 10, "target_services": ["ai_chatbot"]})
    assert ok.dry_run is True
    assert ok.requested_quantity == 10

def test_quantity_max_25():
    err = parse_campaign({"niche": "n", "location": "Dallas, Texas", "requested_quantity": 26, "target_services": ["ai_chatbot"]})
    assert isinstance(err, ParseError)

def test_does_not_invent_services():
    err = parse_campaign({"niche": "n", "location": "Dallas, Texas", "requested_quantity": 5, "target_services": ["seo"]})
    assert isinstance(err, ParseError)

def test_always_dry_run():
    ok = parse_campaign({"niche": "n", "location": "Dallas, Texas", "requested_quantity": 5, "target_services": ["website_redesign"], "dry_run": False})
    assert ok.dry_run is True
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd apps/intelligence-api && PYTHONPATH=. pytest tests/test_parser.py -v`

Expected: FAIL missing module

- [x] **Step 3: Implement parser**

Required: niche non-empty str, location non-empty str, requested_quantity int 1..25, target_services non-empty subset of SERVICES. Optional filters dict. Always `dry_run=True`. Unknown service names → ParseError. Do not default missing required fields.

- [x] **Step 4: Run tests**

Run: `cd apps/intelligence-api && PYTHONPATH=. pytest tests/test_parser.py -v`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add apps/intelligence-api
git commit -m "feat: add campaign request parser with dry-run default"
```

---

### Task 4: Mock scraper, fixtures, and typed client

**Files:**
- Create: `tests/fixtures/businesses.json`
- Create: `tests/fixtures/sites/` HTML files listed below
- Create: `apps/intelligence-api/app/providers/mock_scraper.py`
- Create: `apps/intelligence-api/app/providers/scraper_client.py`
- Create: `apps/intelligence-api/tests/test_mock_scraper.py`
- Create: `apps/intelligence-api/tests/test_scraper_client.py`

**Interfaces:**
- Consumes: `NormalizedListing`
- Produces: FastAPI router `mock_scraper_router` with `POST /scraper/jobs` and `GET /scraper/jobs/{job_id}`; `ScraperClient.create_job(query, location, limit, filters) -> str`; `ScraperClient.get_job(job_id) -> JobResult`; `JobResult.status`, `.results: list[NormalizedListing]`, `.error`

- [x] **Step 1: Write fixtures and failing tests**

`tests/fixtures/businesses.json` — 9 listings (8 scenarios + 1 duplicate of place_id `ChIJ-acme`):

1. `no_website` — Oak Lawn Realty, Dallas, no website, place_id `ChIJ-noweb`, phone present, rating 4.2
2. `unreachable` — website `https://fixtures.intentlead.test/unreachable`, place_id `ChIJ-unreach`
3. `brochure` — website `https://fixtures.intentlead.test/brochure`, no form, no listing search
4. `listing_form` — listing search + contact form
5. `whatsapp_only` — WhatsApp link, no chatbot
6. `widgets` — chatbot and booking widget
7. `low_rating` — rating 2.1, 4 reviews, has website brochure-like
8. `explicit_intent` — page text requesting a listing website vendor
9. duplicate of 1 with same place_id, different phone

HTML fixtures (minimal valid HTML):

- `tests/fixtures/sites/brochure.html` — no viewport, no form, no listing search, phone in footer
- `tests/fixtures/sites/listing_form.html` — viewport, `#search` listing filters, `<form action="/inquire">`
- `tests/fixtures/sites/whatsapp.html` — viewport, `https://wa.me/12145550100`, no chatbot
- `tests/fixtures/sites/widgets.html` — `#chatbot` and `#book-now`
- `tests/fixtures/sites/explicit_intent.html` — paragraph: "We are looking for a vendor to build a property listing website"
- `tests/fixtures/sites/robots.txt` for a disallow case used in audit tests (Task 7)

Mock job completes immediately with filtered fixture rows (limit applied). Duplicate row included when query matches real estate.

Tests:

```python
def test_mock_job_returns_labeled_mock_results():
    # POST then GET via httpx ASGI transport against mock router
    ...
    assert all(r.discovery_source == "mock" for r in results)

def test_live_client_does_not_swap_in_mock_on_failure(monkeypatch):
    client = ScraperClient(base_url="http://127.0.0.1:9", token="", provider="live")
    with pytest.raises(ScraperError):
        client.create_job("real estate", "Dallas, Texas", 5, {})
```

Live client: httpx timeout 10s, retries 2 on 502/503/429 only. If `provider=="live"` and base_url empty → `ScraperError("GOOGLE_MAPS_SCRAPER_BASE_URL missing")`. If `provider=="mock"` client uses in-process app URL or direct mock functions — do not call live.

- [x] **Step 2: Run tests, expect fail**

Run: `cd apps/intelligence-api && PYTHONPATH=. pytest tests/test_mock_scraper.py tests/test_scraper_client.py -v`

Expected: FAIL missing modules

- [x] **Step 3: Implement mock router and client**

Map gosom-like JSON `{title, category, address, website, phone, emails, rating, reviewCount, placeId, reviews}` → `NormalizedListing`. Preserve `source_fields` as the raw object. Label `discovery_source` from client provider, not from the mock payload.

- [x] **Step 4: Run tests**

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add tests/fixtures apps/intelligence-api
git commit -m "feat: add mock Google Maps scraper and typed client"
```

---

### Task 5: CSV/JSON import loader

**Files:**
- Create: `apps/intelligence-api/app/providers/import_loader.py`
- Create: `apps/intelligence-api/tests/test_import_loader.py`

**Interfaces:**
- Produces: `load_import(content: bytes, filename: str) -> ImportResult` with `.listings: list[NormalizedListing]`, `.row_errors: list[str]`

- [x] **Step 1: Failing tests**

```python
def test_json_import_labels_import():
    data = b'[{"name":"A","address":"1 Main","city":"Dallas","category":"Real estate agency"}]'
    result = load_import(data, "x.json")
    assert result.listings[0].discovery_source == "import"
    assert result.listings[0].locality == "Dallas"

def test_missing_name_rejected_others_kept():
    data = b'[{"name":"","city":"Dallas"},{"name":"B","address":"2 Oak","city":"Dallas"}]'
    result = load_import(data, "x.json")
    assert len(result.listings) == 1
    assert result.row_errors
```

CSV columns: name, category, address, city, website, phone, email, rating, review_count, place_id.

- [x] **Step 2: Run, expect fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Tests pass**
- [x] **Step 5: Commit** `feat: add CSV and JSON business import loader`

---

### Task 6: SSRF guard

**Files:**
- Create: `apps/intelligence-api/app/services/ssrf.py`
- Create: `apps/intelligence-api/tests/test_ssrf.py`

**Interfaces:**
- Produces: `class UnsafeURL(Exception)`; `validate_public_url(url: str) -> ResolvedTarget` where `ResolvedTarget` has `url`, `hostname`, `port`, `ip` (the address that passed the check). Must resolve DNS, apply blocklist, allow only http/https and ports 80/443, reject userinfo.

- [x] **Step 1: Failing tests**

```python
import pytest
from app.services.ssrf import validate_public_url, UnsafeURL

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://localhost/",
    "http://10.0.0.1/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "file:///etc/passwd",
    "http://example.com:8080/",
    "http://user:pass@example.com/",
])
def test_blocked(url):
    with pytest.raises(UnsafeURL):
        validate_public_url(url)

def test_redirect_to_private_is_blocked(monkeypatch):
    # validate_public_url on http://127.0.0.1/redirect-target raises
    with pytest.raises(UnsafeURL):
        validate_public_url("http://192.168.0.5/next")
```

Use a fake resolver in tests via optional `resolver=` argument so tests do not depend on live DNS for private literals (literals skip DNS and are still blocked). For hostname tests, inject resolver returning `127.0.0.1` for `localhost` and a public IP for `example.com`.

```python
def test_hostname_resolving_to_loopback_blocked():
    with pytest.raises(UnsafeURL):
        validate_public_url("http://evil.test/", resolver=lambda h: ["127.0.0.1"])

def test_public_a_record_allowed():
    t = validate_public_url("https://example.com/", resolver=lambda h: ["93.184.216.34"])
    assert t.ip == "93.184.216.34"
    assert t.port == 443
```

- [x] **Step 2: Run, expect fail**
- [x] **Step 3: Implement blocklist from spec section 8.2** including IPv4-mapped IPv6. `ipaddress` module. Metadata hostnames blocked even if they resolved public.
- [x] **Step 4: Tests pass**
- [x] **Step 5: Commit** `feat: add SSRF URL validation for website audits`

---

### Task 7: robots.txt and access restrictions

**Files:**
- Create: `apps/intelligence-api/app/services/robots.py`
- Create: `apps/intelligence-api/tests/test_robots.py`

**Interfaces:**
- Produces: `robots_allows(robots_txt: str | None, url: str, user_agent="IntentLeadBot") -> bool`. `None` means unknown → allow (caller records `robots_unknown`). Disallow paths → False.

- [x] **Step 1: Failing tests**

```python
from app.services.robots import robots_allows

def test_disallow_star():
    txt = "User-agent: *\nDisallow: /hidden\n"
    assert robots_allows(txt, "https://ex.com/") is True
    assert robots_allows(txt, "https://ex.com/hidden/page") is False

def test_unknown_allows():
    assert robots_allows(None, "https://ex.com/") is True
```

- [x] **Step 2–5:** implement with urllib.robotparser, commit `feat: honor robots.txt disallow rules`

---

### Task 8: Website audit with limits and evidence

**Files:**
- Create: `apps/intelligence-api/app/services/audit.py`
- Create: `apps/intelligence-api/tests/test_audit.py`

**Interfaces:**
- Consumes: `validate_public_url`, `robots_allows`, `Evidence` model, fixture HTML loader
- Produces: `audit_business(session, campaign_id, business, *, fetcher) -> list[Evidence]`

Fetcher protocol: `fetch(url: str) -> FetchResult` with status, headers, body_bytes, final_url. Production fetcher: httpx, connect 5s, read 10s, max 3 redirects, each hop `validate_public_url`, 1 MiB truncate, per-host lock.

Mock/fixture path: if `business.discovery_source == "mock"` and website host is `fixtures.intentlead.test`, load matching HTML from `tests/fixtures/sites/` without network. `unreachable` maps to status 0 / timeout evidence. Never use `file://`.

Detect:

- viewport meta → `has_viewport`
- form with action → `has_form`; empty action or later 4xx on action URL → `broken_form`
- listing search: inputs/links containing listing|property|search|filter (case-insensitive) or `#search`
- wa.me or whatsapp → `has_whatsapp`
- id/class/script hints `chatbot`, `tidio`, `intercom`, `drift` → `has_chatbot`
- `book-now`, `calendly`, `booking` widget → `has_booking`
- explicit intent phrase: looking for a vendor / we need a website / hire.*web (only from inspected HTML, not Maps fields)

Access evidence reason codes as claims: `dns_failure`, `ssrf_blocked`, `robots_disallow`, `robots_unknown`, `access_restricted` (401/403/407), `challenge_or_paywall` (body contains recaptcha/hcaptcha/captcha or status 402 or www-authenticate paywall heuristics), `website_unreachable`, `content_type_skipped`.

Limits: follow at most 4 additional same-origin nav links after homepage (5 total). Skip non-html content-types.

If SSRF/robots/401/403/CAPTCHA/paywall: do **not** emit absence-of-feature observations.

- [x] **Step 1: Failing tests** (use fixture fetcher)

```python
def test_inaccessible_does_not_invent_missing_form(db, business_unreachable):
    ev = audit_business(db, campaign_id, business_unreachable, fetcher=fixture_fetcher)
    types = [e.claim for e in ev]
    assert any("unreachable" in e.claim.lower() or e.caveat for e in ev)
    assert not any("no inquiry" in e.claim.lower() for e in ev)

def test_ssrf_localhost_not_fetched(db):
    biz.website = "http://127.0.0.1/"
    ev = audit_business(...)
    assert any("ssrf" in (e.claim + e.caveat).lower() or "blocked" in e.claim.lower() for e in ev)

def test_robots_disallow(db, fetcher_with_robots_disallow_all):
    ev = audit_business(...)
    assert any("robots" in e.claim.lower() for e in ev)

def test_page_cap(db, fetcher_that_counts):
    audit_business(...)
    assert fetcher_that_counts.calls <= 6  # robots.txt + 5 pages

def test_explicit_intent_only_from_html(db, business_explicit):
    ev = audit_business(...)
    assert any(e.evidence_type == "explicit_intent" for e in ev)
```

- [x] **Step 2–5:** implement and commit `feat: add website audit with SSRF, robots, and evidence records`

---

### Task 9: Deterministic scoring with traceability

**Files:**
- Create: `apps/intelligence-api/app/scoring/reasons.py`
- Create: `apps/intelligence-api/app/scoring/engine.py`
- Create: `apps/intelligence-api/tests/test_scoring.py`

**Interfaces:**
- Produces: `score_lead(listing_facts, evidence: list[Evidence], target_services: list[str]) -> ScoreResult`

`ScoreResult`: overall_score, priority, confidence, dimensions: list[{dimension, points, max_points, evidence_ids, reason_code}], service_scores: list[{service, points, evidence_ids, reason_code}], recommended_service: str | None

Implement first-match rules from spec 9.2 and 9.3 exactly.

Residual chatbot/booking points: `ai_chatbot +10` / `crm_appointment_automation +15` when widgets visible, with reason_code `residual_existing_tool` and evidence_ids of the visibility observations.

`recommended_service` = max among target_services with points >= 40, tie order as SERVICES tuple. If the winning service's points come only from `residual_existing_tool` and there is no verified gap evidence, still return that service from scorer; draft layer (Task 10) refuses the body.

- [x] **Step 1: Golden tests for eight fixtures**

Compute expected numbers from spec while writing tests. Examples:

- no website, open real-estate, phone only, no explicit intent:
  - website_opportunity 25 `no_website_url`
  - lead_capture 18 `no_website_url`
  - automation 0 `unknown_not_inspected`
  - suitability 15 `niche_active`
  - buying_intent 0 `no_explicit_intent`
  - contactability 4 `public_phone`
  - overall 62, priority C
  - website_development 70
  - website_redesign 0
- maps-only (no website audit evidence except listing): buying_intent 0
- widgets visible: automation 0 `automation_already_visible`; ai_chatbot 10 residual; crm_appointment_automation 15 residual
- uninspected 401: website_opportunity 0 `unknown_not_inspected`
- explicit_intent HTML: buying_intent 15

Also assert every dimension has reason_code and evidence_ids list (empty allowed only with `unknown_not_inspected`, `no_explicit_intent`, `unknown_no_listing_fields`, `no_public_contact` — still include a listing evidence id when a listing exists).

```python
def test_scores_are_not_close_probability():
    # docstring / field: ScoreResult has no probability field
    r = score_lead(...)
    assert not hasattr(r, "close_probability")

def test_confidence_independent_of_score():
    # high score with one observation → confidence medium
    ...
```

- [x] **Step 2–5:** implement tables as data, no LLM. Commit `feat: add deterministic evidence-traced lead scoring`

---

### Task 10: Dry-run drafts

**Files:**
- Create: `apps/intelligence-api/app/services/drafts.py`
- Create: `apps/intelligence-api/tests/test_drafts.py`

**Interfaces:**
- Produces: `build_draft(*, agency_name, sender_name, business_name, recommended_service, evidence, service_scores) -> DraftResult` with `status` `preview` | `draft_not_recommended`, `body`, `reason`, `evidence_ids`

- [x] **Step 1: Failing tests**

```python
def test_blank_identity_not_recommended():
    r = build_draft(agency_name="", sender_name="", ...)
    assert r.status == "draft_not_recommended"
    assert r.reason == "agency_identity_not_configured"
    assert r.body is None

def test_does_not_invent_sender():
    r = build_draft(agency_name="", sender_name="", ...)
    assert r.body is None or "Alex" not in (r.body or "")

def test_residual_chatbot_no_false_gap():
    # recommended ai_chatbot with only residual_existing_tool
    r = build_draft(..., recommended_service="ai_chatbot", service_scores=[...])
    assert r.status == "draft_not_recommended"
    assert "no chatbot" not in (r.body or "").lower()

def test_preview_mentions_verified_observation():
    r = build_draft(agency_name="River Agency", sender_name="Sam Lee", recommended_service="real_estate_listing_portal", evidence=[verified missing listing search])
    assert r.status == "preview"
    assert "Sam Lee" in r.body
    assert "River Agency" in r.body
    assert "listing" in r.body.lower()

def test_never_sent_status():
    r = build_draft(...)
    assert r.status in {"preview", "draft_not_recommended"}
```

Template: `{sender} at {agency}. I reviewed the public pages at {scope} and noticed {claim}. If helpful, we can discuss {service}. Happy to share a brief outline — no need to reply if this is not relevant.`

- [x] **Step 2–5:** implement. Commit `feat: add dry-run outreach drafts without invented identity`

---

### Task 11: Campaign pipeline

**Files:**
- Create: `apps/intelligence-api/app/services/campaigns.py`
- Create: `apps/intelligence-api/app/services/pipeline.py`
- Create: `apps/intelligence-api/tests/test_pipeline.py`

**Interfaces:**
- Produces: `create_campaign(session, payload, settings) -> Campaign`; `run_campaign(session, campaign_id, settings, *, scraper: ScraperClient, fetcher) -> None`

Flow: parse → insert campaign dry_run True → insert scrape_job unique → if import wait (status `awaiting_import`) → else create scraper job → poll until complete/fail → normalize listings with discovery_source from settings.DISCOVERY_PROVIDER → upsert_business → get_or_create_lead → audit → score → persist dimension_scores/service_scores → build_draft → audit_log.

Live failure: job.status=`failed`, no businesses from mock.

- [x] **Step 1: Tests**

```python
def test_mock_pipeline_labels_source_and_dedupes(db, settings_mock):
    ...
    assert {b.discovery_source for b in businesses} == {"mock"}
    # duplicate place_id → one lead

def test_live_failure_does_not_insert_mock(db, settings_live_bad_url):
    run_campaign(...)
    assert db.query(Business).count() == 0
    job = db.query(ScrapeJob).one()
    assert job.status == "failed"
```

- [x] **Step 2–5:** implement. Commit `feat: run discovery-audit-score pipeline without mock fallback`

---

### Task 12: HTTP API and operator UI

**Files:**
- Create: `apps/intelligence-api/app/main.py`
- Create: `apps/intelligence-api/app/api/campaigns.py`
- Create: `apps/intelligence-api/app/api/leads.py`
- Create: `apps/intelligence-api/app/web/routes.py`
- Create: `apps/intelligence-api/app/web/templates/base.html`
- Create: `apps/intelligence-api/app/web/templates/campaign_new.html`
- Create: `apps/intelligence-api/app/web/templates/jobs.html`
- Create: `apps/intelligence-api/app/web/templates/leads.html`
- Create: `apps/intelligence-api/app/web/templates/lead_detail.html`
- Create: `apps/intelligence-api/tests/test_api.py`

**Interfaces:**
- FastAPI app includes mock scraper router, API router, web router
- Startup: `resolve_database_url`; if postgres unreachable, abort (do not catch and sqlite); run Alembic `upgrade head` when not in pytest

UI: persistent banner `Dry-run mode. Outreach is disabled.` No send button. Lead detail lists evidence, dimension reason_codes, evidence_ids, draft or not_recommended.

CSV: name, location, overall_score, priority, confidence, recommended_service, discovery_source, reason codes joined, website.

- [x] **Step 1: API tests with TestClient**

```python
def test_create_mock_campaign_and_list_leads(client):
    r = client.post("/api/campaigns", json={...})
    assert r.status_code == 201
    leads = client.get(f"/api/leads?campaign_id={r.json()['id']}").json()
    assert leads
    assert all(x["discovery_source"] == "mock" for x in leads)
    html = client.get("/").text
    assert "Dry-run mode" in html
    assert "Approve & Send" not in html
    detail = client.get(f"/leads/{leads[0]['id']}").text
    assert "Approve" not in detail or "Send" not in html

def test_health(client):
    assert client.get("/health").json()["status"] == "ok"

def test_export_csv_has_discovery_source(client):
    ...
    assert "discovery_source" in body
```

- [x] **Step 2–5:** implement templates (simple readable CSS, no emoji). Commit `feat: add operator UI and JSON API for dry-run campaigns`

---

### Task 13: Compose, start scripts, README

**Files:**
- Create: `docker-compose.yml`
- Create: `start.sh`
- Create: `start.ps1`
- Modify: `README.md`

**Interfaces:** none beyond docs

docker-compose: service `db` postgres:16, user/password/db `intentlead`/`change-me`/`intentlead`, port 5432; service `api` build or command `uvicorn app.main:app --host 0.0.0.0 --port 8000` with `DATABASE_URL` postgres, `DISCOVERY_PROVIDER=mock`, volume-less.

`start.sh`: wait for postgres or print that sqlite is not auto-selected; `alembic upgrade head`; `uvicorn`.

`start.ps1`: Windows equivalent; document `$env:DATABASE_URL`.

README: Phase 0–2 MVP status; how to run with docker Postgres; how to set explicit sqlite URL in development; PowerShell; dry-run only; do not claim live scraper works; link spec and this plan.

- [x] **Step 1:** No new unit test; run full suite

Run: `cd apps/intelligence-api && PYTHONPATH=. pytest -v`

Expected: all PASS

- [x] **Step 2:** Add scripts and README sections
- [x] **Step 3:** Commit `docs: add Postgres compose, start scripts, and Windows setup`

---

### Task 14: Full verification against spec

**Files:** none new unless a test failed

- [x] **Step 1:** Run `cd apps/intelligence-api && PYTHONPATH=. pytest -v`
- [x] **Step 2:** Confirm coverage of spec acceptance criteria by grepping tests for: ssrf, robots, sqlite, alembic (migration file exists), identity, dry-run, discovery_source, explicit_intent, residual, agency_identity_not_configured
- [x] **Step 3:** Fix any gap with a failing test first
- [x] **Step 4:** Commit only if fixes were needed

---

## Spec coverage checklist

| Spec section | Task |
|---|---|
| 3 architecture, single port | 12 |
| 5.1 entities / Alembic | 1 |
| 5.2 identity | 2 |
| 6 providers mock/live/import | 4, 5, 11 |
| 7 parser | 3 |
| 8.1 limits | 8 |
| 8.2 SSRF | 6, 8 |
| 8.3 robots/401/CAPTCHA | 7, 8 |
| 9 scoring + traceability + residual | 9 |
| 10 drafts + blank identity | 10 |
| 11 UI | 12 |
| 12 API | 12 |
| 13 database policy | 1, 12 |
| 16 tests listed | 1–12, 14 |
| 18 no Telegram/n8n/Sheets/Calendar/LLM/dispatch | global; no tasks add them |
)
