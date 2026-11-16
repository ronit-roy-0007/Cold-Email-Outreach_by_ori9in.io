from __future__ import annotations

import uuid
import pytest
from app.models import (
    Business,
    Campaign,
    CampaignLeftoverLead,
    Lead,
    MailboxAccount,
    MessageDraft,
    OperatorProfile,
    OutboundMessage,
)
from app.services.campaigns import create_campaign
from app.services.geo_expansion import get_nearby_regions, get_next_expansion_location
from app.services.pipeline import run_campaign
from app.services.sub_campaign_service import (
    check_existing_leftover_leads,
    consume_leftover_leads,
    dispatch_subcampaign_batch,
    generate_gmail_success_csv,
    generate_remaining_leads_csv,
    generate_total_volume_csv,
    is_business_duplicate,
    record_campaign_leftovers,
)
from app.services.telegram_bot import handle_telegram_update


@pytest.fixture(autouse=True)
def setup_operator(db_session):
    # Ensure operator profile exists
    prof = db_session.get(OperatorProfile, "123456789")
    if not prof:
        prof = OperatorProfile(user_id="123456789", sender_name="Roy", agency_name="ori9in.io")
        db_session.add(prof)
        db_session.commit()
    yield


def test_triple_layer_deduplication(db_session, auth_settings):
    # Setup test campaign
    camp = create_campaign(db_session, {
        "niche": "Real Estate Agencies",
        "location": "Delhi",
        "requested_quantity": 5,
        "target_services": ["website_development"],
        "filters": {"min_score": 70},
    }, auth_settings)

    biz1 = Business(
        identity_key="place:ChIJ_delhi_1",
        place_id="ChIJ_delhi_1",
        name="Apex Properties Delhi",
        website="https://www.apexdelhi.com/contact",
        email="contact@apexdelhi.com",
        source_fields={},
        discovery_source="mock",
    )
    db_session.add(biz1)
    db_session.flush()

    lead1 = Lead(
        campaign_id=camp.id,
        business_id=biz1.id,
        overall_score=85,
        priority="A",
        confidence="high",
        outreach_status="draft",
        crm_stage="qualified",
    )
    db_session.add(lead1)
    db_session.commit()

    # Layer 1: Check duplicate place_id
    assert is_business_duplicate(db_session, camp.id, place_id="ChIJ_delhi_1") is True
    assert is_business_duplicate(db_session, camp.id, place_id="ChIJ_new_unique") is False

    # Layer 2: Check duplicate root domain
    assert is_business_duplicate(db_session, camp.id, website="https://sub.apexdelhi.com/about") is True
    assert is_business_duplicate(db_session, camp.id, website="https://uniquerealty.com") is False

    # Layer 3: Check duplicate email in campaign
    assert is_business_duplicate(db_session, camp.id, email="contact@apexdelhi.com") is True
    assert is_business_duplicate(db_session, camp.id, email="fresh@uniquerealty.com") is False

    # Layer 3b: Check duplicate email across historical outbound messages
    outbound = OutboundMessage(
        lead_id=None,
        campaign_id=None,
        recipient_email="historical@client.com",
        sender_email="outreach@ori9in.io",
        subject="Hello",
        body="Pitch",
        provider="smtp",
        status="sent",
    )
    db_session.add(outbound)
    db_session.commit()

    assert is_business_duplicate(db_session, camp.id, email="historical@client.com") is True


def test_geo_expansion_regions():
    # Delhi concentric rings
    regions = get_nearby_regions("Delhi")
    assert "Noida" in regions
    assert "Gurugram" in regions

    # Next location selection
    next_loc = get_next_expansion_location("Delhi", visited_locations=["Noida"])
    assert next_loc == "Gurugram"

    # Fallback for unmapped city
    unmapped = get_nearby_regions("Springfield")
    assert any("Springfield" in r for r in unmapped)


