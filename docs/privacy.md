# IntentLead AI — Privacy & Regulatory Compliance Guide

IntentLead AI is designed to help B2B agencies and growth teams operate fully compliant cold email and lead generation programs under the CAN-SPAM Act (US), GDPR (EU), CASL (Canada), and Privacy Act (Australia).

---

## 1. Compliance Requirements Matrix

| Regulatory Requirement | Legal Basis | IntentLead AI Implementation |
|---|---|---|
| **Clear Sender Identification** | CAN-SPAM § 5(a)(1) | Outbound emails include verified "From" name and mailbox matching agency sender profile. |
| **Non-Deceptive Subject Lines** | CAN-SPAM § 5(a)(2) | Templates and AI generators are constrained to honest, business-relevant subject lines. |
| **Physical Postal Address** | CAN-SPAM § 5(a)(5)(A) | `AGENCY_PHYSICAL_ADDRESS` is automatically rendered into every outbound email footer. |
| **One-Click Opt-Out / Unsubscribe** | CAN-SPAM § 5(a)(5)(B), GDPR Art. 21 | Every message contains an HMAC-signed one-click unsubscribe URL. Clicking instantly suppresses the contact. |
| **Permanent Suppression Enforcement** | GDPR Art. 17 / CAN-SPAM | Once an address is added to `SuppressionEntry`, all future dispatches and scheduled follow-ups are permanently blocked at Gate 0. |
| **Data Sovereignty & Local Storage** | GDPR Art. 44 | All prospect data, audit logs, and lead intelligence remain strictly on your self-hosted infrastructure. Zero phone-home telemetry. |

---

## 2. Managing the Suppression List

### Automatic Suppression
An email address is automatically added to the suppression list when:
1. The prospect clicks the one-click unsubscribe link.
2. The prospect sends a reply containing opt-out intent (e.g., *"Please unsubscribe me"*, *"Remove me from your list"*).
3. The mailbox provider returns a hard bounce or spam complaint webhook.

### Manual Suppression via UI or API
- **Web UI**: Navigate to `/suppression` in the dashboard, click **"Add Suppression"**, and enter the email address or domain.
- **REST API**:
  ```bash
  curl -X POST http://localhost:8000/api/outreach/suppression \
    -H "Content-Type: application/json" \
    -d '{"email": "prospect@competitor.com", "reason": "competitor_exclusion"}'
  ```

---

## 3. Data Retention & Erasure (Right to Be Forgotten)

Operators can purge historical lead records or audit traces via the database CLI or administrative API. Purging a lead automatically purges associated message drafts, reconnaissance records, and contact records while maintaining the suppression record to prevent accidental future outreach.
