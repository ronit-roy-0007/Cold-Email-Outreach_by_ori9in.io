import os

os.environ["APP_ENV"] = "development"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["AGENCY_NAME"] = ""
os.environ["AGENCY_SENDER_NAME"] = ""
os.environ["DISCOVERY_PROVIDER"] = "mock"
os.environ["OUTREACH_DRY_RUN"] = "true"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import Base


@pytest.fixture
def auth_settings():
    return Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        DISCOVERY_PROVIDER="mock",
        AGENCY_NAME="River Agency",
        AGENCY_SENDER_NAME="Jordan Reed",
        TELEGRAM_ALLOWED_USER_ID="123456789",
        OUTREACH_DRY_RUN=True,
    )


@pytest.fixture
def client(db_session, auth_settings):
    from app.services.auth import ensure_bootstrap_operator, create_operator_session
    operator = ensure_bootstrap_operator(db_session, auth_settings)
    session_rec, raw_token = create_operator_session(db_session, operator, max_age_seconds=86400)

    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: auth_settings
    with TestClient(app) as test_client:
        test_client.cookies.set(auth_settings.SESSION_COOKIE_NAME, raw_token)
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def db(db_session: Session) -> Session:
    return db_session


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
