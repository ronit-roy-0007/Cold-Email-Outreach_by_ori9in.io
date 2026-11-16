import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.models import Business, Campaign, DailyDispatchQuota, Lead, MessageDraft, OutboundMessage, SuppressionEntry
from app.services.email_compliance import (
    build_unsubscribe_url,
    format_compliant_email_body,
    generate_unsubscribe_token,
    get_unsubscribe_headers,
    verify_unsubscribe_token,
)
from app.services.email_dispatcher import (
    dispatch_approved_campaign_leads,
    dispatch_single_email,
    send_google_workspace_email,
    send_resend_email,
    send_smtp_email,
)
from app.services.email_gate import (
    add_to_suppression_list,
    check_and_increment_daily_quota,
    check_domain_mx,
    is_suppressed,
    preflight_deliverability_gate,
    validate_email_syntax,
)


from app.db import get_session
from app.config import get_settings


@pytest.fixture
def email_settings():
    return Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        OUTREACH_DRY_RUN=True,
        EMAIL_PROVIDER="smtp",
        SENDER_EMAIL="outreach@ori9in.io",
        AGENCY_NAME="ori9in.io",
        AGENCY_SENDER_NAME="Ronit",
        AGENCY_PHYSICAL_ADDRESS="100 Innovation Way, Suite 400, Wilmington, DE 19801",
        MAX_EMAILS_PER_DAY=5,
        UNSUBSCRIBE_BASE_URL="https://ori9in.io/unsubscribe",
        UNSUBSCRIBE_SECRET="test-secret-key-12345",
        SMTP_HOST="smtp.test.local",
        SMTP_PORT=587,
        SMTP_USER="user",
        SMTP_PASSWORD="pass",
    )


@pytest.fixture
def client(db, email_settings):
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_settings] = lambda: email_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_email_syntax_validation():
    assert validate_email_syntax("hello@example.com") is True
    assert validate_email_syntax("user.name+tag@domain.co.uk") is True
    assert validate_email_syntax("invalid-email") is False
    assert validate_email_syntax("@no-user.com") is False
    assert validate_email_syntax("") is False


def test_domain_mx_preflight_gate(db):
    # Test whitelisted domains
    valid, err = check_domain_mx("example.com")
    assert valid is True
    assert err is None

    # Custom resolver mock for testing valid MX
    def mock_valid_resolver(domain):
        return ["mail.valid-domain.com"]

    valid, err = preflight_deliverability_gate("contact@valid-domain.com", db=db, resolver_fn=mock_valid_resolver)
    assert valid is True
    assert err is None

    # Custom resolver mock for failing MX
    def mock_invalid_resolver(domain):
        return []

    valid, err = preflight_deliverability_gate("contact@fake-nonexistent.xyz", db=db, resolver_fn=mock_invalid_resolver)
    assert valid is False
    assert "no_mx_records" in err


def test_suppression_list_gate(db):
    email = "unsub@company.com"
    assert is_suppressed(db, email) is False

    add_to_suppression_list(db, email, reason="unsubscribe")
    assert is_suppressed(db, email) is True
    assert is_suppressed(db, "UNSUB@company.com") is True  # Case insensitive

    valid, reason = preflight_deliverability_gate(email, db=db)
    assert valid is False
    assert reason == "recipient_on_suppression_list"


def test_daily_pacing_and_throttling(db):
    mailbox = "agent@ori9in.io"
    max_quota = 3

    # Send 3 times in live mode
    for i in range(3):
        allowed, count = check_and_increment_daily_quota(db, mailbox, max_daily=max_quota, dry_run=False)
        assert allowed is True
        assert count == i + 1

    # 4th time should be rejected by quota gate
    allowed, count = check_and_increment_daily_quota(db, mailbox, max_daily=max_quota, dry_run=False)
    assert allowed is False
    assert count == 3


def test_can_spam_compliance_formatting(email_settings):
    body = "Hi, we saw your Google Maps listing and can automate your lead flow."
    unsub_url = build_unsubscribe_url("test@client.com", email_settings.UNSUBSCRIBE_SECRET, email_settings.UNSUBSCRIBE_BASE_URL)
    
    formatted = format_compliant_email_body(
        body=body,
        agency_name="ori9in.io",
        sender_name="Ronit",
        agency_address=email_settings.AGENCY_PHYSICAL_ADDRESS,
        unsubscribe_url=unsub_url,
    )

    assert "100 Innovation Way, Suite 400, Wilmington, DE 19801" in formatted
    assert "Ronit | ori9in.io" in formatted
    assert unsub_url in formatted

    headers = get_unsubscribe_headers(unsub_url)
    assert headers["List-Unsubscribe"] == f"<{unsub_url}>"
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_operator_safety_toggle_dry_run(db, email_settings):
    email_settings.OUTREACH_DRY_RUN = True

    camp = Campaign(
        niche="Real Estate",
        location="Delhi",
        requested_quantity=1,
        target_services=["ai_chatbot"],
        filters={},
        provider="live",
        status="completed",
    )
    db.add(camp)
    db.flush()

    biz = Business(
        identity_key="test-key-1",
        name="Apex Properties",
        email="info@example.com",
        discovery_source="google_maps",
        source_fields={},
    )
    db.add(biz)
    db.flush()

    lead = Lead(
        campaign_id=camp.id,
        business_id=biz.id,
        overall_score=85,
        priority="A",
        confidence="high",
        outreach_status="approved",
    )
    db.add(lead)
    db.flush()

    # Dry run dispatch should simulate and NOT call smtplib
    with patch("smtplib.SMTP") as mock_smtp:
        outbound = dispatch_single_email(
            db=db,
            lead=lead,
            biz=biz,
            settings=email_settings,
            resolver_fn=lambda d: ["mx.example.com"],
        )
        mock_smtp.assert_not_called()

    assert outbound.status == "simulated"
    assert lead.outreach_status == "simulated"
    assert outbound.recipient_email == "info@example.com"
    assert "Dry-run simulation" in outbound.error_message


