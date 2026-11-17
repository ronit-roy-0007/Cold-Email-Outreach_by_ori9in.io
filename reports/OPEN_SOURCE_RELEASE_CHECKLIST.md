# IntentLead AI — Open-Source Release Checklist & Sign-Off

**Release Version:** v0.2.1-oss  
**Release Date:** 2026-11-17  
**Git Baseline:** `26098c2` + Master Remediation Commit  
**Release Manager:** Principal Open-Source Release Manager & Software Architect  

---

## 1. Master Release Verification Checklist

### A. Licensing, Attribution & Community Standards
- [x] **Open-Source License**: Apache License 2.0 confirmed in root [`LICENSE`](LICENSE).
- [x] **Attribution Notice**: Required third-party copyright and open-source credits documented in [`NOTICE`](NOTICE).
- [x] **Code of Conduct**: Contributor Covenant standard documented in [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
- [x] **Contribution Guidelines**: Development workflow, PR guidelines, and testing requirements in [`CONTRIBUTING.md`](CONTRIBUTING.md).
- [x] **Security Policy**: Vulnerability reporting protocols documented in [`SECURITY.md`](SECURITY.md).

### B. Secret Hygiene & Repository Cleansing
- [x] **Tracked Secret Scan**: Automated scan across all 185 tracked repository files confirmed **0 leaks**.
- [x] **Git History Audit**: Deep commit log scan across entire Git tree confirmed **0 credential exposures**.
- [x] **Hardened `.gitignore`**: Excludes all `.env`, `.env.*` (except `.env.example`), `mailboxes.json`, `*.pem`, `*.key`, `*.sqlite`, `*.db`, caches, and backups.
- [x] **Clean Templates**: `.env.example`, `.env.staging`, and `mailboxes.example.json` contain strictly non-sensitive placeholder tokens.

### C. Authentication & Access Control
- [x] **Dashboard Route Protection**: All 22 dashboard routes require verified operator authentication (`require_operator`).
- [x] **Login Interface**: Styled MonkeyCode/Obsidian `/login` page with secure form submission.
- [x] **Cryptographic Password Hashing**: PBKDF2-HMAC-SHA256 (600,000 iterations, 16-byte random salt, constant-time compare).
- [x] **Session Cookie Security**: 256-bit URL-safe tokens stored as SHA-256 hashes; cookies configured with `HttpOnly=True`, `SameSite=Lax`, `Secure=True` in production.
- [x] **Brute-Force Rate Limiting**: 5 failed login attempts per 15 minutes per IP triggers HTTP 429.
- [x] **Idempotent Operator Bootstrap**: `ensure_bootstrap_operator` and CLI script [`scripts/bootstrap_operator.py`](scripts/bootstrap_operator.py).
- [x] **Spoofing Immunity**: Eliminated `Sec-Fetch-Site` and `Referer` pseudo-authentication headers.
- [x] **Fail-Closed API Key Auth**: Production fails closed if `API_KEY` is missing, < 16 characters, or a default placeholder.

### D. Database & Migration Integrity
- [x] **Alembic Migration Chain**: Linear revision sequence `0001` -> `0002` -> `0003` -> `0004` -> `0005` -> `0006_operator_auth`.
- [x] **Fail-Closed Container Entrypoint**: Replaced swallowed warning with strict `alembic upgrade head || exit 1`.
- [x] **Pre-Flight Database Connectivity**: 30-second active connection poll before DDL execution.
- [x] **Production Multi-Worker Safety**: `Base.metadata.create_all` restricted to development only.

### E. Functional Workflows & User Experience
- [x] **Stealth Discovery & Crawling**: Google Maps + Scrapling with multi-key deduplication.
- [x] **Evidence-Based Intent Scoring**: 0–100 rubric with benchmark thresholds and audited evidence claims.
- [x] **AI Draft Studio**: Manual on-demand generation, lead-specific Gemini grounding, drawer preview, and persistent storage.
- [x] **Telegram Operator Bot**: Complete 7-step onboarding flow with Question 6 template choice (YES/NO) and Question 7 follow-up sequence.
- [x] **Multi-Touch Follow-Up Engine**: Calendar and business-day schedules, automatic stop on replies or suppression.
- [x] **Multi-Mailbox Pooling**: Round-robin distribution, daily caps (40/day), Fernet encryption.

### F. Safety Invariants & Regulatory Compliance
- [x] **Gate 0 Human Approval**: Mandatory `lead.outreach_status == 'approved'` required before any email dispatch.
- [x] **Dry-Run Switch**: `OUTREACH_DRY_RUN=True` default cannot be bypassed from Telegram, Web UI, or API without explicit env change.
- [x] **CAN-SPAM / GDPR**: Postal address footers, HMAC-signed one-click unsubscribe URLs, permanent suppression lists.

### G. Docker Portability & Documentation
- [x] **Supported Platforms**: Windows 10/11, Linux, macOS (Apple Silicon + Intel), Ubuntu VPS.
- [x] **Non-Root Containers**: Unprivileged user `appuser` (UID 10001).
- [x] **Network Isolation**: PostgreSQL and Redis publish zero host ports in production.
- [x] **Full Documentation Suite**: Universal installation, OS-specific guides, VPS deployment, observability, backup/restore.

---
*Release checklist certified for production open-source distribution.*
