import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import Business, Lead, MailboxAccount, MessageDraft, OperatorProfile
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


def test_export_csv_command(client, db_session, auth_settings):
    payload = {
        "niche": "Real Estate Agencies",
        "location": "Dallas, Texas",
        "requested_quantity": 3,
        "target_services": ["website_development"],
        "filters": {},
    }
    camp = create_campaign(db_session, payload, auth_settings)
    run_campaign(db_session, camp.id, auth_settings)

    update = {
        "message": {
            "from": {"id": 123456789},
            "text": f"/export_csv {camp.id}",
        }
    }
    res = client.post("/api/orchestrator/webhooks/telegram", json=update)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "csv_content" in data
    assert "name,location,overall_score" in data["csv_content"]


def test_interactive_wizard_flow(client, db_session):
    user_id = 123456789
    # User is already onboarded
    db_session.add(OperatorProfile(user_id=str(user_id), sender_name="Jordan Reed", agency_name="River Agency"))
    db_session.commit()

    # Step 1: Send /findleads to start wizard
    r1 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "/findleads"}
    })
    assert r1.status_code == 200
    assert "Step 1/6" in r1.json()["reply"]

    # Step 2: Provide niche
    r2 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "Real Estate"}
    })
    assert r2.status_code == 200
    assert "Step 2/6" in r2.json()["reply"]

    # Step 3: Provide location
    r3 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "Dallas, Texas"}
    })
    assert r3.status_code == 200
    assert "Step 3/6" in r3.json()["reply"]

    # Step 4: Provide services
    r4 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "automation system for business (ad managing, leads handling and follow ups and website providing)"}
    })
    assert r4.status_code == 200
    assert "Step 4/6" in r4.json()["reply"]

    # Step 5: Provide quantity
    r5 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "10"}
    })
    assert r5.status_code == 200
    assert "Step 5/6" in r5.json()["reply"]

    # Step 6: Provide benchmark score
    r6 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "50"}
    })
    assert r6.status_code == 200
    assert "Step 6/6" in r6.json()["reply"]

    # Step 7: Choose template
    r7 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "yes"}
    })
    assert r7.status_code == 200
    res_data = r7.json()
    assert "Campaign Completed & Scored" in res_data["reply"]
    assert "csv_content" in res_data
    assert "benchmark_met" in res_data["csv_content"]
    assert "buttons" in res_data


def test_provider_commands_and_callbacks(client, db_session):
    user_id = 123456789
    db_session.add(OperatorProfile(user_id=str(user_id), sender_name="Roy", agency_name="ori9in.io"))
    db_session.commit()

    # 1. Test /provider command
    r = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "/provider"}
    })
    assert r.status_code == 200
    data = r.json()
    assert "Engine & Provider Settings" in data["reply"]
    assert "buttons" in data

    # 2. Test /set_provider command
    r_set = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "/set_provider scrapling"}
    })
    assert r_set.status_code == 200
    assert "SCRAPLING" in r_set.json()["reply"]

    # 3. Test callback set_disc_provider:mock
    r_cb = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "set_disc_provider:mock"}
    })
    assert r_cb.status_code == 200
    assert "Mock Fixtures" in r_cb.json()["reply"]

    # 4. Test callback set_email_provider:smtp
    r_ecb = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "set_email_provider:smtp"}
    })
    assert r_ecb.status_code == 200
    assert "Gmail SMTP Pool" in r_ecb.json()["reply"]


def test_bulk_approve_campaign(client, db_session, auth_settings):
    payload = {
        "niche": "Real Estate Agencies",
        "location": "Dallas, Texas",
        "requested_quantity": 5,
        "target_services": ["website_development"],
        "filters": {"min_score": 50},
    }
    camp = create_campaign(db_session, payload, auth_settings)
    run_campaign(db_session, camp.id, auth_settings)

    # Approve all leads via command
    update = {
        "message": {
            "from": {"id": 123456789},
            "text": f"/approve_campaign {camp.id} 50",
        }
    }
    res = client.post("/api/orchestrator/webhooks/telegram", json=update)
    assert res.status_code == 200
    assert "Successfully approved" in res.json()["reply"]

    leads = db_session.query(Lead).filter_by(campaign_id=camp.id).all()
    assert all(l.outreach_status == "approved" for l in leads if l.overall_score >= 50)


def test_dispatch_command_and_callback(client, db_session, auth_settings):
    payload = {
        "niche": "Real Estate Agencies",
        "location": "Dallas, Texas",
        "requested_quantity": 5,
        "target_services": ["website_development"],
        "filters": {"min_score": 50},
    }
    camp = create_campaign(db_session, payload, auth_settings)
    run_campaign(db_session, camp.id, auth_settings)

    # 1. Test /dispatch command
    res = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": f"/dispatch {camp.id}"}
    })
    assert res.status_code == 200
    assert "Outreach Dispatch Completed" in res.json()["reply"]

    # 2. Test dispatch_campaign callback
    cb_res = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {
            "from": {"id": 123456789},
            "data": f"dispatch_campaign:{camp.id}",
        }
    })
    assert cb_res.status_code == 200
    assert "Outreach Dispatch Completed" in cb_res.json()["reply"]


