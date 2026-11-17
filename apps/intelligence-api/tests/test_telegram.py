import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import Business, Lead, MailboxAccount, MessageDraft, OperatorProfile, OperatorUser
from app.services.auth import verify_password
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
    assert "Step 1/7" in r1.json()["reply"]

    # Step 2: Provide niche
    r2 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "Real Estate"}
    })
    assert r2.status_code == 200
    assert "Step 2/7" in r2.json()["reply"]

    # Step 3: Provide location
    r3 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "Dallas, Texas"}
    })
    assert r3.status_code == 200
    assert "Step 3/7" in r3.json()["reply"]

    # Step 4: Provide services
    r4 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "automation system for business (ad managing, leads handling and follow ups and website providing)"}
    })
    assert r4.status_code == 200
    assert "Step 4/7" in r4.json()["reply"]

    # Step 5: Provide quantity
    r5 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "10"}
    })
    assert r5.status_code == 200
    assert "Step 5/7" in r5.json()["reply"]

    # Step 6: Provide benchmark score
    r6 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "50"}
    })
    assert r6.status_code == 200
    assert "Step 6/7" in r6.json()["reply"]
    assert "High-Converting Cold Outreach Template" in r6.json()["reply"]

    # Step 7: Answer Question 6 (Choose template: yes) -> advances to Question 7/7
    r7 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "yes"}
    })
    assert r7.status_code == 200
    res7 = r7.json()
    assert "Step 7/7" in res7["reply"]
    assert "Follow-Up Configuration" in res7["reply"]
    assert "buttons" in res7

    # Answer Question 7: Select Standard follow-up -> shows confirmation card
    r8 = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "wizard_followup:standard"}
    })
    assert r8.status_code == 200
    res8 = r8.json()
    assert "Confirm Campaign & Follow-Up Architecture" in res8["reply"]
    assert "Standard" in res8["reply"] or "Day +2" in res8["reply"]

    # Confirm & Launch
    r9 = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "wizard_confirm:yes"}
    })
    assert r9.status_code == 200
    res_data = r9.json()
    assert "Campaign Completed & Scored" in res_data["reply"]
    assert "csv_content" in res_data
    assert "benchmark_met" in res_data["csv_content"]
    assert "buttons" in res_data


def test_wizard_question6_no_personalized_ai_branch(client, db_session):
    user_id = 123456789
    db_session.add(OperatorProfile(user_id=str(user_id), sender_name="Alex", agency_name="Nexus"))
    db_session.commit()

    # Fast forward wizard to Step 6
    from app.services.telegram_bot import _USER_WIZARD_SESSIONS
    _USER_WIZARD_SESSIONS[str(user_id)] = {
        "step": "awaiting_template_choice",
        "niche": "Law Firms",
        "location": "Miami",
        "services": "lead automation",
        "quantity": 5,
        "benchmark": 40,
    }

    # Choose NO (Personalized AI pitches)
    r = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "wizard_template:no"}
    })
    assert r.status_code == 200
    res = r.json()
    assert "Personalized AI Proposals" in res["reply"]
    assert "Step 7/7: Follow-Up Configuration" in res["reply"]
    assert _USER_WIZARD_SESSIONS[str(user_id)]["use_best_response_template"] is False
    assert _USER_WIZARD_SESSIONS[str(user_id)]["step"] == "awaiting_followup_config"

    # Clean up
    _USER_WIZARD_SESSIONS.pop(str(user_id), None)