def test_subcampaign_loop_and_precision_stop(client, db_session, auth_settings):
    # Ensure active mailbox exists
    mb = db_session.query(MailboxAccount).filter_by(email="roy@ori9in.io").first()
    if not mb:
        mb = MailboxAccount(email="roy@ori9in.io", password="abcd efgh ijkl mnop", sender_name="Roy", daily_limit=50, is_active=True)
        db_session.add(mb)
        db_session.commit()

    # Step 1: Start campaign for 2 target sent emails
    update = {
        "message": {
            "from": {"id": 123456789},
            "text": "/findleads Real Estate in Delhi 2 70",
        }
    }
    res = client.post("/api/orchestrator/webhooks/telegram", json=update)
    assert res.status_code == 200
    data = res.json()
    assert "Sub-Campaign 1 Ready" in data["reply"]

    camp_id = uuid.UUID(data["campaign_id"])
    camp = db_session.get(Campaign, camp_id)
    assert camp.target_sent_emails == 2
    assert camp.total_sent_emails == 0

    # Step 2: Approve Batch 1
    approve_update = {
        "callback_query": {
            "from": {"id": 123456789},
            "data": f"subcamp_approve:{camp.id}:1",
        }
    }
    res_app = client.post("/api/orchestrator/webhooks/telegram", json=approve_update)
    assert res_app.status_code == 200
    app_data = res_app.json()

    db_session.refresh(camp)
    assert camp.total_sent_emails >= 2
    assert camp.status == "completed"
    assert "Campaign Finished" in app_data["reply"]
    assert "Total volume of campaign.csv" in app_data["files"]
    assert "Final campaign gmail success.csv" in app_data["files"]
    assert "Remaining leads.csv" in app_data["files"]


def test_smart_rollover_into_next_campaign(client, db_session, auth_settings):
    # Create leftover leads in CampaignLeftoverLead
    biz = Business(
        identity_key="place:ChIJ_leftover_1",
        place_id="ChIJ_leftover_1",
        name="Rollover Realty",
        website="https://www.rollover.com",
        email="info@rollover.com",
        source_fields={},
        discovery_source="mock",
    )
    db_session.add(biz)
    db_session.flush()

    past_camp = create_campaign(db_session, {
        "niche": "Real Estate Agencies",
        "location": "Delhi",
        "requested_quantity": 10,
        "target_services": ["website_development"],
        "filters": {"min_score": 70},
    }, auth_settings)

    lead = Lead(
        campaign_id=past_camp.id,
        business_id=biz.id,
        overall_score=88,
        priority="A",
        confidence="high",
        outreach_status="draft",
        crm_stage="qualified",
    )
    db_session.add(lead)
    db_session.flush()

    leftover = CampaignLeftoverLead(
        campaign_id=past_camp.id,
        business_id=biz.id,
        lead_id=lead.id,
        niche="Real Estate Agencies",
        location="Delhi",
        overall_score=88,
        is_consumed=False,
    )
    db_session.add(leftover)
    db_session.commit()

    # Launch new campaign with matching criteria
    update = {
        "message": {
            "from": {"id": 123456789},
            "text": "/findleads Real Estate Agencies in Delhi 5 70",
        }
    }
    res = client.post("/api/orchestrator/webhooks/telegram", json=update)
    assert res.status_code == 200
    data = res.json()
    assert "Smart Rollover Activated" in data["reply"]

    # Verify leftover was consumed
    db_session.refresh(leftover)
    assert leftover.is_consumed is True


def test_exhaustion_and_radius_expansion(client, db_session, auth_settings):
    camp = create_campaign(db_session, {
        "niche": "Real Estate Agencies",
        "location": "Delhi",
        "requested_quantity": 50,
        "max_limit": 100,
        "target_services": ["website_development"],
        "filters": {"min_score": 70},
    }, auth_settings)
    camp.target_sent_emails = 50
    camp.total_sent_emails = 35
    camp.is_exhausted = True
    db_session.commit()

    # Send approve callback when exhausted
    update = {
        "callback_query": {
            "from": {"id": 123456789},
            "data": f"subcamp_approve:{camp.id}:2",
        }
    }
    res = client.post("/api/orchestrator/webhooks/telegram", json=update)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "paused_exhaustion"
    assert "Primary Location Exhausted" in data["reply"]
    assert any(btn["callback_data"].startswith("expand_radius:") for row in data["buttons"] for btn in row)
    assert any(btn["callback_data"].startswith("finish_campaign_early:") for row in data["buttons"] for btn in row)

    # Click Expand Radius
    expand_update = {
        "callback_query": {
            "from": {"id": 123456789},
            "data": f"expand_radius:{camp.id}",
        }
    }
    res_exp = client.post("/api/orchestrator/webhooks/telegram", json=expand_update)
    assert res_exp.status_code == 200
    exp_data = res_exp.json()
    assert "Search Radius Expanded" in exp_data["reply"]

    db_session.refresh(camp)
    assert camp.radius_expanded is True
    assert len(camp.expanded_locations) > 0


