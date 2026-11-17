# IntentLead AI — Environment & Configuration Reference

This guide documents every configuration parameter available in IntentLead AI.
Settings can be defined in a `.env` file at the repository root or passed as system environment variables.

---

## 1. Core Application Settings

| Variable | Type | Default | Description |
|---|---|---|---|
| `APP_ENV` | `string` | `development` | Environment mode: `development`, `staging`, or `production`. In `production`, strict security validations are enforced (mandatory encryption key, non-wildcard CORS, unique unsubscribe secret). |
| `LOG_LEVEL` | `string` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
| `API_KEY` | `string` | *(empty)* | Optional master API key for authenticating programmatic REST requests (`X-API-Key` or `Authorization: Bearer <key>`). If empty in `development`, allows unauthenticated local access. |
| `CORS_ORIGINS` | `string` | `*` | Allowed CORS origins (comma-separated). Must be an explicit list in `production` (e.g. `https://intentlead.yourcompany.com`). Wildcards are rejected in production. |
| `RATE_LIMIT_PER_MINUTE` | `integer` | `120` | Maximum API requests allowed per client IP per minute. |
| `TRUSTED_PROXIES` | `string` | `127.0.0.1,::1` | Comma-separated list of trusted upstream reverse-proxy IPs (e.g. Nginx, Cloudflare, Docker gateway). Protects against IP spoofing via `X-Forwarded-For`. |

---

## 2. Database & Cache

| Variable | Type | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | `string` | `sqlite:///./intentlead.db` | SQLAlchemy connection string. In development, SQLite is permitted (`sqlite:///./intentlead.db`). In production, a PostgreSQL database is required (`postgresql://user:pass@host:5432/dbname`). |
| `REDIS_URL` | `string` | *(empty)* | Connection string for Redis (`redis://redis:6379/0`). In production, Redis is strictly required for atomic distributed webhook replay protection and distributed rate limiting. |

---

## 3. Agency Branding & Identity

| Variable | Type | Default | Description |
|---|---|---|---|
| `AGENCY_NAME` | `string` | `IntentLead` | Default agency name used across email signatures, headers, and Telegram notifications. |
| `AGENCY_SENDER_NAME` | `string` | `Outreach Team` | Default human sender name used in cold email templates. |
| `AGENCY_PHYSICAL_ADDRESS` | `string` | `100 Innovation Way...` | Physical postal address required in email footers for CAN-SPAM and GDPR compliance. |

---

## 4. Cold Outreach & Safety Controls

| Variable | Type | Default | Description |
|---|---|---|---|
| `OUTREACH_DRY_RUN` | `boolean` | `true` | **CRITICAL SAFETY SWITCH**. When `true`, dispatches are simulated and logged to the database without sending real emails. Must be explicitly set to `false` by an operator to send live emails. |
| `EMAIL_PROVIDER` | `string` | `smtp` | Primary email provider: `smtp`, `resend`, or `google_workspace`. |
| `SENDER_EMAIL` | `string` | `outreach@example.com` | Default "From" email address. |
| `MAX_EMAILS_PER_DAY` | `integer` | `50` | Maximum daily dispatch limit across all mailboxes to protect sender reputation. |
| `ENABLE_DISPATCH_PACING` | `boolean` | `true` | Introduces jitter and randomized delays between outbound emails to prevent ESP rate-limiting and spam triggers. |
| `MAILBOXES_FILE` | `string` | `mailboxes.json` | Path to JSON file defining rotating mailboxes for multi-inbox rotation. |

---

## 5. SMTP Configuration

| Variable | Type | Default | Description |
|---|---|---|---|
| `SMTP_HOST` | `string` | *(empty)* | Outgoing SMTP server hostname (e.g. `smtp.gmail.com`, `smtp.sendgrid.net`). |
| `SMTP_PORT` | `integer` | `587` | SMTP port (typically `587` for STARTTLS, `465` for SSL/TLS). |
| `SMTP_USER` | `string` | *(empty)* | SMTP username / email. |
| `SMTP_PASSWORD` | `string` | *(empty)* | SMTP password or app-specific password. |
| `SMTP_USE_TLS` | `boolean` | `true` | Whether to enable STARTTLS for secure transport. |

---

## 6. AI Personalization & Audit

| Variable | Type | Default | Description |
|---|---|---|---|
| `USER_LLM_API_KEY` | `string` | *(empty)* | API key for Google Gemini (or compatible LLM provider). Used to perform prospect website audits and generate customized cold outreach pitches. |
| `USER_LLM_MODEL` | `string` | `gemini-1.5-flash` | LLM model identifier (e.g. `gemini-1.5-flash`, `gemini-1.5-pro`). |
| `USER_LLM_BASE_URL` | `string` | *(empty)* | Optional custom API endpoint URL when using LiteLLM, Ollama, or OpenAI-compatible gateways. |

---

## 7. Telegram Bot Operator Interface

| Variable | Type | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `string` | *(empty)* | Telegram Bot API token obtained from `@BotFather`. |
| `TELEGRAM_ALLOWED_USER_ID` | `string` | *(empty)* | Numeric Telegram user ID of the authorized operator. All other Telegram users are rejected. |
| `TELEGRAM_WEBHOOK_SECRET` | `string` | *(empty)* | Secret token for validating incoming Telegram webhook requests when running in webhook mode instead of long-polling. |

---

## 8. Cryptographic & Webhook Secrets

| Variable | Type | Default | Description |
|---|---|---|---|
| `FIELD_ENCRYPTION_KEY` | `string` | *(empty)* | Fernet encryption key or 32-character passphrase used to encrypt sensitive mailbox passwords and API keys at rest in the database. Required in `production`. |
| `UNSUBSCRIBE_SECRET` | `string` | *(generated)* | Secret key used to generate HMAC-signed one-click unsubscribe links. Required to be unique in `production`. |
| `UNSUBSCRIBE_BASE_URL` | `string` | `http://localhost:8000/unsubscribe` | Public base URL for unsubscribe links included in outbound emails. |
| `OUTREACH_WEBHOOK_SECRET` | `string` | *(empty)* | HMAC secret for verifying custom inbound email parser webhooks. |
| `RESEND_WEBHOOK_SECRET` | `string` | *(empty)* | Svix webhook signing secret (`whsec_...`) for Resend delivery/bounce/reply events. |
| `MAILGUN_WEBHOOK_SIGNING_KEY` | `string` | *(empty)* | Mailgun HTTP webhook signing key for verifying authenticity of inbound callbacks. |

---

## 9. Lead Discovery

| Variable | Type | Default | Description |
|---|---|---|---|
| `DISCOVERY_PROVIDER` | `string` | `scrapling` | Discovery scraper engine: `scrapling` (stealth browserless crawling), `google_maps` (microservice scraper), or `mock` (deterministic fixtures for testing). |
| `GOOGLE_MAPS_SCRAPER_BASE_URL` | `string` | `http://localhost:8080` | URL of the optional Go Google Maps scraper container when using `DISCOVERY_PROVIDER=google_maps`. |
| `GOOGLE_MAPS_SCRAPER_API_TOKEN` | `string` | *(empty)* | Optional bearer token for authenticating with the external scraper service. |
