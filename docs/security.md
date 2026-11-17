# IntentLead AI — Security Architecture & Threat Model

Security is a primary design tenet of IntentLead AI. The application implements defense-in-depth protections across network, application, database, and operational boundaries.

---

## 1. Threat Mitigation Matrix

| Attack Vector | Threat Description | IntentLead AI Defense |
|---|---|---|
| **Server-Side Request Forgery (SSRF)** | Attacker inputs a malicious prospect URL pointing to AWS metadata (`169.254.169.254`) or internal LAN services (`10.0.0.0/8`, `192.168.0.0/16`). | `app/services/ssrf.py`: Resolves DNS before requesting, validates IP addresses against RFC 1918 private ranges, loopback (`127.0.0.0/8`), link-local, and cloud metadata endpoints. |
| **Credential Theft at Rest** | Database dumps or unauthorized SQL access expose mailbox SMTP passwords or API tokens. | `app/services/crypto.py`: Field-level Fernet symmetric authenticated encryption using `FIELD_ENCRYPTION_KEY`. Mailbox passwords are stored as ciphertext `gAAAAA...`. |
| **Webhook Replay Attacks** | Adversary re-sends recorded ESP webhook requests to forge unsubscribe or reply events. | `app/services/webhook_security.py`: Atomic Redis `SET key '1' EX ttl NX` deduplication with 10-minute sliding window. Fails closed in production if Redis is unreachable. |
| **Cross-Site Scripting (XSS)** | Malicious prospect replies containing `<script>` or event handlers (`onerror=...`) rendered in the operator inbox. | `app/services/inbound_service.py`: Multi-stage HTML sanitization: unescapes HTML entities, strips all dangerous tags (`<script>`, `<iframe>`, `<object>`), purges event handlers and `javascript:` URIs. |
| **SQL Injection** | SQL payload injection via lead search queries, filters, or webhook identifiers. | 100% SQLAlchemy ORM parameterized queries. Raw string concatenation is strictly prohibited across all database models and routes. |
| **IP Spoofing / Rate Limit Bypass** | Attacker spoofs `X-Forwarded-For` headers to bypass rate limits or impersonate trusted proxies. | `app/security.py`: Reverse-proxy IP validation. `X-Forwarded-For` is only honored if the immediate peer IP matches `TRUSTED_PROXIES`. |
| **Credential Leakage in Logs** | Sensitive tokens (Telegram bot token, LLM keys, webhook secrets) printed in logs or tracebacks. | `mask_sensitive` sanitization in poller, suppression of HTTP client INFO logs (`httpx`/`httpcore`), and automated secret-scanning regression tests. |

---

## 2. Production Security Hardening Checklist

When deploying to production (`APP_ENV=production`), the application enforces:
1. `FIELD_ENCRYPTION_KEY` must be configured with a 32-byte Fernet key.
2. `CORS_ORIGINS` must not be wildcard `*`.
3. `UNSUBSCRIBE_SECRET` must be set to a unique, cryptographically strong secret.
4. Database and Redis ports are bound exclusively to Docker's internal network or `127.0.0.1`.
5. Container runs as unprivileged user `appuser` (UID `10001`).
