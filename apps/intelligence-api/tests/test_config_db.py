import os
import pytest
from app.config import Settings, DatabaseConfigError, resolve_database_url, SQLITE_WARNING


def test_postgres_url_unchanged_in_development():
    s = Settings(APP_ENV="development", DATABASE_URL="postgresql://intentlead:x@localhost:5432/intentlead")
    assert resolve_database_url(s) == s.DATABASE_URL


def test_sqlite_allowed_only_in_development(capsys):
    s = Settings(APP_ENV="development", DATABASE_URL="sqlite:///./data/dev.db")
    assert resolve_database_url(s).startswith("sqlite:")
    err = capsys.readouterr().err
    assert "WARNING: Using SQLite" in err
    assert "PostgreSQL is the production source of truth" in err


def test_sqlite_rejected_when_not_development():
    s = Settings(APP_ENV="production", DATABASE_URL="sqlite:///./data/dev.db")
    with pytest.raises(DatabaseConfigError, match="SQLite"):
        resolve_database_url(s)


def test_agency_identity_defaults_empty():
    s = Settings()
    assert s.AGENCY_NAME == ""
    assert s.AGENCY_SENDER_NAME == ""


def test_outreach_dry_run_defaults_true():
    s = Settings()
    assert s.OUTREACH_DRY_RUN is True
