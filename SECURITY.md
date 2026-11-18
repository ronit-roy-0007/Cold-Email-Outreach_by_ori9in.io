# Security Policy

The IntentLead AI maintainers and community take security vulnerabilities seriously. We appreciate your efforts to responsibly disclose any findings.

---

## 1. Supported Versions

We provide security patches for the following versions:

| Version | Supported | Status |
|---|---|---|
| `0.3.x` | :white_check_mark: | Current Release Branch |
| `0.2.x` | :white_check_mark: | Maintenance |
| `< 0.2.0` | :x: | End of Life / Deprecated |

---

## 2. Reporting a Vulnerability

**DO NOT report security issues via public GitHub issues, discussions, or pull requests.**

If you discover a security vulnerability in IntentLead AI:
1. Send an email to **`security@intentlead.ai`** (or your designated security contact).
2. Include:
   - A detailed description of the vulnerability.
   - Affected files and components.
   - Step-by-step reproduction instructions or proof-of-concept.
   - Impact assessment (e.g. SSRF, secret disclosure, SQL injection, replay attack).
3. We will acknowledge receipt of your vulnerability report within **48 hours** and provide an initial severity assessment.
4. We request that you maintain confidentiality until an official fix is released.

---

## 3. Scope & Rules of Engagement

- **In-Scope**:
  - Server-Side Request Forgery (SSRF) bypasses in web reconnaissance.
  - Credential or secret leakage in logs, error tracebacks, or database state.
  - Webhook authentication bypasses or replay attacks.
  - SQL injection or cross-site scripting (XSS) vulnerabilities.
  - Authentication or authorization bypasses in API routes or Telegram controls.

- **Out-of-Scope**:
  - Denial of Service (DoS/DDoS) attacks against local development instances.
  - Social engineering against project maintainers.
  - Issues present solely in third-party services (e.g. Telegram Bot API, Google Gemini API).

---

## 4. Coordinated Disclosure Process

1. **Triage**: Maintainers verify and reproduce the reported issue within 48 hours.
2. **Patch Development**: A fix is developed in a private security branch and verified against regression suites.
3. **Release**: A security advisory and patched release are published simultaneously.
4. **Credit**: The researcher will be acknowledged in release notes and the project advisory (unless anonymity is requested).
