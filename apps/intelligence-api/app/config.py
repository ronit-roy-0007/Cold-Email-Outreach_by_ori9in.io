from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


SQLITE_WARNING = (
    "WARNING: Using SQLite because APP_ENV=development and DATABASE_URL is sqlite. "
    "PostgreSQL is the production source of truth."
)


class DatabaseConfigError(Exception):
    pass


class SecurityConfigError(Exception):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", str(Path(__file__).resolve().parent.parent / ".env")),
        extra="ignore"
    )

    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: str = "sqlite:///./intentlead.db"
    DISCOVERY_PROVIDER: str = "scrapling"
    GOOGLE_MAPS_SCRAPER_BASE_URL: str = ""
    GOOGLE_MAPS_SCRAPER_API_TOKEN: str = ""
    AGENCY_NAME: str = "IntentLead"
    AGENCY_SENDER_NAME: str = "Outreach Team"
    OUTREACH_DRY_RUN: bool = True
    USER_LLM_API_KEY: str = ""
    USER_LLM_BASE_URL: str = ""
    USER_LLM_MODEL: str = "gemini-1.5-flash"
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ALLOWED_USER_ID: str = ""
    N8N_WEBHOOK_URL: str = ""
    EMAIL_PROVIDER: str = "smtp"
    SENDER_EMAIL: str = "outreach@example.com"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    RESEND_API_KEY: str = ""
    GOOGLE_WORKSPACE_CREDENTIALS: str = ""
    AGENCY_PHYSICAL_ADDRESS: str = "100 Innovation Way, Suite 400, Wilmington, DE 19801"
    MAX_EMAILS_PER_DAY: int = 50
    UNSUBSCRIBE_BASE_URL: str = "http://localhost:8000/unsubscribe"
    UNSUBSCRIBE_SECRET: str = "intentlead-compliance-secret-key"
    MAILBOXES_FILE: str = "mailboxes.json"
    ENABLE_DISPATCH_PACING: bool = True
    API_KEY: str = ""
    CORS_ORIGINS: str = "*"
    RATE_LIMIT_PER_MINUTE: int = 120
    TELEGRAM_WEBHOOK_SECRET: str = ""
    FIELD_ENCRYPTION_KEY: str = ""
    OUTREACH_WEBHOOK_SECRET: str = ""
    RESEND_WEBHOOK_SECRET: str = ""
    MAILGUN_WEBHOOK_SIGNING_KEY: str = ""
    REDIS_URL: str = ""
    TRUSTED_PROXIES: str = "127.0.0.1,::1"


def resolve_database_url(settings: Settings) -> str:
    url = settings.DATABASE_URL
    if url.startswith("sqlite:"):
        if settings.APP_ENV != "development":
            raise DatabaseConfigError(
                "SQLite is not permitted when APP_ENV is not development"
            )
        print(SQLITE_WARNING, file=sys.stderr)
        if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
            db_path_str = url[len("sqlite:///"):]
            db_path = Path(db_path_str)
            if not db_path.is_absolute():
                base_dir = Path(__file__).resolve().parent.parent
                resolved = (base_dir / db_path).resolve()
                return f"sqlite:///{resolved.as_posix()}"
        return url
    return url


def validate_production_security(settings: Settings) -> None:
    """
    Enforces essential security controls when running in production environment.
    Fails fast at application startup if critical secrets or unsafe policies are detected.
    """
    if settings.APP_ENV == "production":
        if not settings.FIELD_ENCRYPTION_KEY or not settings.FIELD_ENCRYPTION_KEY.strip():
            raise SecurityConfigError(
                "FIELD_ENCRYPTION_KEY must be configured in production to encrypt sensitive credentials at rest."
            )
        cors_str = (settings.CORS_ORIGINS or "*").strip()
        if cors_str == "*":
            raise SecurityConfigError(
                "CORS_ORIGINS cannot be set to wildcard '*' in production. Provide an explicit comma-separated allowlist of origins."
            )
        if not settings.UNSUBSCRIBE_SECRET or settings.UNSUBSCRIBE_SECRET == "intentlead-compliance-secret-key":
            raise SecurityConfigError(
                "UNSUBSCRIBE_SECRET must be set to a secure, unique secret in production."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