def test_auto_mode_subcampaign(client, db_session, auth_settings):
    # Ensure active mailbox exists
    mb = db_session.query(MailboxAccount).filter_by(email="roy@ori9in.io").first()
    if not mb:
        mb = MailboxAccount(email="roy@ori9in.io", password="abcd efgh ijkl mnop", sender_name="Roy", daily_limit=50, is_active=True)
        db_session.add(mb)
        db_session.commit()

    camp = create_campaign(db_session, {
        "niche": "Real Estate Agencies",
        "location": "Dallas, Texas",
        "requested_quantity": 5,
        "target_services": ["website_development"],
        "filters": {"min_score": 60},
    }, auth_settings)
    camp.target_sent_emails = 3
    camp.total_sent_emails = 0
    db_session.commit()

    # Pre-populate leads
    run_campaign(db_session, camp.id, auth_settings)

    # Trigger Auto Mode callback
    auto_update = {
        "callback_query": {
            "from": {"id": 123456789},
            "data": f"subcamp_auto:{camp.id}:1",
        }
    }
    res = client.post("/api/orchestrator/webhooks/telegram", json=auto_update)
    assert res.status_code == 200
    data = res.json()

    db_session.refresh(camp)
    assert camp.is_auto_mode is True
    assert camp.total_sent_emails >= 3
    assert camp.status == "completed"
    assert "Campaign Finished" in data["reply"]


def test_subcampaign_trigger_only_when_sent_less_than_target_and_csv_partitions(client, db_session, auth_settings):
    # Ensure active mailbox exists
    mb = db_session.query(MailboxAccount).filter_by(email="roy@ori9in.io").first()
    if not mb:
        mb = MailboxAccount(email="roy@ori9in.io", password="abcd efgh ijkl mnop", sender_name="Roy", daily_limit=50, is_active=True)
        db_session.add(mb)
        db_session.commit()

    # Create a campaign where target_sent_emails is 5
    camp = create_campaign(db_session, {
        "niche": "Real Estate Agencies",
        "location": "Dallas, Texas",
        "requested_quantity": 4,
        "target_services": ["website_development"],
        "filters": {"min_score": 60},
    }, auth_settings)
    camp.target_sent_emails = 5
    camp.total_sent_emails = 0
    camp.sub_campaign_index = 1
    db_session.commit()

    # Pre-populate 4 leads (all score >= 60)
    run_campaign(db_session, camp.id, auth_settings, target_count=4)
    matching = db_session.query(Lead).filter(Lead.campaign_id == camp.id, Lead.overall_score >= 60).count()
    assert matching >= 4

    # Add extra qualified leads with lower scores so at least one remains untouched after precision stop
    for i, sc in [(1, 62), (2, 61)]:
        eb = Business(
            identity_key=f"place:ChIJ_extra_unattempted_{i}",
            place_id=f"ChIJ_extra_unattempted_{i}",
            name=f"Unattempted Realty {i}",
            website="https://www.example.com",
            email=f"contact{i}@example.com",
            source_fields={},
            discovery_source="mock",
        )
        db_session.add(eb)
        db_session.flush()
        el = Lead(
            campaign_id=camp.id,
            business_id=eb.id,
            overall_score=sc,
            priority="B",
            confidence="high",
            outreach_status="draft",
            crm_stage="qualified",
        )
        db_session.add(el)
    db_session.commit()

    # Step 1: User approves Batch 1
    # Batch 1 has 4 leads. When sent, total_sent becomes 4 (less than target 5).
    # Therefore, Sub-Campaign 2 MUST auto-trigger!
    update = {
        "callback_query": {
            "from": {"id": 123456789},
            "data": f"subcamp_approve:{camp.id}:1",
        }
    }
    res = client.post("/api/orchestrator/webhooks/telegram", json=update)
    assert res.status_code == 200
    data = res.json()

    db_session.refresh(camp)
    assert camp.total_sent_emails == 4
    # Sub-Campaign 2 was triggered because 4 < 5!
    assert camp.sub_campaign_index == 2
    assert "Sub-Campaign 2 Ready" in data["reply"]

    # Step 2: User approves Batch 2
    # In Batch 2, only 1 more sent email is needed to hit 5 (target_sent_emails).
    # Precision stop MUST hit on the 1st send of Batch 2!
    update_2 = {
        "callback_query": {
            "from": {"id": 123456789},
            "data": f"subcamp_approve:{camp.id}:2",
        }
    }
    res_2 = client.post("/api/orchestrator/webhooks/telegram", json=update_2)
    assert res_2.status_code == 200
    data_2 = res_2.json()

    db_session.refresh(camp)
    # Target 5 reached exactly!
    assert camp.total_sent_emails == 5
    assert camp.status == "completed"
    assert "Campaign Finished" in data_2["reply"]
    # Sub-Campaign 3 is NEVER triggered!
    assert camp.sub_campaign_index == 2

    # Verify CSV partitions
    total_csv = data_2["files"]["Total volume of campaign.csv"]
    success_csv = data_2["files"]["Final campaign gmail success.csv"]
    remaining_csv = data_2["files"]["Remaining leads.csv"]

    # Total volume CSV strictly contains leads that were ATTEMPTED
    # Every lead in total_csv must have outreach_status in attempted states and NEVER 'draft'
    total_lines = [l for l in total_csv.strip().splitlines() if l.strip()]
    assert len(total_lines) > 1
    for line in total_lines[1:]:
        assert any(st in line for st in ["sent", "simulated", "bounced", "suppressed", "throttled", "failed"])
        assert not line.endswith(",draft")

    # Final success CSV contains strictly the 5 successfully sent leads
    success_lines = [l for l in success_csv.strip().splitlines() if l.strip()]
    assert len(success_lines) == 6

    # Remaining CSV strictly contains leads with status 'draft' or 'approved'
    remaining_lines = [l for l in remaining_csv.strip().splitlines() if l.strip()]
    assert len(remaining_lines) >= 2
    for line in remaining_lines[1:]:
        assert (line.endswith(",draft") or line.endswith(",approved"))