def test_wizard_question7_business_days_branch(client, db_session):
    user_id = 123456789
    db_session.add(OperatorProfile(user_id=str(user_id), sender_name="Alex", agency_name="Nexus"))
    db_session.commit()

    from app.services.telegram_bot import _USER_WIZARD_SESSIONS
    _USER_WIZARD_SESSIONS[str(user_id)] = {
        "step": "awaiting_followup_config",
        "niche": "Roofers",
        "location": "Phoenix",
        "services": "website",
        "quantity": 5,
        "benchmark": 50,
        "use_best_response_template": True,
    }

    # Select Business Days
    r = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "wizard_followup:biz_days"}
    })
    assert r.status_code == 200
    res = r.json()
    assert "Confirm Campaign & Follow-Up Architecture" in res["reply"]
    assert "Business" in res["reply"]
    assert "Day +3" in res["reply"]
    assert "Day +7" in res["reply"]

    session = _USER_WIZARD_SESSIONS[str(user_id)]
    assert session["followup_sequence"]["enabled"] is True
    assert session["followup_sequence"]["schedule_type"] == "business"
    assert session["followup_sequence"]["delays"] == [3, 7]

    _USER_WIZARD_SESSIONS.pop(str(user_id), None)


def test_wizard_question7_single_touch_branch(client, db_session):
    user_id = 123456789
    db_session.add(OperatorProfile(user_id=str(user_id), sender_name="Alex", agency_name="Nexus"))
    db_session.commit()

    from app.services.telegram_bot import _USER_WIZARD_SESSIONS
    _USER_WIZARD_SESSIONS[str(user_id)] = {
        "step": "awaiting_followup_config",
        "niche": "Gyms",
        "location": "Austin",
        "services": "marketing",
        "quantity": 5,
        "benchmark": 40,
        "use_best_response_template": True,
    }

    # Select Single Touch
    r = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "wizard_followup:none"}
    })
    assert r.status_code == 200
    res = r.json()
    assert "Single Touch" in res["reply"]
    assert "no automated follow-ups" in res["reply"]

    session = _USER_WIZARD_SESSIONS[str(user_id)]
    assert session["followup_sequence"]["enabled"] is False
    assert session["followup_sequence"]["delays"] == []

    _USER_WIZARD_SESSIONS.pop(str(user_id), None)


def test_wizard_question7_custom_branch(client, db_session):
    user_id = 123456789
    db_session.add(OperatorProfile(user_id=str(user_id), sender_name="Alex", agency_name="Nexus"))
    db_session.commit()

    from app.services.telegram_bot import _USER_WIZARD_SESSIONS
    _USER_WIZARD_SESSIONS[str(user_id)] = {
        "step": "awaiting_followup_config",
        "niche": "Dentists",
        "location": "Seattle",
        "services": "automation",
        "quantity": 5,
        "benchmark": 40,
        "use_best_response_template": True,
    }

    # 1. Tap Custom Intervals button
    r_btn = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "wizard_followup:custom"}
    })
    assert r_btn.status_code == 200
    assert "Custom Follow-Up Intervals" in r_btn.json()["reply"]

    # 2. Test Invalid custom intervals (decreasing)
    r_invalid = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "5, 2"}
    })
    assert r_invalid.status_code == 200
    assert "strictly increasing" in r_invalid.json()["reply"]

    # 3. Test Invalid custom intervals (negative)
    r_neg = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "-2, 5"}
    })
    assert r_neg.status_code == 200
    assert "strictly positive" in r_neg.json()["reply"]

    # 4. Provide Valid custom intervals (2, 5, 9)
    r_valid = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "2, 5, 9"}
    })
    assert r_valid.status_code == 200
    res_val = r_valid.json()
    assert "Confirm Campaign & Follow-Up Architecture" in res_val["reply"]
    assert "3 Touches" in res_val["reply"]
    assert "Day +2" in res_val["reply"]
    assert "Day +5" in res_val["reply"]
    assert "Day +9" in res_val["reply"]

    session = _USER_WIZARD_SESSIONS[str(user_id)]
    assert session["followup_sequence"]["enabled"] is True
    assert session["followup_sequence"]["delays"] == [2, 5, 9]

    _USER_WIZARD_SESSIONS.pop(str(user_id), None)


