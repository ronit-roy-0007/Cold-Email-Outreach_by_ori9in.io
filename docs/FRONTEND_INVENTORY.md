# IntentLead AI — Frontend Inventory & Architectural Assessment

**Date:** 2026-11-16  
**Project:** `Cold-Email-Outreach_by_ori9in.io`  
**Application:** `apps/intelligence-api`  
**Stack:** FastAPI, Jinja2Templates, HTML5, CSS3 Custom Properties (Design Tokens), Vanilla JS  
**Status:** Pre-Upgrade Baseline Audit  

---

## 1. Executive Summary

IntentLead AI is an autonomous B2B client acquisition engine with robust backend intelligence, stealth scraping, multi-mailbox pooling, and human-in-the-loop approval gates. However, the existing frontend was a rudimentary developer prototype utilizing basic unstyled tables and an outdated dark-blue theme (`#0f172a`), lacking modern SaaS navigation, dedicated operational views, responsive controls, or the editorial-engineering visual language required for a production-grade intelligence platform.

This inventory documents all existing frontend routes, templates, data bindings, API integrations, and UI components prior to the master design overhaul.

---

## 2. Existing Frontend Routes (`apps/intelligence-api/app/web/routes.py`)

| Route Path | HTTP Method | Template Used | Backing DB / Service Models | Functional State | Limitations & Gaps |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `GET /` | `GET` | `jobs.html` | `Campaign`, `ScrapeJob` | Functional | Displays raw campaign table; lacks operational metrics, KPI cards, pipeline charts, and quick-action triggers. |
| `GET /campaigns/new` | `GET` | `campaign_new.html` | None | Functional | Bare HTML form; lacks target service chips, budget/pacing options, provider descriptions, and validation feedback. |
| `POST /campaigns/new` | `POST` | Redirects to `/campaigns/{id}` | `create_campaign`, `run_campaign` | Functional | Form POST without progress indicator; no async background dispatch feedback. |
| `GET /campaigns/{campaign_id}` | `GET` | `leads.html` | `Lead`, `Business`, `Campaign` | Functional | Basic table of leads for a single campaign; lacks search, sorting, multi-status filters, and batch actions. |
| `GET /campaigns/{campaign_id}/export.csv` | `GET` | Plain CSV stream | `Lead`, `Business`, `DimensionScore`, `Evidence` | Functional | Raw CSV download; functional and complete. |
| `GET /leads/{lead_id}` | `GET` | `lead_detail.html` | `Lead`, `Business`, `DimensionScore`, `ServiceScore`, `MessageDraft`, `Evidence` | Functional | Displays raw audit lists; lacks inline draft editing, approval/rejection triggers, and visual evidence cards. |

---

## 3. Existing Templates Inventory (`apps/intelligence-api/app/web/templates/`)

### 3.1 `base.html` (134 lines)
- **Palette:** Generic Tailwind-dark blues (`#0f172a`, `#1e293b`, `#334155`, `#38bdf8`).
- **Layout:** Fixed top navbar with only 3 links (`IntentLead AI`, `New Campaign`, `Campaigns`, `Pending Approvals`).
- **Flaws:**
  - No sidebar navigation shell.
  - No operator status indicators (Staging, Dry-Run, DB connection status).
  - No mobile navigation drawer or responsive hamburger toggle.
  - No modular design system or reusable typography tokens.

### 3.2 `jobs.html` (52 lines)
- **Content:** Minimal list of campaigns with status badges.
- **Flaws:** No aggregate KPI metrics, no lead pipeline summary, no recent activity log.

### 3.3 `campaign_new.html` (76 lines)
- **Content:** Simple input fields for niche, location, quantity, provider, target services.
- **Flaws:** Missing visual guidance, no presets for common B2B niches, unstyled multi-select.

### 3.4 `leads.html` (74 lines)
- **Content:** Table showing Business, Score, Priority, Status, Service, Actions.
- **Flaws:** No live search, no filter pills, no pagination, no batch approval or quick-preview modal.

### 3.5 `lead_detail.html` (148 lines)
- **Content:** Lists dimension scores, service fit scores, email draft text, and evidence excerpts.
- **Flaws:** Raw text presentation without visual hierarchy, score meters, or interactive approval buttons.

---

## 4. Backend API Endpoints Available for Frontend Integration

The backend exposes rich REST APIs that the frontend currently underutilizes:

1. **Campaigns API (`/api/campaigns`):**
   - `GET /api/campaigns` (full campaign metadata, quantities, and dates).
   - `POST /api/campaigns/{id}/import` (CSV file upload).
2. **Leads API (`/api/leads`):**
   - `GET /api/leads` (cross-campaign lead queries with `limit`, `offset`, `campaign_id`).
   - `GET /api/leads/{id}` (deep lead intelligence payload).
3. **Orchestrator API (`/api/orchestrator`):**
   - `POST /api/orchestrator/campaign-run` (trigger end-to-end scraper & scoring).
   - `POST /api/orchestrator/approvals/{lead_id}` (`action: "approve"` or `"reject"`).
   - `GET /api/orchestrator/pending-approvals` (unapproved draft leads).
4. **Outreach & Compliance API (`/api/outreach`):**
   - `POST /api/outreach/dispatch` (controlled dispatch engine with dry-run protection).
   - `GET /api/outreach/suppression` (suppression list entries).
   - `POST /api/outreach/suppression` (add email to suppression list).
   - `GET /api/outreach/unsubscribe` (HMAC-signed opt-out flow).
5. **System & Health API (`/health/ready`, `/health/live`):**
   - Real-time database, Redis, discovery provider, and dry-run operational mode telemetry.

---

## 5. Architectural Upgrade Requirements

To transform IntentLead AI into an enterprise B2B intelligence platform:
1. **Design System:** Implement MonkeyCode-inspired warm editorial engineering aesthetic (`#F8F6F0` cream background, `#0F1117` obsidian sidebar, `#C8F560` electric lime accent, 1.5px solid borders, and brutalist offset shadows).
2. **Modular Application Shell:** Unified responsive sidebar with mobile drawer, breadcrumbs, search, and live environment telemetry badges.
3. **9 Complete Product Modules:**
   - A. Operational Dashboard (`/` & `/overview`)
   - B. Lead Intelligence (`/leads` & `/leads/{id}`)
   - C. Approval Center (`/approvals`)
   - D. Campaign Management (`/campaigns`)
   - E. Mailbox Management (`/mailboxes`)
   - F. Analytics & Reporting (`/analytics`)
   - G. Suppression Management (`/suppression`)
   - H. Activity & Audit History (`/activity`)
   - I. Settings & Integrations (`/settings`)
4. **Interactivity & State Management:** Vanilla modern JavaScript for filtering, tabs, modals, drawer toggles, and seamless async API calls without heavy framework bloat.
