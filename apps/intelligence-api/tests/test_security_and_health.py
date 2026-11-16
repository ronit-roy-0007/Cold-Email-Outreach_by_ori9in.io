import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import SuppressionEntry
from app.security import InMemoryRateLimiter, rate_limiter


@pytest.fixture
def auth_required_settings():
    return Settings(
        APP_ENV="production",
        DATABASE_URL="sqlite:///:memory:",
        DISCOVERY_PROVIDER="mock",
        AGENCY_NAME="Ori9in Secure",
        AGENCY_SENDER_NAME="Ronit",
        API_KEY="super-secret-production-key",
        RATE_LIMIT_PER_MINUTE=100,
        OUTREACH_DRY_RUN=True,
    )


def test_health_probes(client):
    res_live = client.get("/health/live")
    assert res_live.status_code == 200
    assert res_live.json()["status"] == "ok"

    res_ready = client.get("/health/ready")
    assert res_ready.status_code == 200
    data = res_ready.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"


def test_api_key_auth_enforcement(db_session, auth_required_settings):
    rate_limiter.reset()
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: auth_required_settings

    with TestClient(app) as test_client:
        # 1. No credentials -> 401
        res_no_auth = test_client.get("/api/campaigns")
        assert res_no_auth.status_code == 401

        # 2. Invalid API Key -> 401
        res_bad_auth = test_client.get(
            "/api/campaigns",
            headers={"X-API-Key": "invalid-token"}
        )
        assert res_bad_auth.status_code == 401

        # 3. Valid X-API-Key header -> 200
        res_good_header = test_client.get(
            "/api/campaigns",
            headers={"X-API-Key": "super-secret-production-key"}
        )
        assert res_good_header.status_code == 200

        # 4. Valid Bearer Token in Authorization header -> 200
        res_good_bearer = test_client.get(
            "/api/campaigns",
            headers={"Authorization": "Bearer super-secret-production-key"}
        )
        assert res_good_bearer.status_code == 200

    app.dependency_overrides.clear()


def test_in_memory_rate_limiter():
    limiter = InMemoryRateLimiter()
    ip = "192.168.1.100"

    # Allow up to 3 requests in 10s window
    assert limiter.is_allowed(ip, max_requests=3, window_seconds=10) is True
    assert limiter.is_allowed(ip, max_requests=3, window_seconds=10) is True
    assert limiter.is_allowed(ip, max_requests=3, window_seconds=10) is True
    # 4th request must be rejected
    assert limiter.is_allowed(ip, max_requests=3, window_seconds=10) is False


def test_compliance_webhook_bounce_and_complaint(client, db_session):
    # Register a bounce via webhook
    bounce_payload = {
        "email": "victim_bounced@example.com",
        "event": "bounce",
        "reason": "550 5.1.1 User unknown"
    }
    r_bounce = client.post("/api/outreach/webhook/event", json=bounce_payload)
    assert r_bounce.status_code == 200
    assert r_bounce.json()["status"] == "success"
    assert r_bounce.json()["suppression_reason"] == "hard_bounce"

    # Verify database entry created in suppression_list
    entry = db_session.query(SuppressionEntry).filter_by(email="victim_bounced@example.com").first()
    assert entry is not None
    assert entry.reason == "hard_bounce"

    # Register duplicate complaint -> should handle idempotently
    complaint_payload = {
        "email": "victim_bounced@example.com",
        "event": "complaint",
        "reason": "Spam flag by recipient"
    }
    r_complaint = client.post("/api/outreach/webhook/event", json=complaint_payload)
    assert r_complaint.status_code == 200
    assert r_complaint.json()["status"] == "success"
