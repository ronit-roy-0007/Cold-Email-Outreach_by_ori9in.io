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
| **Unauthorized Dashboard Access** | Unauthorized network users browsing to the web dashboard on port 8000. | `app/security.py`: Mandatory `require_operator` dependency on all dashboard routes. Unauthenticated requests redirect to `/login` with HttpOnly, SameSite=Lax, and Secure session cookies. |
| **Credential Brute-Force** | Adversary attempts dictionary or brute-force attacks against operator credentials. | `app/services/auth.py`: Cryptographic PBKDF2-HMAC-SHA256 password hashing (600,000 iterations, 16-byte random salt, constant-time compare) and sliding-window rate limiting (max 5 failed attempts per 15 minutes per IP, returning HTTP 429). |
| **Cross-Site Request Forgery (CSRF)** | Malicious third-party site tricks operator browser into executing state-changing actions. | Session-bound HMAC-SHA256 CSRF tokens validated against operator sessions on state-changing requests. |
| **DoS via Payload Flooding** | Attacker floods the API with large payloads to exhaust memory or worker buffers. | Request body size limit middleware enforcing max 2MB (`MAX_REQUEST_BODY_BYTES`) with immediate HTTP 413 rejection. |

---

## 2. Production Security Hardening Checklist

When deploying to production (`APP_ENV=production`), the application enforces:
1. `FIELD_ENCRYPTION_KEY` must be configured with a 32-byte Fernet key.
2. `API_KEY` must be configured with at least 16 characters and cannot be a default placeholder.
3. `CORS_ORIGINS` must not be wildcard `*`.
4. `UNSUBSCRIBE_SECRET` must be set to a unique, cryptographically strong secret.
5. Database and Redis ports are bound exclusively to Docker's internal network or `127.0.0.1`.
6. Container runs as unprivileged user `appuser` (UID `10001`).
7. Operator credentials must be bootstrapped via `BOOTSTRAP_OPERATOR_PASSWORD` or CLI.