def test_wizard_duplicate_callback_handling(client, db_session):
    user_id = 123456789
    db_session.add(OperatorProfile(user_id=str(user_id), sender_name="Alex", agency_name="Nexus"))
    db_session.commit()

    from app.services.telegram_bot import _USER_WIZARD_SESSIONS
    _USER_WIZARD_SESSIONS[str(user_id)] = {
        "step": "awaiting_template_choice",
        "niche": "Dentists",
        "location": "Seattle",
        "services": "automation",
        "quantity": 5,
        "benchmark": 40,
    }

    # Click YES once
    r1 = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "wizard_template:yes"}
    })
    assert r1.status_code == 200
    assert "Step 7/7" in r1.json()["reply"]

    # Click YES second time (duplicate) -> should NOT crash or error
    r2 = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "wizard_template:yes"}
    })
    assert r2.status_code == 200
    assert "Step 7/7" in r2.json()["reply"]

    # Click standard followup once
    r3 = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "wizard_followup:standard"}
    })
    assert r3.status_code == 200
    assert "Confirm Campaign" in r3.json()["reply"]

    # Click standard followup second time (duplicate)
    r4 = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "wizard_followup:standard"}
    })
    assert r4.status_code == 200
    assert "Confirm Campaign" in r4.json()["reply"]

    _USER_WIZARD_SESSIONS.pop(str(user_id), None)


def test_wizard_persistence_and_bot_restart_recovery(client, db_session):
    user_id = 123456789
    db_session.add(OperatorProfile(user_id=str(user_id), sender_name="Alex", agency_name="Nexus"))
    db_session.commit()

    from app.services.telegram_bot import _USER_WIZARD_SESSIONS, PersistentSessionDict

    # Save an in-progress session
    _USER_WIZARD_SESSIONS[str(user_id)] = {
        "step": "awaiting_followup_config",
        "niche": "E-commerce",
        "location": "California",
        "services": "marketing",
        "quantity": 25,
        "benchmark": 45,
        "use_best_response_template": True,
    }

    # Simulate bot restart by creating a new session dictionary from disk
    restored = PersistentSessionDict("wizard_sessions.json", "user_wizard_session")
    session = restored.get(str(user_id))
    assert session is not None
    assert session["niche"] == "E-commerce"
    assert session["step"] == "awaiting_followup_config"

    # User can seamlessly proceed with Question 7 after restart
    r = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "wizard_followup:standard"}
    })
    assert r.status_code == 200
    assert "Confirm Campaign & Follow-Up Architecture" in r.json()["reply"]

    _USER_WIZARD_SESSIONS.pop(str(user_id), None)


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

    # 3. Provide Agency Name -> triggers Step 3/3 (Web Dashboard Password)
    r3 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "ori9in.io"}
    })
    assert r3.status_code == 200
    assert "Step 3/3: Set your Web Dashboard Password" in r3.json()["reply"]

    # 4. Provide Password -> creates OperatorUser + OperatorProfile and completes setup
    r4 = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "SecurePassword123!"}
    })
    assert r4.status_code == 200
    reply4 = r4.json()["reply"]
    assert "Account Created Successfully!" in reply4
    assert "/findleads" in reply4
    assert "http://localhost:8000/login" in reply4

    # Check database persistence of profile and linked user
    prof = db_session.get(OperatorProfile, str(user_id))
    assert prof is not None
    assert prof.sender_name == "Roy"
    assert prof.agency_name == "ori9in.io"
    assert prof.operator_user_id is not None

    user = db_session.get(OperatorUser, prof.operator_user_id)
    assert user is not None
    assert user.username == "roy"
    assert verify_password("SecurePassword123!", user.password_hash)

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

    # /setpassword
    r_pw = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "/setpassword SuperSecret999!"}
    })
    assert r_pw.status_code == 200
    assert "Password Successfully Updated" in r_pw.json()["reply"]

    db_session.refresh(prof)
    assert prof.operator_user_id is not None
    user = db_session.get(OperatorUser, prof.operator_user_id)
    assert verify_password("SuperSecret999!", user.password_hash)

    # Interactive button to edit password
    r_pw_btn = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": user_id}, "data": "edit_profile:password"}
    })
    assert r_pw_btn.status_code == 200
    assert "Update Web Dashboard Password" in r_pw_btn.json()["reply"]

    # Reply with new password
    r_pw_reply = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": user_id}, "text": "BrandNewPass456!"}
    })
    assert r_pw_reply.status_code == 200
    assert "Password Successfully Updated" in r_pw_reply.json()["reply"]

    db_session.refresh(user)
    assert verify_password("BrandNewPass456!", user.password_hash)


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


