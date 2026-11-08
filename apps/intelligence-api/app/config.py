from __future__ import annotations

import sys
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


SQLITE_WARNING = (
    "WARNING: Using SQLite because APP_ENV=development and DATABASE_URL is sqlite. "
    "PostgreSQL is the production source of truth."
)


class DatabaseConfigError(Exception):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: str = "postgresql://intentlead:change-me@localhost:5432/intentlead"
    DISCOVERY_PROVIDER: str = "mock"
    GOOGLE_MAPS_SCRAPER_BASE_URL: str = ""
    GOOGLE_MAPS_SCRAPER_API_TOKEN: str = ""
    AGENCY_NAME: str = ""
    AGENCY_SENDER_NAME: str = ""
    OUTREACH_DRY_RUN: bool = True
    USER_LLM_API_KEY: str = ""
    USER_LLM_BASE_URL: str = ""
    USER_LLM_MODEL: str = ""


def resolve_database_url(settings: Settings) -> str:
    url = settings.DATABASE_URL
    if url.startswith("sqlite:"):
        if settings.APP_ENV != "development":
            raise DatabaseConfigError(
                "SQLite is not permitted when APP_ENV is not development"
            )
        print(SQLITE_WARNING, file=sys.stderr)
        return url
    return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
