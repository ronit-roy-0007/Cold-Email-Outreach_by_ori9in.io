# GitHub Repository Guide

## 1. Recommended repository name

`intentlead-ai`

Suggested description:

> Evidence-led B2B prospect discovery, lead qualification, Telegram-approved outreach, reply management, and meeting automation.

## 2. Suggested directory structure

```text
intentlead-ai/
├── README.md
├── architecture.md
├── prompt.md
├── github.md
├── SOURCES.md
├── .gitignore
├── .env.example
├── docker-compose.yml
├── apps/
│   ├── intelligence-api/
│   │   ├── app/
│   │   ├── tests/
│   │   └── requirements.txt
│   └── telegram-bot/
├── n8n/
│   ├── workflows/
│   └── README.md
├── database/
│   ├── migrations/
│   └── schema/
├── integrations/
│   ├── google-maps-scraper/
│   ├── google-calendar/
│   ├── google-sheets/
│   └── channels/
├── prompts/
│   └── prompt.md
├── tests/
│   ├── fixtures/
│   └── acceptance/
└── docs/
    ├── runbooks/
    └── decisions/
```

## 3. Upstream repositories

### Primary runtime dependency

```bash
git clone --depth 1 https://github.com/gosom/google-maps-scraper.git
```

Keep the scraper in a separate checkout or as a pinned submodule/subtree only if the team has a clear update strategy. Do not silently fork and modify upstream behavior without documenting the delta.

### Reference-only research source

```bash
git clone --depth 1 https://github.com/Kappaemme-git/codex-first-customer-finder-skill.git
```

Use this checkout for studying workflow concepts and tests. Do not install it as a production dependency. Document which ideas were independently implemented in IntentLead AI.

## 4. Git submodule option

If you explicitly want both upstream source trees visible inside this repository, use submodules rather than copying their files:

```bash
git submodule add https://github.com/gosom/google-maps-scraper.git vendor/google-maps-scraper
git submodule add https://github.com/Kappaemme-git/codex-first-customer-finder-skill.git references/first-customer-finder-skill
git submodule update --init --recursive
```

This preserves upstream history and makes the distinction clear. The first submodule is the primary scraper dependency; the second is a reference library. Review both licenses and any additional notices before redistributing.

To clone the project with submodules:

```bash
git clone --recurse-submodules <YOUR_INTENTLEAD_REPOSITORY_URL>
```

To update a submodule intentionally:

```bash
git -C vendor/google-maps-scraper fetch origin
git -C vendor/google-maps-scraper checkout <REVIEWED_COMMIT>
git add vendor/google-maps-scraper
git commit -m "chore: update Google Maps scraper reference"
```

Do not blindly track upstream `main` in production. Pin reviewed commits and test updates.

## 5. Branch strategy

- `main` — stable, reviewed code.
- `develop` — integration branch.
- `feature/<short-name>` — feature work.
- `fix/<short-name>` — bug fixes.
- `docs/<short-name>` — documentation changes.

Example:
```bash
git switch -c feature/telegram-approval
```

## 6. Commit convention

Use clear conventional-style messages:
- `feat: add Google Maps scraper client`
- `feat: add evidence-backed lead scoring`
- `feat: add Telegram approval callbacks`
- `feat: create Google Calendar events for confirmed meetings`
- `fix: prevent duplicate outreach dispatch`
- `docs: document channel eligibility rules`
- `test: cover opt-out suppression`

## 7. .gitignore essentials

```gitignore
.env
.env.*
!.env.example
.venv/
venv/
__pycache__/
*.py[cod]
node_modules/
dist/
build/
.idea/
.vscode/
.DS_Store
Thumbs.db
*.log
data/
outputs/
secrets/
credentials/
*.sqlite3
```

Do not ignore migrations, schema definitions, workflow JSON, or safe test fixtures.

## 8. Environment variables

Create `.env.example` with placeholders only. Never commit actual credentials.

```dotenv
APP_ENV=development
LOG_LEVEL=INFO

DATABASE_URL=postgresql://intentlead:change-me@localhost:5432/intentlead

GOOGLE_MAPS_SCRAPER_BASE_URL=http://localhost:8080
GOOGLE_MAPS_SCRAPER_API_TOKEN=

TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=
GOOGLE_CALENDAR_ID=primary

GOOGLE_SHEETS_SPREADSHEET_ID=

LLM_PROVIDER=
LLM_API_KEY=
LLM_MODEL=

OUTREACH_DRY_RUN=true
```

Use your n8n credential store or a secret manager for production. The example values above are not working credentials.

## 9. Pull request checklist

- [ ] Tests pass.
- [ ] No secrets or personal data committed.
- [ ] Evidence provenance is preserved.
- [ ] Numeric scoring is deterministic and tested.
- [ ] Unknowns are not converted into facts.
- [ ] Channel eligibility and opt-out gates are enforced.
- [ ] Telegram approval is restricted and idempotent.
- [ ] Duplicate webhook events are safe.
- [ ] Calendar events are idempotent and tied to a confirmed booking.
- [ ] Logs contain no tokens or unnecessary personal data.
- [ ] Documentation and `.env.example` are updated.

## 10. Release checklist

1. Pin upstream dependency commits.
2. Run unit and integration tests.
3. Test with synthetic fixtures.
4. Run a dry-run campaign.
5. Manually review a small sample of evidence and scores.
6. Confirm opt-out and suppression behavior.
7. Confirm calendar create/update/cancel behavior.
8. Back up PostgreSQL and test restore.
9. Tag a version and publish release notes.