def test_wizard_campaign_persistence_and_followup_scheduler(client, db_session, auth_settings):
    from datetime import datetime, timezone
    from app.models import Campaign, Conversation, FollowUpExecution, Lead
    from app.services.followup_engine import schedule_followups_for_conversation
    from app.services.telegram_bot import _execute_wizard_campaign

    user_id = 123456789

    # 1. Standard branch (Day 2, Day 5 Calendar)
    session_std = {
        "niche": "Accountants",
        "location": "Boston, MA",
        "services": "automation",
        "quantity": 3,
        "benchmark": 40,
        "use_best_response_template": True,
        "followup_sequence": {
            "enabled": True,
            "count": 2,
            "delays": [2, 5],
            "schedule_type": "calendar",
            "final_action": "close",
        },
    }
    _execute_wizard_campaign(
        db=db_session,
        settings=auth_settings,
        user_id=user_id,
        user_key=str(user_id),
        session_data=session_std,
        use_best_response_template=True,
        agency_name="River Agency",
        sender_name="Jordan Reed",
    )

    camp_std = db_session.query(Campaign).filter_by(niche="Accountants").first()
    assert camp_std is not None
    assert camp_std.followup_sequence["enabled"] is True
    assert camp_std.followup_sequence["delays"] == [2, 5]
    assert camp_std.followup_sequence["schedule_type"] == "calendar"

    lead_std = db_session.query(Lead).filter_by(campaign_id=camp_std.id).first()
    conv_std = Conversation(
        campaign_id=camp_std.id,
        lead_id=lead_std.id,
        recipient_email="prospect_std@example.com",
        sender_email="outreach@ori9in.io",
        subject="Introductory note",
        status="active",
        followup_status="active",
        followup_step=0,
    )
    db_session.add(conv_std)
    db_session.commit()

    base_time = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)
    executions = schedule_followups_for_conversation(db_session, conv_std, camp_std, base_time=base_time)
    assert len(executions) == 2
    assert executions[0].sequence_step == 1
    assert executions[0].scheduled_at == datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)  # Day +2
    assert executions[1].sequence_step == 2
    assert executions[1].scheduled_at == datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)  # Day +5

    # 2. Single Touch branch (No follow-ups)
    session_single = {
        "niche": "Plumbers",
        "location": "Dallas, TX",
        "services": "website",
        "quantity": 3,
        "benchmark": 40,
        "use_best_response_template": False,
        "followup_sequence": {
            "enabled": False,
            "count": 0,
            "delays": [],
            "schedule_type": "calendar",
            "final_action": "close",
        },
    }
    _execute_wizard_campaign(
        db=db_session,
        settings=auth_settings,
        user_id=user_id,
        user_key=str(user_id),
        session_data=session_single,
        use_best_response_template=False,
        agency_name="River Agency",
        sender_name="Jordan Reed",
    )

    camp_single = db_session.query(Campaign).filter_by(niche="Plumbers").first()
    assert camp_single is not None
    assert camp_single.followup_sequence["enabled"] is False

    lead_single = db_session.query(Lead).filter_by(campaign_id=camp_single.id).first()
    conv_single = Conversation(
        campaign_id=camp_single.id,
        lead_id=lead_single.id,
        recipient_email="prospect_single@example.com",
        sender_email="outreach@ori9in.io",
        subject="Introductory note",
        status="active",
        followup_status="idle",
        followup_step=0,
    )
    db_session.add(conv_single)
    db_session.commit()

    executions_single = schedule_followups_for_conversation(db_session, conv_single, camp_single, base_time=base_time)
    assert len(executions_single) == 0