def test_rescrape_excludes_previous_campaign_sent_and_current_campaign_leads(client, db_session, auth_settings):
    from app.services.sub_campaign_service import is_business_duplicate
    from app.models import OutboundMessage

    # Step 1: Create Campaign 1 and record a successfully sent email
    camp1 = create_campaign(db_session, {
        "niche": "Dental Clinics",
        "location": "New York",
        "requested_quantity": 5,
        "target_services": ["website_development"],
        "filters": {"min_score": 60},
    }, auth_settings)

    biz1 = Business(
        identity_key="place:ChIJ_past_sent_dental",
        place_id="ChIJ_past_sent_dental",
        name="Past Sent Dental",
        website="https://www.pastsentdental.com",
        email="contact@pastsentdental.com",
        source_fields={},
        discovery_source="mock",
    )
    db_session.add(biz1)
    db_session.flush()

    lead1 = Lead(
        campaign_id=camp1.id,
        business_id=biz1.id,
        overall_score=75,
        priority="A",
        confidence="high",
        outreach_status="sent",
        crm_stage="contacted",
    )
    db_session.add(lead1)
    db_session.flush()

    outbound = OutboundMessage(
        campaign_id=camp1.id,
        lead_id=lead1.id,
        sender_email="roy@ori9in.io",
        recipient_email="contact@pastsentdental.com",
        subject="Pitch",
        body="Pitch text",
        provider="smtp",
        status="sent",
    )
    db_session.add(outbound)
    db_session.commit()

    # Step 2: Create Campaign 2 (e.g. user enters /findleads Dental Clinics in New York 14 60)
    camp2 = create_campaign(db_session, {
        "niche": "Dental Clinics",
        "location": "New York",
        "requested_quantity": 14,
        "target_services": ["website_development"],
        "filters": {"min_score": 60},
    }, auth_settings)

    # Add a business in Campaign 2 during scrape attempt 1
    biz2 = Business(
        identity_key="place:ChIJ_camp2_attempt1",
        place_id="ChIJ_camp2_attempt1",
        name="Camp2 Attempt1 Dental",
        website="https://www.camp2dental.com",
        email="hello@camp2dental.com",
        source_fields={},
        discovery_source="mock",
    )
    db_session.add(biz2)
    db_session.flush()

    lead2 = Lead(
        campaign_id=camp2.id,
        business_id=biz2.id,
        overall_score=55,  # Score < 60
        priority="C",
        confidence="medium",
        outreach_status="draft",
        crm_stage="discovered",
    )
    db_session.add(lead2)
    db_session.commit()

    # Verify Exclusion Rule 1: Exclude leads from ANY previous campaign that were successfully sent emails
    # A) Check by place_id of past sent business
    assert is_business_duplicate(db_session, camp2.id, place_id="ChIJ_past_sent_dental") is True
    # B) Check by email of past sent business
    assert is_business_duplicate(db_session, camp2.id, email="contact@pastsentdental.com") is True
    # C) Check by domain of past sent business
    assert is_business_duplicate(db_session, camp2.id, website="https://www.pastsentdental.com") is True

    # Verify Exclusion Rule 2: Exclude leads already in this sub-campaign's previous scrape attempts (even if score was < 60)
    # A) Check by place_id
    assert is_business_duplicate(db_session, camp2.id, place_id="ChIJ_camp2_attempt1") is True
    # B) Check by email
    assert is_business_duplicate(db_session, camp2.id, email="hello@camp2dental.com") is True
    # C) Check by domain
    assert is_business_duplicate(db_session, camp2.id, website="https://www.camp2dental.com") is True

    # Verify: Brand new uncontacted lead is NOT excluded
    assert is_business_duplicate(
        db_session,
        camp2.id,
        place_id="ChIJ_brand_new_lead",
        website="https://www.brandnewdental.com",
        email="info@brandnewdental.com",
    ) is False