def test_live_dispatch_via_smtp(db, email_settings):
    email_settings.OUTREACH_DRY_RUN = False
    email_settings.EMAIL_PROVIDER = "smtp"

    camp = Campaign(
        niche="Dentists",
        location="London",
        requested_quantity=1,
        target_services=["ai_chatbot"],
        filters={},
        provider="live",
        status="completed",
    )
    db.add(camp)
    biz = Business(
        identity_key="test-key-2",
        name="London Dental",
        email="contact@example.com",
        discovery_source="google_maps",
        source_fields={},
    )
    db.add(biz)
    db.flush()

    lead = Lead(
        campaign_id=camp.id,
        business_id=biz.id,
        overall_score=90,
        priority="A",
        confidence="high",
        outreach_status="approved",
    )
    db.add(lead)
    db.flush()

    # Mock SMTP server
    mock_server = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_server):
        outbound = dispatch_single_email(
            db=db,
            lead=lead,
            biz=biz,
            settings=email_settings,
            resolver_fn=lambda d: ["mx.example.com"],
        )
        mock_server.send_message.assert_called_once()
        mock_server.quit.assert_called_once()

    assert outbound.status == "sent"
    assert lead.outreach_status == "sent"
    assert outbound.dispatched_at is not None


def test_live_dispatch_via_resend(db, email_settings):
    email_settings.OUTREACH_DRY_RUN = False
    email_settings.EMAIL_PROVIDER = "resend"
    email_settings.RESEND_API_KEY = "re_test_api_key_12345"

    camp = Campaign(
        niche="Gyms",
        location="Miami",
        requested_quantity=1,
        target_services=["ai_chatbot"],
        filters={},
        provider="live",
        status="completed",
    )
    db.add(camp)
    biz = Business(
        identity_key="test-key-3",
        name="Miami Fitness",
        email="hello@example.com",
        discovery_source="google_maps",
        source_fields={},
    )
    db.add(biz)
    db.flush()

    lead = Lead(
        campaign_id=camp.id,
        business_id=biz.id,
        overall_score=88,
        priority="A",
        confidence="high",
        outreach_status="approved",
    )
    db.add(lead)
    db.flush()

    mock_resp = MagicMock(status_code=200, json=lambda: {"id": "resend-msg-123"})
    with patch("httpx.post", return_value=mock_resp) as mock_post:
        outbound = dispatch_single_email(
            db=db,
            lead=lead,
            biz=biz,
            settings=email_settings,
            resolver_fn=lambda d: ["mx.example.com"],
        )
        mock_post.assert_called_once()

    assert outbound.status == "sent"
    assert lead.outreach_status == "sent"


def test_unsubscribe_endpoint_and_suppression(client, db, email_settings):
    email = "client@example.com"
    token = generate_unsubscribe_token(email, email_settings.UNSUBSCRIBE_SECRET)

    # 1. Invalid token should return 400
    res_bad = client.get(f"/api/outreach/unsubscribe?email={email}&token=wrongtoken")
    assert res_bad.status_code == 400

    # 2. Valid token should unsubscribe and render HTML confirmation
    res_ok = client.get(f"/api/outreach/unsubscribe?email={email}&token={token}")
    assert res_ok.status_code == 200
    assert "Unsubscribed Successfully" in res_ok.text

    # 3. Verify email is now in suppression database
    assert is_suppressed(db, email) is True


def test_outreach_api_endpoints(client, db, email_settings):
    camp = Campaign(
        niche="Real Estate",
        location="Delhi",
        requested_quantity=2,
        target_services=["ai_chatbot"],
        filters={},
        provider="live",
        status="completed",
    )
    db.add(camp)
    db.flush()

    biz1 = Business(identity_key="b1", name="Biz 1", email="one@example.com", discovery_source="google_maps", source_fields={})
    biz2 = Business(identity_key="b2", name="Biz 2", email="two@example.com", discovery_source="google_maps", source_fields={})
    db.add_all([biz1, biz2])
    db.flush()

    l1 = Lead(campaign_id=camp.id, business_id=biz1.id, overall_score=85, priority="A", confidence="high", outreach_status="approved")
    l2 = Lead(campaign_id=camp.id, business_id=biz2.id, overall_score=82, priority="A", confidence="high", outreach_status="approved")
    db.add_all([l1, l2])
    db.commit()

    # 1. Dispatch via API
    res = client.post(
        "/api/outreach/dispatch",
        json={"campaign_id": str(camp.id)},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_candidates"] == 2
    assert data["simulated"] == 2

    # 2. Stats endpoint
    stats_res = client.get("/api/outreach/stats")
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert stats["total_dispatches"] == 2
    assert stats["status_breakdown"].get("simulated") == 2
