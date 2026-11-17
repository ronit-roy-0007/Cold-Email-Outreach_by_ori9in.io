# Contributing to IntentLead AI

Thank you for your interest in contributing to IntentLead AI! We welcome bug reports, feature enhancements, documentation improvements, and architectural suggestions.

---

## 1. Development Principles & Safety Rules

When contributing to IntentLead AI, strict safety rules apply:
1. **Never Send Real Cold Emails**: Keep `OUTREACH_DRY_RUN=true` at all times during local development and testing.
2. **Zero Plaintext Secrets**: Never commit real API keys, Telegram bot tokens, or private credentials. Use `.env.example` placeholders.
3. **Database Integrity**: Never modify existing Alembic migrations. Always generate a new forward migration (`alembic revision --autogenerate -m "description"`).
4. **Preserve Core Workflows**: Ensure all 15 operational workflows (A through O) and the 7-step Telegram onboarding flow continue to pass.

---

## 2. Setting Up Your Development Environment

### Prerequisites
- Python 3.12+
- Git
- Docker and Docker Compose (recommended)

### Local Setup
```bash
# 1. Clone your fork
git clone https://github.com/<your-username>/IntentLead-AI.git
cd IntentLead-AI

# 2. Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Initialize local config
cp .env.example .env
```

---

## 3. Running Regression Tests

Before submitting any code changes, ensure all tests pass:

```bash
# Run Telegram test suite
export PYTHONPATH=apps/intelligence-api  # Windows: $env:PYTHONPATH="apps/intelligence-api"
pytest apps/intelligence-api/tests/test_telegram.py

# Run Full 15-Workflow Operational Acceptance Suite
python scripts/test_operational_acceptance.py

# Run Secret Scanning Audit
python scripts/scan_tracked_secrets.py
```

---

## 4. Git Commit Conventions

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:
- `feat(scope): add new capability`
- `fix(scope): fix bug or issue`
- `docs(scope): update or add documentation`
- `test(scope): add or improve test suites`
- `refactor(scope): internal code refactor without behavior change`
- `chore(scope): update build configurations or dependencies`

---

## 5. Submitting a Pull Request

1. Create a descriptive feature branch: `git checkout -b feat/your-feature-name`.
2. Commit your changes with clear messages.
3. Push to your fork: `git push origin feat/your-feature-name`.
4. Open a Pull Request against `main`. Fill in the PR template with a summary, testing steps, and confirmation that safety rules were respected.
