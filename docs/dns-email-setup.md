# IntentLead AI — DNS & Deliverability Authentication Guide (SPF, DKIM, DMARC)

Proper DNS authentication is mandatory for cold email outreach to ensure high inbox placement, prevent spam categorization, and comply with Google and Yahoo sender requirements.

---

## 1. Required DNS Records Overview

| Record Type | Host / Name | Record Value / Target | Purpose |
|---|---|---|---|
| **SPF** | `@` | `v=spf1 include:_spf.google.com ~all` *(or provider include)* | Authorizes designated IP addresses/servers to send on behalf of your domain. |
| **DKIM** | `google._domainkey` *(or selector)* | `v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8...` | Cryptographically signs outbound messages to prove they were not modified in transit. |
| **DMARC** | `_dmarc` | `v=DMARC1; p=quarantine; pct=100; rua=mailto:dmarc@yourdomain.com` | Instructs receiving mail servers how to treat emails failing SPF or DKIM. |
| **MX** | `@` | `10 smtp.google.com` | Enables receiving prospect replies to your domain. |

---

## 2. Step-by-Step DNS Configuration

### Step A: Configure SPF (Sender Policy Framework)
- Open your DNS manager (Cloudflare, Namecheap, GoDaddy, AWS Route 53).
- Create a `TXT` record at the root domain (`@`):
  - **For Google Workspace / Gmail**:
    ```text
    v=spf1 include:_spf.google.com ~all
    ```
  - **For Resend**:
    ```text
    v=spf1 include:amazonses.com ~all
    ```
- **Rule**: Never create more than one SPF TXT record on a single domain. Combine multiple senders using `include:` statements.

### Step B: Configure DKIM (DomainKeys Identified Mail)
- In your email provider's admin console (e.g. Google Admin or Resend Dashboard), generate a 2048-bit DKIM key.
- Create a `TXT` record:
  - Name: `google._domainkey` (or provider selector)
  - Value: The public key string provided by your host.
- Wait 15–30 minutes, then click **"Start Authentication"** in your email admin panel.

### Step C: Configure DMARC
- Create a `TXT` record:
  - Name: `_dmarc` (or `_dmarc.yourdomain.com`)
  - Value:
    ```text
    v=DMARC1; p=quarantine; sp=quarantine; pct=100; rua=mailto:dmarc-reports@yourdomain.com
    ```
- Recommendation: Start with `p=none` for the first 7 days to monitor reports, then advance to `p=quarantine` or `p=reject`.

---

## 3. Dedicated Secondary Domains for Cold Outreach

Never perform cold outbound campaigns using your primary corporate domain.
1. Register 2–3 dedicated outreach domains (e.g., `getacme.com`, `acmelabs.io`).
2. Set up forwarding for HTTP web traffic to your main company website.
3. Configure dedicated mailboxes on each outreach domain.
4. Add these accounts to IntentLead AI's `mailboxes.json`.

---

## 4. Mailbox Warmup & Daily Volume Scheduling

Cold domains must undergo an incremental warmup sequence:

| Week | Max Emails Per Day / Mailbox | Spacing Delay |
|---|---|---|
| **Week 1** | 5 – 10 | 120s – 300s |
| **Week 2** | 10 – 20 | 90s – 180s |
| **Week 3** | 20 – 35 | 60s – 120s |
| **Week 4+ (Cruising)** | 40 – 50 | Pacing enabled (`ENABLE_DISPATCH_PACING=true`) |

IntentLead AI automatically enforces `MAX_EMAILS_PER_DAY=40` and `ENABLE_DISPATCH_PACING=true` to protect domain health.
