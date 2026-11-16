import uuid
import pytest
from app.models import Business, Campaign, Lead, MessageDraft
from app.config import Settings
from app.services.campaigns import create_campaign
from app.services.social import get_business_social_links, get_lead_messages, sanitize_website
from app.services.telegram_bot import generate_campaign_csv, format_approval_card, handle_telegram_update


def test_sanitize_website():
    assert sanitize_website("Apex Dental", None) == ""
    assert sanitize_website("Apex Dental", "") == ""
    assert sanitize_website("Apex Dental", "https://www.apexdental.com") == "https://www.apexdental.com"
    # Replaces fixtures.intentlead.test
    sanitized = sanitize_website("Apex Dental", "https://fixtures.intentlead.test/explicit_intent?biz=101")
    assert "fixtures" not in sanitized
    assert "test" not in sanitized
    assert "apexdental" in sanitized
    assert sanitized.startswith("https://www.")


def test_get_business_social_links_from_dict():
    data = {
        "name": "Dr Smile Dental",
        "phone": "+1 305-555-1234",
        "source_fields": {
            "social_links": {
                "linkedin": "https://linkedin.com/company/drsmile",
                "facebook": "https://facebook.com/drsmile",
                "instagram": "https://instagram.com/drsmile",
                "twitter": "https://x.com/drsmile",
                "reddit": "https://reddit.com/user/drsmile",
                "telegram": "https://t.me/drsmile_official",
            }
        }
    }
    socials = get_business_social_links(data)
    assert socials["linkedin"] == "https://linkedin.com/company/drsmile"
    assert socials["facebook"] == "https://facebook.com/drsmile"
    assert socials["instagram"] == "https://instagram.com/drsmile"
    assert socials["twitter"] == "https://x.com/drsmile"
    assert socials["reddit"] == "https://reddit.com/user/drsmile"
    assert socials["telegram"] == "https://t.me/drsmile_official"


def test_get_business_social_links_phone_fallback_telegram():
    data = {
        "name": "Apex Cleaners",
        "phone": "+1 (305) 555-9876",
        "source_fields": {}
    }
    socials = get_business_social_links(data)
    assert socials["telegram"] == "https://t.me/+13055559876"
    assert socials["linkedin"] == ""
    assert socials["facebook"] == ""


def test_generate_campaign_csv_includes_social_columns(db):
    camp = Campaign(
        id=uuid.uuid4(),
        niche="Orthodontics",
        location="Miami",
        requested_quantity=1,
        provider="mock",
        target_services=["website_redesign"],
        filters={},
        dry_run=True,
        status="completed",
    )
    db.add(camp)
    db.flush()

    biz = Business(
        id=uuid.uuid4(),
        identity_key="test:ortho_1",
        name="Miami Ortho Care",
        address="100 Biscayne Blvd",
        locality="Miami",
        website="https://fixtures.intentlead.test/explicit_intent",
        phone="+1 305-555-7788",
        email="contact@miamiortho.com",
        rating=4.9,
        review_count=120,
        source_fields={
            "social_links": {
                "linkedin": "https://linkedin.com/company/miamiortho",
                "facebook": "https://facebook.com/miamiortho",
                "instagram": "https://instagram.com/miamiortho",
                "twitter": "https://x.com/miamiortho",
                "reddit": "https://reddit.com/user/miamiortho",
                "telegram": "https://t.me/miamiortho",
            }
        },
        discovery_source="mock",
    )
    db.add(biz)
    db.flush()

    lead = Lead(
        id=uuid.uuid4(),
        campaign_id=camp.id,
        business_id=biz.id,
        overall_score=92,
        priority="A",
        confidence="high",
        recommended_service="ai_chatbot",
        outreach_status="draft",
        crm_stage="qualified",
    )
    db.add(lead)
    db.flush()

    csv_data = generate_campaign_csv(db, camp.id)
    header = csv_data.strip().split("\n")[0]
    row = csv_data.strip().split("\n")[1]

    # Verify header contains all requested social platforms and address
    for col in ["website", "address", "linkedin", "facebook", "instagram", "twitter", "reddit", "telegram"]:
        assert col in header

    # Verify website was sanitized (no fixtures.intentlead.test)
    assert "fixtures.intentlead.test" not in row
    assert "https://www.miamiortho" in row

    # Verify social values are in the row
    assert "https://linkedin.com/company/miamiortho" in row
    assert "https://facebook.com/miamiortho" in row
    assert "https://instagram.com/miamiortho" in row
    assert "https://x.com/miamiortho" in row
    assert "https://reddit.com/user/miamiortho" in row
    assert "https://t.me/miamiortho" in row


def test_format_approval_card_has_telegram_button(db):
    biz = Business(
        id=uuid.uuid4(),
        identity_key="test:ortho_card",
        name="Sunny Dental",
        address="200 Ocean Dr",
        locality="Miami",
        website="https://www.sunnydental.com",
        phone="+1 305-555-3344",
        source_fields={},
        discovery_source="mock",
    )
    lead = Lead(
        id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        business_id=biz.id,
        overall_score=85,
        priority="A",
        confidence="high",
        recommended_service="ai_chatbot",
        outreach_status="draft",
        crm_stage="qualified",
    )
    card_text, buttons = format_approval_card(lead, biz, None, [])
    assert "Telegram" in card_text
    # Verify inline direct Telegram button exists
    telegram_button_found = any(
        btn.get("text") == "💬 Open Telegram Chat" and "t.me" in btn.get("url", "")
        for row in buttons
        for btn in row
    )
    assert telegram_button_found


