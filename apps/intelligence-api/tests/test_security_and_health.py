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

        # 5. Sensitive outreach dispatch endpoint blocked without auth -> 401
        res_dispatch_no_auth = test_client.post(
            "/api/outreach/dispatch",
            json={"campaign_id": "00000000-0000-0000-0000-000000000000"}
        )
        assert res_dispatch_no_auth.status_code == 401

        # 6. Suppression endpoints blocked without auth -> 401
        res_suppression_no_auth = test_client.get("/api/outreach/suppression")
        assert res_suppression_no_auth.status_code == 401

        res_stats_no_auth = test_client.get("/api/outreach/stats")
        assert res_stats_no_auth.status_code == 401

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
    import hashlib
    import hmac
    import json
    from app.config import get_settings, Settings
    from app.main import app

    webhook_secret = "test-outreach-secret-1234"
    test_settings = Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        OUTREACH_WEBHOOK_SECRET=webhook_secret,
    )
    app.dependency_overrides[get_settings] = lambda: test_settings

    try:
        # Register a bounce via signed webhook
        bounce_payload = {
            "email": "victim_bounced@example.com",
            "event": "bounce",
            "reason": "550 5.1.1 User unknown",
        }
        raw_bounce = json.dumps(bounce_payload).encode("utf-8")
        sig_bounce = hmac.new(webhook_secret.encode("utf-8"), raw_bounce, hashlib.sha256).hexdigest()

        r_bounce = client.post(
            "/api/outreach/webhook/event",
            content=raw_bounce,
            headers={"content-type": "application/json", "x-signature-sha256": sig_bounce},
        )
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
            "reason": "Spam flag by recipient",
        }
        raw_complaint = json.dumps(complaint_payload).encode("utf-8")
        sig_complaint = hmac.new(webhook_secret.encode("utf-8"), raw_complaint, hashlib.sha256).hexdigest()

        r_complaint = client.post(
            "/api/outreach/webhook/event",
            content=raw_complaint,
            headers={"content-type": "application/json", "x-signature-sha256": sig_complaint},
        )
        assert r_complaint.status_code == 200
        assert r_complaint.json()["status"] in ("success", "duplicate")
    finally:
        app.dependency_overrides.clear()
