# IntentLead AI — Product Implementation Roadmap

**Date:** 2026-11-16  
**Project:** `Cold-Email-Outreach_by_ori9in.io`  
**Execution:** Phased Implementation according to Master Design Brief  
**Design Reference:** MonkeyCode Editorial-Engineering Visual Language (`https://monkeycode.cc/`)  

---

## 1. Roadmap Phasing Strategy

```
Phase 0: Design System & Core Shell (P0)
 ├── Design Tokens (Cream #F8F6F0, Obsidian #0F1117, Electric Lime #C8F560)
 ├── Engineering Grid & Brutalist Offset Shadow Components
 ├── Unified Responsive Sidebar & Top Navigation Bar
 └── Mobile Navigation Drawer & Telemetry Indicators

Phase 1: Mission-Critical Operational Workspaces (P0)
 ├── Overview Dashboard (KPI Cards, Lead Pipeline, Discovery Trends, Live Telemetry)
 ├── Lead Intelligence Directory (Search, Multi-Filter, Sorting, Status Pills, Pagination)
 ├── Deep Lead Intelligence View & Evidence Modal
 └── Dedicated Approval Center (Draft Review, Evidence Inspection, Inline Email Preview, Approve/Reject Actions)

Phase 2: Outreach Execution & Asset Management (P1)
 ├── Campaign Management Workspace (List, Creation Wizard, CSV Export, Progress Tracking)
 ├── Email Draft Preview & Personalization Editor
 ├── Mailbox Pool Management (Status, Quota Usage Meters, Active Switch, Rotation Health)
 └── Suppression Management (List, Search, Reason Tags, Manual Suppression Add Modal)

Phase 3: Intelligence, Audit & Configuration (P2)
 ├── Analytics & Qualification Performance Reports
 ├── Audit Log & Activity Stream (Approvals, Dispatches, System Events)
 └── Settings & Integrations Center (API Keys, AI Models, Telegram, Webhooks, Masked Secrets)

Phase 4: Visual Polish, Micro-Interactions & Rigorous QA (P3)
 ├── Micro-interactions (Button active press, subtle badge transitions, modal animations)
 ├── Comprehensive Cross-Device Responsive Testing (Mobile 375px, Tablet 768px, Laptop 1024px, Desktop 1440px)
 └── Regression Testing Against Live Docker Staging Backend
```

---

## 2. Detailed Task Breakdown by Priority

### Priority 0 (P0) — Foundations & Core Workspaces
- [x] **T0.1 Design System Assets:** Create `static/css/intentlead.css` establishing custom properties (`--bg-canvas`, `--bg-sidebar`, `--accent-lime`, `--border-color`, `--shadow-offset`), typography scale, and brutalist card/button utilities.
- [x] **T0.2 Application Shell:** Redesign `base.html` with persistent dark sidebar, status indicators, mobile hamburger drawer, and top navigation header.
- [x] **T0.3 Overview Dashboard (`/`):** Implement metrics grid (Discovered Businesses, Qualified Leads, Pending Approvals, Total Dispatches), pipeline distribution bar, active campaigns, and quick action launchpad.
- [x] **T0.4 Lead Intelligence (`/leads`):** Implement searchable, sortable lead directory with filter chips (Priority A/B/C, Status Draft/Approved/Sent), score badges, and quick drawer.
- [x] **T0.5 Deep Lead Detail (`/leads/{id}`):** Comprehensive visual report showing business metadata, Google Maps review signals, 5 dimension scores, service fit scores, website gaps, and raw evidence excerpts.
- [x] **T0.6 Approval Center (`/approvals`):** Specialized operator queue showing leads awaiting approval, side-by-side evidence and AI email draft review, with one-click approve (`POST /api/orchestrator/approvals/{id}`) and reject controls.

### Priority 1 (P1) — Campaigns, Outreach & Deliverability
- [x] **T1.1 Campaign Management (`/campaigns`):** Campaign cards and table displaying niche, location, progress against target (`total_sent_emails / target_sent_emails`), and status pills.
- [x] **T1.2 Campaign Creation Modal & Form (`/campaigns/new`):** Clean modal and dedicated page supporting niche presets, location autocomplete, service multi-select, and provider selection.
- [x] **T1.3 Mailbox Management (`/mailboxes`):** Operational view of `mailbox_accounts` displaying sender names, daily sending quotas, usage progress meters, and status toggles.
- [x] **T1.4 Suppression List Management (`/suppression`):** Searchable suppression directory with reason codes (unsubscribe, complaint, bounce, manual) and manual suppression modal.

### Priority 2 (P2) — Analytics, Auditing & Configuration
- [x] **T2.1 Analytics & Reporting (`/analytics`):** Interactive data cards and SVG charts visualizing lead score distribution, campaign conversion rates, and deliverability metrics.
- [x] **T2.2 Audit & Activity Log (`/activity`):** Chronological event stream displaying system actions, operator approvals, scrape jobs, and dispatches.
- [x] **T2.3 Settings & Integrations (`/settings`):** Clean multi-tab configuration interface for General, Discovery Providers, Telegram Bot, Webhooks, and Operator Profile with masked credentials.

### Priority 3 (P3) — Polish, Accessibility & QA
- [x] **T3.1 Micro-Interactions & Polish:** Tactile button states (`box-shadow: 1px 1px 0px #000; transform: translate(1px, 1px);`), score pill color scales, and toast notifications.
- [x] **T3.2 Responsive Adaptations:** Fluid table layouts, mobile drawer navigation, stacked forms on mobile screens.
- [x] **T3.3 End-to-End QA Validation:** Verify all 9 modules against the live Docker staging stack.