def test_six_step_wizard_best_response_template(client, db_session, auth_settings):
    # Step 1: /findleads
    res = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "/findleads"}
    })
    assert res.status_code == 200
    assert "Step 1/6" in res.json()["reply"]

    # Step 2: Niche
    res = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "Dental Clinics"}
    })
    assert "Step 2/6" in res.json()["reply"]

    # Step 3: Location
    res = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "Dallas, Texas"}
    })
    assert "Step 3/6" in res.json()["reply"]

    # Step 4: Services
    res = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "website development and SEO"}
    })
    assert "Step 4/6" in res.json()["reply"]

    # Step 5: Quantity
    res = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "5"}
    })
    assert "Step 5/6" in res.json()["reply"]

    # Step 6: Benchmark Score -> triggers Step 6/6 template prompt
    res = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "60"}
    })
    data = res.json()
    assert "Step 6/6" in data["reply"]
    assert "Where should we go from here?" in data["reply"]
    assert any(btn["callback_data"] == "wizard_template:yes" for row in data["buttons"] for btn in row)

    # Answer YES via button callback
    res_launch = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": 123456789}, "data": "wizard_template:yes"}
    })
    assert res_launch.status_code == 200
    launch_data = res_launch.json()

    # Sub-Campaign 1 preview should have Approve Batch 1, but NO Review 1-by-1
    assert any(btn["callback_data"].startswith("subcamp_approve:") for row in launch_data["buttons"] for btn in row)
    assert not any(btn["callback_data"].startswith("start_review:") for row in launch_data["buttons"] for btn in row)
    assert "Review 1-by-1" not in launch_data["reply"]

    # Verify that drafts have the best response template body
    camp_id = uuid.UUID(launch_data["campaign_id"])
    camp = db_session.get(Campaign, camp_id)
    assert camp.filters.get("use_best_response_template") is True

    drafts = (
        db_session.query(MessageDraft)
        .join(Lead, MessageDraft.lead_id == Lead.id)
        .filter(Lead.campaign_id == camp_id)
        .all()
    )
    assert len(drafts) > 0
    for d in drafts:
        assert "tried to reach you a few times but didn't hear back . . .\n\n\nWhere should we go from here?" in d.body


def test_six_step_wizard_personalized_choice(client, db_session, auth_settings):
    # Step 1: /findleads
    res = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "/findleads"}
    })
    assert res.status_code == 200

    # Steps 2-5
    client.post("/api/orchestrator/webhooks/telegram", json={"message": {"from": {"id": 123456789}, "text": "Dental Clinics"}})
    client.post("/api/orchestrator/webhooks/telegram", json={"message": {"from": {"id": 123456789}, "text": "Dallas, Texas"}})
    client.post("/api/orchestrator/webhooks/telegram", json={"message": {"from": {"id": 123456789}, "text": "web dev"}})
    client.post("/api/orchestrator/webhooks/telegram", json={"message": {"from": {"id": 123456789}, "text": "5"}})

    # Step 6 prompt
    res = client.post("/api/orchestrator/webhooks/telegram", json={"message": {"from": {"id": 123456789}, "text": "60"}})
    assert "Step 6/6" in res.json()["reply"]

    # Answer NO via button callback
    res_launch = client.post("/api/orchestrator/webhooks/telegram", json={
        "callback_query": {"from": {"id": 123456789}, "data": "wizard_template:no"}
    })
    assert res_launch.status_code == 200
    launch_data = res_launch.json()

    # Sub-Campaign 1 preview should have Approve Batch 1 AND Review 1-by-1
    assert any(btn["callback_data"].startswith("subcamp_approve:") for row in launch_data["buttons"] for btn in row)
    assert any(btn["callback_data"].startswith("start_review:") for row in launch_data["buttons"] for btn in row)
    assert "Review 1-by-1" in launch_data["reply"]


def test_quick_command_best_response_flag(client, db_session, auth_settings):
    res = client.post("/api/orchestrator/webhooks/telegram", json={
        "message": {"from": {"id": 123456789}, "text": "/findleads Dental Clinics in Dallas, Texas 5 60 yes"}
    })
    assert res.status_code == 200
    data = res.json()
    assert not any(btn["callback_data"].startswith("start_review:") for row in data["buttons"] for btn in row)
    assert "Review 1-by-1" not in data["reply"]
