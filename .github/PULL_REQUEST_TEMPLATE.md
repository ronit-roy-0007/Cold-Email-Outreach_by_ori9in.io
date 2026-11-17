## Description
Brief summary of the changes made and the problem being solved.

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Security hardening

## Safety & Compliance Checklist
- [ ] `OUTREACH_DRY_RUN=true` remains default; no real prospect emails were dispatched during testing.
- [ ] Zero real credentials, tokens, or private secrets were committed.
- [ ] Run `python scripts/scan_tracked_secrets.py` (0 violations found).
- [ ] Database migration history preserved (no existing migration files modified).
- [ ] Ran automated tests:
  - [ ] `pytest apps/intelligence-api/tests/test_telegram.py`
  - [ ] `python scripts/test_operational_acceptance.py`
  - [ ] `python scripts/verify_telegram_runtime_requirements.py`