def test_exit_review_mode_and_approved_messages_in_csv(db):
    settings = Settings(TELEGRAM_ALLOWED_USER_ID="12345")
    camp = Campaign(
        id=uuid.uuid4(),
        niche="Dental Clinics",
        location="Miami",
        requested_quantity=5,
        provider="mock",
        target_services=["website_redesign"],
        filters={},
        dry_run=True,
        status="completed",
    )
    db.add(camp)
    db.flush()

    leads = []
    for i in range(1, 6):
        biz = Business(
            id=uuid.uuid4(),
            identity_key=f"test:dentist_{i}",
            name=f"Clinic {i}",
            address=f"{100*i} Biscayne Blvd",
            locality="Miami",
            website=f"https://www.clinic{i}.com",
            phone=f"+1 305-555-000{i}",
            email=f"contact@clinic{i}.com",
            rating=4.5,
            review_count=50,
            source_fields={},
            discovery_source="mock",
        )
        db.add(biz)
        db.flush()

        lead = Lead(
            id=uuid.uuid4(),
            campaign_id=camp.id,
            business_id=biz.id,
            overall_score=85 + i,
            priority="A",
            confidence="high",
            recommended_service="ai_chatbot",
            outreach_status="draft",
            crm_stage="qualified",
        )
        db.add(lead)
        db.flush()

        # Initial draft created by pipeline
        draft = MessageDraft(
            lead_id=lead.id,
            channel="preview",
            status="preview",
            body=f"Initial draft message for Clinic {i}",
            evidence_ids=[],
        )
        db.add(draft)
        db.flush()
        leads.append((lead, biz))

    # Lead 1: User regenerates AI pitch and approves
    ai_draft_1 = MessageDraft(
        lead_id=leads[0][0].id,
        channel="ai_regenerated",
        status="preview",
        body="AI custom pitch for Clinic 1",
        evidence_ids=[],
    )
    db.add(ai_draft_1)
    db.flush()

    # Approve Lead 1 via callback
    handle_telegram_update(
        {"callback_query": {"from": {"id": 12345}, "data": f"review_approve:{leads[0][0].id}"}},
        db,
        settings,
    )

    # Lead 2: User regenerates AI pitch and approves
    ai_draft_2 = MessageDraft(
        lead_id=leads[1][0].id,
        channel="ai_regenerated",
        status="preview",
        body="AI custom pitch for Clinic 2",
        evidence_ids=[],
    )
    db.add(ai_draft_2)
    db.flush()

    # Approve Lead 2 via callback
    handle_telegram_update(
        {"callback_query": {"from": {"id": 12345}, "data": f"review_approve:{leads[1][0].id}"}},
        db,
        settings,
    )

    # Now on Lead 3, user decides to EXIT review mode
    exit_res = handle_telegram_update(
        {"callback_query": {"from": {"id": 12345}, "data": f"review_exit:{camp.id}"}},
        db,
        settings,
    )

    assert exit_res["status"] == "success"
    assert "Review Paused" in exit_res["reply"]
    assert "2 approved" in exit_res["reply"]
    assert "3 remaining pending" in exit_res["reply"]

    # Verify buttons offered
    buttons = exit_res["buttons"]
    bulk_approve_btn = any(btn.get("callback_data") == f"bulk_approve:{camp.id}:80" for row in buttons for btn in row)
    resume_btn = any(btn.get("callback_data") == f"start_review:{camp.id}:80" for row in buttons for btn in row)
    export_btn = any(btn.get("callback_data") == f"export_csv:{camp.id}" for row in buttons for btn in row)

    assert bulk_approve_btn
    assert resume_btn
    assert export_btn

    # User chooses option to Approve All Remaining (3)
    bulk_res = handle_telegram_update(
        {"callback_query": {"from": {"id": 12345}, "data": f"bulk_approve:{camp.id}:80"}},
        db,
        settings,
    )
    assert bulk_res["status"] == "success"
    assert "3 qualified leads" in bulk_res["reply"]

    # All 5 leads are now approved!
    approved_leads = db.query(Lead).filter_by(campaign_id=camp.id, outreach_status="approved").count()
    assert approved_leads == 5

    # Check generated CSV
    csv_str = generate_campaign_csv(db, camp.id)
    lines = csv_str.strip().split("\n")
    header = lines[0].split(",")

    assert "drafts" in header
    assert "approved_messages" in header
    draft_idx = header.index("drafts")
    appr_idx = header.index("approved_messages")

    import csv as py_csv
    reader = list(py_csv.reader(lines))
    # Leads are ordered by overall_score desc (i=5, 4, 3, 2, 1)
    rows_by_name = {row[1]: row for row in reader[1:]}

    # Clinic 1 had AI pitch
    assert rows_by_name["Clinic 1"][draft_idx] == "Initial draft message for Clinic 1"
    assert rows_by_name["Clinic 1"][appr_idx] == "AI custom pitch for Clinic 1"

    # Clinic 2 had AI pitch
    assert rows_by_name["Clinic 2"][draft_idx] == "Initial draft message for Clinic 2"
    assert rows_by_name["Clinic 2"][appr_idx] == "AI custom pitch for Clinic 2"

    # Clinic 3, 4, 5 were bulk approved with their initial drafts
    for i in (3, 4, 5):
        name = f"Clinic {i}"
        assert rows_by_name[name][draft_idx] == f"Initial draft message for Clinic {i}"
        assert rows_by_name[name][appr_idx] == f"Initial draft message for Clinic {i}"

