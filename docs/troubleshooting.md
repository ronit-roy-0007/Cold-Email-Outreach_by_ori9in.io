# IntentLead AI — Troubleshooting & Diagnostics Guide

This guide provides solutions for common configuration, network, and operational issues.

---

## 1. Telegram Bot Issues

### Symptom: Bot does not reply to `/findleads` or commands
- **Cause 1**: `TELEGRAM_ALLOWED_USER_ID` does not match your numeric Telegram user ID.
  - *Fix*: Check your ID using `@userinfobot` and update `TELEGRAM_ALLOWED_USER_ID` in `.env`. Restart the poller.
- **Cause 2**: Telegram poller process is not running.
  - *Fix*: Check container status with `docker compose ps` or logs with `docker compose logs -f telegram-poller`.
- **Cause 3**: `TELEGRAM_BOT_TOKEN` is invalid or contains extra spaces.
  - *Fix*: Verify the token with BotFather: `curl https://api.telegram.org/bot<TOKEN>/getMe`.

---

## 2. AI Personalization & LLM Issues

### Symptom: Campaigns proceed without personalized AI pitch text
- **Cause**: `USER_LLM_API_KEY` is not configured or is invalid.
  - *Fix*: IntentLead AI has a zero-crash design. When an API key is missing or quota is exhausted, campaigns fall back to high-converting cold email copy. Add a valid Gemini API key to `.env` to restore AI generation.
- **Cause**: Google Gemini Free Tier 429 quota exhaustion.
  - *Fix*: The built-in `GeminiRateLimiter` paces calls at 14 RPM. If you have multiple workers running concurrently on the same key, upgrade to a paid Gemini API tier or route through LiteLLM.

---

## 3. Email Dispatch & SMTP Issues

### Symptom: `smtplib.SMTPAuthenticationError: (535, '5.7.8 Username and Password not accepted')`
- **Cause**: Using your normal Google account password instead of an App Password.
  - *Fix*: Google requires an App Password when 2FA is active. Generate a 16-character App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) and enter it without spaces in `SMTP_PASSWORD` or `mailboxes.json`.

### Symptom: Emails not sending even though campaigns are started
- **Cause**: `OUTREACH_DRY_RUN` is set to `true`.
  - *Fix*: By default, outreach is simulated. Check your mode with `/mode` in Telegram or inspect `OUTREACH_DRY_RUN` in `.env`. To send live emails, set `OUTREACH_DRY_RUN=false` or use `/live` in Telegram.

---

## 4. Docker & Port Conflicts

### Symptom: `Bind for 0.0.0.0:8000 failed: port is already allocated`
- **Cause**: Another service (or previous container) is listening on port 8000.
  - *Fix*: Change the published host port in `.env`:
    ```bash
    API_PORT=8085
    ```
    Then run `docker compose up -d`.

---

## 5. Webhook Replay & Inbound Issues

### Symptom: Inbound webhooks return `503 Service Unavailable: Distributed replay protection failed`
- **Cause**: In production (`APP_ENV=production`), Redis is strictly required for replay protection. If the Redis container is down or unreachable, the webhook fails closed.
  - *Fix*: Ensure Redis is running: `docker compose ps redis`. Verify `REDIS_URL` in `.env`.
