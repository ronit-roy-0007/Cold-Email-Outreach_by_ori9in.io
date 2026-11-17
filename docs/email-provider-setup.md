# IntentLead AI — Email Provider & Mailbox Pool Setup Guide

IntentLead AI supports multi-mailbox pool rotation, automated warmup pacing, CAN-SPAM/GDPR compliance, and inbound reply tracking.

---

## 1. Supported Dispatch Providers

| Provider | Mode | Best For | Configuration Key |
|---|---|---|---|
| **Standard SMTP** | Direct SMTP | Gmail/Google Workspace App Passwords, Outlook, Zoho, Private Mail Servers | `EMAIL_PROVIDER=smtp` |
| **Resend** | REST API | Modern transactional sending with Svix webhook callbacks | `EMAIL_PROVIDER=resend` |
| **Google Workspace** | SMTP / OAuth | Agency primary domain accounts | `EMAIL_PROVIDER=smtp` |

---

## 2. Configuring Standard SMTP (e.g. Gmail / Google Workspace)

1. Enable 2-Step Verification on your Google account.
2. Navigate to **Google Account Security > App Passwords**.
3. Create an app password for "Mail" on your device (generates a 16-character string).
4. Update `.env`:
   ```bash
   EMAIL_PROVIDER=smtp
   SENDER_EMAIL=outreach@yourdomain.com
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=outreach@yourdomain.com
   SMTP_PASSWORD=your_16_char_app_password
   SMTP_USE_TLS=true
   ```

---

## 3. Multi-Mailbox Pool Rotation

To maintain high deliverability and avoid mailbox burn, IntentLead AI distributes outbound emails across a pool of rotating sender mailboxes.

### File-Based Configuration (`mailboxes.json`)
Create `mailboxes.json` at the root of the project (copy from `mailboxes.example.json`):
```json
[
  {
    "email": "alex.outreach1@yourdomain.com",
    "password": "app_password_1",
    "sender_name": "Alex",
    "daily_limit": 40,
    "is_active": true
  },
  {
    "email": "alex.outreach2@yourdomain.com",
    "password": "app_password_2",
    "sender_name": "Alex",
    "daily_limit": 40,
    "is_active": true
  }
]
```

### Dynamic Telegram / UI Management
Operators can also manage mailboxes dynamically via Telegram commands or the Web UI:
- `/addemailaddress <email> <app_password> <name> [daily_limit]`
- `/listmailboxes`

Mailbox passwords saved to the database are encrypted at rest using Fernet authenticated symmetric encryption via `FIELD_ENCRYPTION_KEY`.

---

## 4. Sending Safety & Pacing

- **Dry-Run Mode (`OUTREACH_DRY_RUN=true`)**:
  All new installations default to simulation dry-run mode. Emails are generated, verified, and logged in the database without contacting real prospects.
- **Dispatch Pacing (`ENABLE_DISPATCH_PACING=true`)**:
  Applies randomized time intervals between consecutive dispatches to mimic organic human sending and satisfy ESP heuristics.
- **Daily Mailbox Ceilings (`MAX_EMAILS_PER_DAY=40`)**:
  Strictly caps the number of messages sent per mailbox in a rolling 24-hour window. Once a mailbox reaches its daily threshold, it is automatically paused until the next UTC day.

---

## 5. Inbound Reply Tracking & Webhooks

When a prospect replies to an outreach email, IntentLead AI automatically:
1. Detects and matches the thread to the corresponding `Conversation`.
2. Marks the conversation as `replied`.
3. Instantly cancels all future automated follow-up messages for that prospect.
4. Notifies the operator via Telegram and the Web Unified Inbox.

### Supported Inbound Webhooks:
- **SendGrid Inbound Parse**: POST to `/api/inbound/sendgrid`
- **Postmark Inbound Webhook**: POST to `/api/inbound/postmark`
- **Generic ESP Webhook**: POST to `/api/inbound/webhook`

Inbound endpoints enforce atomic Redis-backed replay protection, shared secret verification (`OUTREACH_WEBHOOK_SECRET`), and HTML sanitization.
