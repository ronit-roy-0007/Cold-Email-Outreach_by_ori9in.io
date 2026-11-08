import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import Business, Lead, MessageDraft
from app.services.campaigns import create_campaign
from app.services.pipeline import run_campaign


@pytest.fixture
def auth_settings():
    return Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        DISCOVERY_PROVIDER="mock",
        AGENCY_NAME="River Agency",
        AGENCY_SENDER_NAME="Jordan Reed",
        TELEGRAM_ALLOWED_USER_ID="123456789",
    )


@pytest.fixture
def client(db_session, auth_settings):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: auth_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_unauthorized_user_blocked(client):
    update = {
        "message": {
            "from": {"id": 999999999},
            "text": "/status",
        }
    }
    res = client.post("/api/orchestrator/webhooks/telegram", json=update)
    assert res.status_code == 403


def test_authorized_status_command(client):
    update = {
        "message": {
            "from": {"id": 123456789},
            "text": "/status",
        }
    }
    res = client.post("/api/orchestrator/webhooks/telegram", json=update)
    assert res.status_code == 200
    assert "reply" in res.json()


def test_findleads_command_creates_campaign(client, db_session):
    update = {
        "message": {
            "from": {"id": 123456789},
            "text": "/findleads Real Estate Agencies in Dallas, Texas 5",
        }
    }
    res = client.post("/api/orchestrator/webhooks/telegram", json=update)
    assert res.status_code == 200
    data = res.json()
    assert "Campaign Launched & Scored" in data["reply"]

    leads = db_session.query(Lead).all()
    assert len(leads) > 0


def test_callback_approval_and_idempotency(client, db_session, auth_settings):
    payload = {
        "niche": "Real Estate Agencies",
        "location": "Dallas, Texas",
        "requested_quantity": 5,
        "target_services": ["website_development"],
        "filters": {},
    }
    camp = create_campaign(db_session, payload, auth_settings)
    run_campaign(db_session, camp.id, auth_settings)

    lead = db_session.query(Lead).filter_by(campaign_id=camp.id).first()
    assert lead.outreach_status == "draft"

    # Send approve callback
    update = {
        "callback_query": {
            "from": {"id": 123456789},
            "data": f"approve:{lead.id}",
        }
    }
    res1 = client.post("/api/orchestrator/webhooks/telegram", json=update)
    assert res1.status_code == 200
    assert res1.json()["status"] == "success"

    db_session.refresh(lead)
    assert lead.outreach_status == "approved"
    assert lead.crm_stage == "approved"

    # Second click -> idempotent
    res2 = client.post("/api/orchestrator/webhooks/telegram", json=update)
    assert res2.status_code == 200
    assert res2.json()["status"] == "already_processed"


def test_pending_approvals_endpoint(client, db_session, auth_settings):
    payload = {
        "niche": "Real Estate Agencies",
        "location": "Dallas, Texas",
        "requested_quantity": 3,
        "target_services": ["website_development"],
        "filters": {},
    }
    camp = create_campaign(db_session, payload, auth_settings)
    run_campaign(db_session, camp.id, auth_settings)

    res = client.get(f"/api/orchestrator/pending-approvals?campaign_id={camp.id}")
    assert res.status_code == 200
    items = res.json()
    assert len(items) > 0
    first = items[0]
    assert "card_markdown" in first
    assert "inline_keyboard" in first
    assert "LEAD APPROVAL CARD" in first["card_markdown"]