def test_review_flow_and_callback(client, db_session, auth_settings):
    payload = {
        "niche": "Real Estate Agencies",
        "location": "Dallas, Texas",
        "requested_quantity": 5,
        "target_services": ["website_development"],
        "filters": {"min_score": 50},
    }
    camp = create_campaign(db_session, payload, auth_settings)
    run_campaign(db_session, camp.id, auth_settings)

    # 1. Trigger /review
    res = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": f"/review {camp.id} 50"}
    })
    assert res.status_code == 200
    data = res.json()
    assert "LEAD APPROVAL CARD" in data["reply"]
    assert "buttons" in data

    # 2. Click Approve & Next on the lead
    lead = db_session.query(Lead).filter_by(campaign_id=camp.id, outreach_status="draft").first()
    assert lead is not None

    cb_res = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {
            "from": {"id": 123456789},
            "data": f"review_approve:{lead.id}",
        }
    })
    assert cb_res.status_code == 200
    db_session.refresh(lead)
    assert lead.outreach_status == "approved"


def test_first_chat_onboarding_and_persistence(client, db_session):
    user_id = 123456789

    # 1. First chat interaction via /start triggers Step 1/3 of onboarding (Name)
    r1 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "/start"}
    })
    assert r1.status_code == 200
    assert "Step 1/3: What is your Name?" in r1.json()["reply"]

    # 2. Provide Name -> triggers Step 2/3 (Agency Name)
    r2 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "Roy"}
    })
    assert r2.status_code == 200
    assert "Step 2/3: What is your Agency or Business Name?" in r2.json()["reply"]
    assert "Roy" in r2.json()["reply"]

    # 3. Provide Agency Name -> triggers Step 3/3 (Outreach Gmail & App Password)
    r3 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "ori9in.io"}
    })
    assert r3.status_code == 200
    assert "Step 3/3: Connect Outreach Gmail & Password" in r3.json()["reply"]

    # 4. Provide Gmail & 16-letter App Password -> configures defaults and triggers Step 1/5
    r4 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "test_default@gmail.com pass1234 Roy"}
    })
    assert r4.status_code == 200
    reply4 = r4.json()["reply"]
    assert "Setup Complete! Default Profile & Mailbox Configured" in reply4
    assert "/findleads" in reply4
    assert "/review" in reply4
    assert "/dispatch" in reply4
    assert "/settings" in reply4

    # Check database persistence of profile
    prof = db_session.get(OperatorProfile, str(user_id))
    assert prof is not None
    assert prof.sender_name == "Roy"
    assert prof.agency_name == "ori9in.io"

    # Check database persistence of mailbox
    acc = db_session.query(MailboxAccount).filter_by(email="test_default@gmail.com").first()
    assert acc is not None
    assert acc.is_active is True

    # 5. On subsequent chats, it NEVER asks again!
    r5 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "/cancel"}
    })
    assert r5.status_code == 200

    r6 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "/start"}
    })
    assert r6.status_code == 200
    assert "*Operator:* *Roy* (ori9in.io)" in r6.json()["reply"]
    assert "Step 1/3" not in r6.json()["reply"]


def test_profile_commands(client, db_session):
    user_id = 123456789
    prof = OperatorProfile(user_id=str(user_id), sender_name="Roy", agency_name="ori9in.io")
    db_session.add(prof)
    db_session.commit()

    # /profile
    r1 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "/profile"}
    })
    assert r1.status_code == 200
    assert "Roy" in r1.json()["reply"]
    assert "ori9in.io" in r1.json()["reply"]

    # /setname
    r2 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "/setname Alex Rivera"}
    })
    assert r2.status_code == 200
    assert "Alex Rivera" in r2.json()["reply"]

    # /setagency
    r3 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "/setagency Apex Solutions"}
    })
    assert r3.status_code == 200
    assert "Apex Solutions" in r3.json()["reply"]

    # Interactive button to edit name
    r_btn = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "edit_profile:name"}
    })
    assert r_btn.status_code == 200
    assert "Update Sender Name" in r_btn.json()["reply"]

    # Reply with new name
    r_reply = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "Jordan Hayes"}
    })
    assert r_reply.status_code == 200
    assert "Jordan Hayes" in r_reply.json()["reply"]

    db_session.refresh(prof)
    assert prof.sender_name == "Jordan Hayes"
    assert prof.agency_name == "Apex Solutions"


def test_clean_memory_command(client, db_session):
    user_id = 123456789
    prof = OperatorProfile(user_id=str(user_id), sender_name="Roy", agency_name="ori9in.io")
    db_session.add(prof)
    mb = MailboxAccount(email="test_mb@gmail.com", password="pass", sender_name="Roy", daily_limit=50, is_active=True)
    db_session.add(mb)
    db_session.commit()

    # 1. Send /clean memory
    r1 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "/clean memory"}
    })
    assert r1.status_code == 200
    reply1 = r1.json()["reply"]
    assert "App Data & Memory Cleared" in reply1
    assert "Step 1/3: What is your Name?" in reply1

    # 2. Verify DB is wiped clean
    prof_check = db_session.get(OperatorProfile, str(user_id))
    assert prof_check is None
    mb_count = db_session.query(MailboxAccount).count()
    assert mb_count == 0

    # 3. Next input answers Step 1/3 and advances to Step 2/3
    r2 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "NewOperator"}
    })
    assert r2.status_code == 200
    assert "Step 2/3: What is your Agency or Business Name?" in r2.json()["reply"]
    assert "NewOperator" in r2.json()["reply"]




