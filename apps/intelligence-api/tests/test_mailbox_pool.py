import json
import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import Business, Campaign, DailyDispatchQuota, Lead, MailboxAccount
from app.services.email_dispatcher import dispatch_approved_campaign_leads
from app.services.mailbox_pool import (
    MailboxConfig,
    add_mailbox_account,
    get_next_available_mailbox,
    get_pool_status,
    get_today_str,
    load_mailbox_pool,
    remove_mailbox_account,
)


@pytest.fixture
def auth_settings():
    return Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        OUTREACH_DRY_RUN=True,
        EMAIL_PROVIDER="google_workspace",
        AGENCY_NAME="ori9in.io",
        AGENCY_SENDER_NAME="Roy",
        MAX_EMAILS_PER_DAY=50,
        TELEGRAM_ALLOWED_USER_ID="123456789",
        MAILBOXES_FILE="non_existent_test_mailboxes.json",
    )


@pytest.fixture
def client(db_session, auth_settings):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: auth_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_mailbox_pool_crud(db_session):
    acc = add_mailbox_account(db_session, "test1@gmail.com", "pass1234", sender_name="Roy", daily_limit=50)
    assert acc.email == "test1@gmail.com"
    assert acc.daily_limit == 50
    assert acc.is_active is True

    # List status
    settings = Settings(APP_ENV="development", DATABASE_URL="sqlite:///:memory:")
    statuses = get_pool_status(db_session, settings)
    found = [s for s in statuses if s["email"] == "test1@gmail.com"]
    assert len(found) == 1
    assert found[0]["daily_limit"] == 50
    assert found[0]["sent_today"] == 0

    # Remove
    ok = remove_mailbox_account(db_session, "test1@gmail.com")
    assert ok is True
    assert db_session.get(MailboxAccount, acc.id).is_active is False


def test_round_robin_rotation(db_session):
    pool = [
        MailboxConfig(email="box1@gmail.com", password="p1", daily_limit=2),
        MailboxConfig(email="box2@gmail.com", password="p2", daily_limit=2),
        MailboxConfig(email="box3@gmail.com", password="p3", daily_limit=2),
    ]

    current_idx = 0

    # Lead 1 -> Box 1
    m1, current_idx = get_next_available_mailbox(pool, db_session, current_idx)
    assert m1.email == "box1@gmail.com"
    assert current_idx == 1

    # Lead 2 -> Box 2
    m2, current_idx = get_next_available_mailbox(pool, db_session, current_idx)
    assert m2.email == "box2@gmail.com"
    assert current_idx == 2

    # Lead 3 -> Box 3
    m3, current_idx = get_next_available_mailbox(pool, db_session, current_idx)
    assert m3.email == "box3@gmail.com"
    assert current_idx == 0

    # Lead 4 -> Box 1 again
    m4, current_idx = get_next_available_mailbox(pool, db_session, current_idx)
    assert m4.email == "box1@gmail.com"


def test_automatic_quota_protection_skips_exhausted(db_session):
    today = get_today_str()
    # Box 1 has already sent 50/50 today
    db_session.add(DailyDispatchQuota(sender_mailbox="box1@gmail.com", dispatch_date=today, count=50))
    # Box 2 has sent 10/50 today
    db_session.add(DailyDispatchQuota(sender_mailbox="box2@gmail.com", dispatch_date=today, count=10))
    db_session.flush()

    pool = [
        MailboxConfig(email="box1@gmail.com", password="p1", daily_limit=50),
        MailboxConfig(email="box2@gmail.com", password="p2", daily_limit=50),
    ]

    # Starting at index 0 (Box 1) -> should skip Box 1 because it's at 50/50, and pick Box 2
    selected, next_idx = get_next_available_mailbox(pool, db_session, current_idx=0)
    assert selected is not None
    assert selected.email == "box2@gmail.com"

    # Now make Box 2 hit 50 as well
    q2 = db_session.query(DailyDispatchQuota).filter_by(sender_mailbox="box2@gmail.com").first()
    q2.count = 50
    db_session.flush()

    # Now all mailboxes are exhausted -> returns None
    selected, next_idx = get_next_available_mailbox(pool, db_session, current_idx=0)
    assert selected is None


def test_batch_dispatch_distributes_across_mailboxes(db_session, auth_settings):
    camp = Campaign(
        niche="Real Estate",
        location="Delhi",
        requested_quantity=3,
        target_services=["ai_chatbot"],
        filters={},
        provider="live",
        status="completed",
    )
    db_session.add(camp)
    db_session.flush()

    # Register 2 mailboxes in database
    add_mailbox_account(db_session, "alpha@gmail.com", "pass1", sender_name="Roy", daily_limit=50)
    add_mailbox_account(db_session, "beta@gmail.com", "pass2", sender_name="Roy", daily_limit=50)

    # Add 3 leads
    for i in range(3):
        biz = Business(identity_key=f"biz-{i}", name=f"Biz {i}", email=f"client{i}@example.com", discovery_source="google_maps", source_fields={})
        db_session.add(biz)
        db_session.flush()
        lead = Lead(campaign_id=camp.id, business_id=biz.id, overall_score=85, priority="A", confidence="high", outreach_status="approved")
        db_session.add(lead)
    db_session.commit()

    # Dispatch in dry-run
    res = dispatch_approved_campaign_leads(
        db=db_session,
        campaign_id=camp.id,
        settings=auth_settings,
        resolver_fn=lambda d: ["mx.example.com"],
    )

    assert res["total_candidates"] == 3
    assert res["simulated"] == 3
    # Check that both mailboxes were utilized in rotation
    senders = [r["sender_mailbox"] for r in res["records"]]
    assert "alpha@gmail.com" in senders
    assert "beta@gmail.com" in senders


def test_telegram_mailbox_commands(client, db_session):
    # 1. Blocked without /settings first
    r_blocked = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "/addemailaddress testfail@gmail.com wrongpass Roy"}
    })
    assert r_blocked.status_code == 200
    assert "Settings Mode Required" in r_blocked.json()["reply"]

    # 2. Enter /settings first
    r_settings = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "/settings"}
    })
    assert r_settings.status_code == 200
    assert "System Settings & Mailbox Management" in r_settings.json()["reply"]

    # 3. Invalid password rejection
    r_fail = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "/addemailaddress testfail@gmail.com wrongpass Roy"}
    })
    assert r_fail.status_code == 200
    assert "Google Authentication Failed" in r_fail.json()["reply"]

    # 4. Add valid test mailbox via command
    r1 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "/addemailaddress test1@gmail.com pass1234 Roy"}
    })
    assert r1.status_code == 200
    assert "Mailbox Verified & Added to Pool" in r1.json()["reply"]

    # 5. View /settings list with password shown
    r2 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "/settings"}
    })
    assert r2.status_code == 200
    assert "test1@gmail.com" in r2.json()["reply"]
    assert "Password:" in r2.json()["reply"]
    assert "0/50" in r2.json()["reply"]

    # 6. Remove mailbox via /deleteemail
    r3 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "/deleteemail test1@gmail.com"}
    })
    assert r3.status_code == 200
    assert "removed from active rotation pool" in r3.json()["reply"]
