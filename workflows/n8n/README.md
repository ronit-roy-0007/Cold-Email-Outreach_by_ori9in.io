# IntentLead AI — n8n Automation Workflows (Phase 3 & 4)

This directory contains production-ready n8n workflow templates connecting your local IntentLead AI instance to Telegram and Google Sheets.

## Workflows Included

1. **`01_campaign_discovery_workflow.json` (Discovery Trigger):**
   - Scheduled trigger (weekly) or instant manual webhook (`/webhook/trigger-discovery`).
   - Calls IntentLead API `POST /api/orchestrator/campaign-run`.
   - Sends a Telegram notification when discovery and scoring finish.

2. **`02_telegram_approval_workflow.json` (Approval Cards):**
   - Fetches newly scored leads waiting for review (`GET /api/orchestrator/pending-approvals`).
   - Sends interactive Telegram Approval Cards formatted with prospect score, verified gaps, and drafted pitch.
   - Contains inline keyboard buttons: `[ ✅ Approve ]`, `[ ⏭️ Skip ]`, `[ ❌ Reject ]`.
   - Captures operator button clicks and updates the lead status in IntentLead API (`POST /api/orchestrator/approvals/{id}`).

3. **`03_sheets_sync_workflow.json` (Google Sheets Sync):**
   - Receives webhook notification when a lead is approved.
   - Fetches full lead and business details.
   - Upserts the prospect record into Google Sheets with scores, recommended service, and contact details.

## How to Import into n8n

1. Open your local n8n instance (e.g. `http://localhost:5678`).
2. Click **Add workflow** $\to$ Click the **`...` (three dots menu)** in the top right $\to$ **Import from File**.
3. Select any of the `.json` files from this folder.
4. Set the following environment variables or credentials in n8n:
   - `TELEGRAM_BOT_TOKEN` (Telegram Bot Credential in n8n)
   - `TELEGRAM_CHAT_ID` (Your authorized Telegram User/Chat ID)
   - `GOOGLE_SHEET_ID` (ID of your Google Spreadsheet for CRM tracking)
