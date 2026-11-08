Build the first working MVP of IntentLead AI using the existing project specifications.

**Repository roles:**
1. `gosom/google-maps-scraper` is our primary business discovery engine.
2. `Kappaemme-git/codex-first-customer-finder-skill` is a reference for learning and independently implementing useful research, evidence validation, qualification, scoring, and reporting logic. Do not make it a runtime dependency.

**MVP requirements:**

1. Telegram bot accepts natural-language lead discovery requests.
2. Google Maps scraper discovers businesses based on niche, location, and filters.
3. Python intelligence service investigates publicly accessible business websites and information.
4. Evidence-based scoring calculates:
   - Overall lead score (0–100).
   - Separate service-fit scores.
   - Confidence levels.
   - Verified problems vs potential opportunities vs explicit buying intent.
5. AI generates personalized outreach messages based on actual evidence.
6. Telegram displays approval cards with Approve, Edit, and Reject actions.
7. Implement channel eligibility checks and dry-run mode. Do not send unauthorized promotional messages.
8. PostgreSQL stores businesses, evidence, scores, messages, and campaign history.
9. Google Sheets supports CRM synchronization.

**Development requirements:**
- Build actual working code, not just mockups or placeholder functions.
- Preserve the existing project structure where practical.
- Implement proper error handling, logging, deduplication, and tests.
- Keep credentials in environment variables.
- Provide Windows PowerShell setup instructions.
- Do not implement fake integrations or claim a feature works before testing it.

**Development strategy:**
First deliver a working discovery → enrichment → scoring → Telegram approval → CRM pipeline. Keep live outreach disabled by default.

After that works, prepare the next phase for reply detection, automated follow-ups, and Google Calendar meeting management.

Before modifying files, inspect the existing workspace and report what is already implemented. Do not unnecessarily overwrite existing working code.

Implement a provider-based business discovery architecture.

- Primary provider: gosom/google-maps-scraper.
- Development provider: realistic mock scraper API.
- Support CSV and JSON business imports as fallback.
- Keep the scraper API client independent of the scoring and enrichment services.
- Use a consistent normalized business schema.
- Include realistic test records for real-estate agencies.
- Implement pagination, retries, timeouts, deduplication and error handling.
- Add a provider configuration setting to switch between mock, import and live scraper modes.
- Never silently substitute mock data when live scraping fails. Clearly identify mock/import/live data in every record and report.
- Do not claim live Google Maps scraping is operational until it has been tested against the actual scraper service.