from app.models import Evidence
from app.scoring.engine import score_lead
from app.scoring import reasons


def test_golden_no_website():
    listing = {
        "title": "Oak Lawn Realty",
        "category": "Real estate agency",
        "address": "3900 Oak Lawn Ave, Dallas, TX 75219",
        "locality": "Dallas",
        "website": None,
        "phone": "+1 214-555-0101",
        "email": None,
        "listing_status": "open",
    }
    evidence = []
    res = score_lead(listing, evidence)

    dim_map = {d.dimension: d for d in res.dimensions}
    assert dim_map["website_opportunity"].points == 25
    assert dim_map["website_opportunity"].reason_code == reasons.NO_WEBSITE_URL
    assert dim_map["lead_capture_opportunity"].points == 18
    assert dim_map["lead_capture_opportunity"].reason_code == reasons.NO_WEBSITE_URL
    assert dim_map["automation_opportunity"].points == 0
    assert dim_map["automation_opportunity"].reason_code == reasons.UNKNOWN_NOT_INSPECTED
    assert dim_map["business_suitability"].points == 15
    assert dim_map["business_suitability"].reason_code == reasons.NICHE_ACTIVE
    assert dim_map["buying_intent_evidence"].points == 0
    assert dim_map["buying_intent_evidence"].reason_code == reasons.NO_EXPLICIT_INTENT
    assert dim_map["contactability"].points == 4
    assert dim_map["contactability"].reason_code == reasons.PUBLIC_PHONE

    assert res.overall_score == 62
    assert res.priority == "C"

    svc_map = {s.service: s for s in res.service_scores}
    assert svc_map["website_development"].points == 70
    assert svc_map["website_redesign"].points == 0
    assert res.recommended_service == "website_development"


def test_unreachable_website():
    listing = {
        "title": "Deep Ellum Property Group",
        "category": "Real estate agency",
        "address": "2650 Main St",
        "locality": "Dallas",
        "website": "https://fixtures.intentlead.test/unreachable",
        "phone": "+1 214-555-0102",
        "listing_status": "open",
    }
    evidence = [
        Evidence(
            claim="Website unreachable",
            evidence_type="verified_observation",
            source_url=listing["website"],
            supporting_excerpt="website_unreachable",
        )
    ]
    res = score_lead(listing, evidence)
    dim_map = {d.dimension: d for d in res.dimensions}
    assert dim_map["website_opportunity"].points == 22
    assert dim_map["lead_capture_opportunity"].points == 18
    assert dim_map["automation_opportunity"].points == 0
    assert res.overall_score == 59
    assert res.priority == "C"

    svc_map = {s.service: s for s in res.service_scores}
    assert svc_map["website_development"].points == 50
    assert res.recommended_service == "website_development"


def test_brochure_site():
    listing = {
        "title": "Bishop Arts Homes",
        "category": "Real estate agency",
        "address": "408 W 8th St",
        "locality": "Dallas",
        "website": "https://fixtures.intentlead.test/brochure",
        "phone": "+1 214-555-0103",
        "listing_status": "open",
    }
    evidence = [
        Evidence(
            claim="No mobile viewport",
            evidence_type="verified_observation",
            source_url=listing["website"],
            supporting_excerpt="no_viewport",
        ),
        Evidence(
            claim="No property search",
            evidence_type="verified_observation",
            source_url=listing["website"],
            supporting_excerpt="missing_listing_search",
        ),
        Evidence(
            claim="No chatbot or booking",
            evidence_type="inference",
            source_url=listing["website"],
            supporting_excerpt="no_visible_chat_or_booking",
        ),
    ]
    res = score_lead(listing, evidence)
    svc_map = {s.service: s for s in res.service_scores}
    assert svc_map["website_redesign"].points == 90
    assert svc_map["real_estate_listing_portal"].points == 80
    assert res.recommended_service == "website_redesign"


def test_visible_widgets_residual():
    listing = {
        "title": "Preston Hollow Estates",
        "category": "Real estate agency",
        "address": "8411 Preston Rd",
        "locality": "Dallas",
        "website": "https://fixtures.intentlead.test/widgets",
        "phone": "+1 214-555-0106",
        "email": "concierge@prestonhollow.test",
        "listing_status": "open",
    }
    evidence = [
        Evidence(
            claim="Chatbot widget visible",
            evidence_type="verified_observation",
            source_url=listing["website"],
            supporting_excerpt="has_chatbot",
        ),
        Evidence(
            claim="Booking widget visible",
            evidence_type="verified_observation",
            source_url=listing["website"],
            supporting_excerpt="has_booking",
        ),
    ]
    res = score_lead(listing, evidence)
    dim_map = {d.dimension: d for d in res.dimensions}
    assert dim_map["automation_opportunity"].points == 0
    assert dim_map["automation_opportunity"].reason_code == reasons.AUTOMATION_ALREADY_VISIBLE

    svc_map = {s.service: s for s in res.service_scores}
    assert svc_map["ai_chatbot"].points == 10
    assert svc_map["ai_chatbot"].reason_code == reasons.RESIDUAL_EXISTING_TOOL
    assert svc_map["crm_appointment_automation"].points == 15
    assert svc_map["crm_appointment_automation"].reason_code == reasons.RESIDUAL_EXISTING_TOOL


def test_explicit_intent_scoring():
    listing = {
        "title": "Design District Properties",
        "category": "Real estate agency",
        "address": "161 Glass St",
        "locality": "Dallas",
        "website": "https://fixtures.intentlead.test/explicit_intent",
        "phone": "+1 214-555-0108",
        "listing_status": "open",
    }
    evidence = [
        Evidence(
            claim="Explicit intent found",
            evidence_type="explicit_intent",
            source_url=listing["website"],
            supporting_excerpt="looking for a vendor",
        )
    ]
    res = score_lead(listing, evidence)
    dim_map = {d.dimension: d for d in res.dimensions}
    assert dim_map["buying_intent_evidence"].points == 15
    assert dim_map["buying_intent_evidence"].reason_code == reasons.EXPLICIT_INTENT_PRESENT


def test_reviews_process_friction():
    listing = {
        "title": "Fair Park Realty",
        "category": "Real estate agency",
        "address": "3809 Grand Ave",
        "locality": "Dallas",
        "website": "https://fixtures.intentlead.test/brochure",
        "phone": "+1 214-555-0107",
        "listing_status": "open",
        "reviews": [
            "Slow to call back",
            "Listing photos were outdated",
            "Office closed early",
            "Would not recommend",
        ],
    }
    evidence = []
    res = score_lead(listing, evidence)
    dim_map = {d.dimension: d for d in res.dimensions}
    assert dim_map["automation_opportunity"].points == 16
    assert dim_map["automation_opportunity"].reason_code == reasons.PUBLIC_PROCESS_FRICTION

    svc_map = {s.service: s for s in res.service_scores}
    assert svc_map["business_process_automation"].points == 40


def test_low_rating_or_review_count_awards_automation_points():
    listing = {
        "title": "Mayfair Estate Agents",
        "category": "Real estate agency",
        "address": "15 Berkeley Square",
        "locality": "London",
        "website": "https://fixtures.intentlead.test/brochure",
        "phone": "+44 20 7946 0101",
        "listing_status": "open",
        "rating": 3.9,
        "review_count": 8,
    }
    evidence = []
    res = score_lead(listing, evidence)
    dim_map = {d.dimension: d for d in res.dimensions}
    assert dim_map["automation_opportunity"].points == 16
    assert dim_map["automation_opportunity"].reason_code == reasons.PUBLIC_PROCESS_FRICTION


def test_service_intent_scoring_real_world_candidate():
    listing = {
        "title": "Somani Realtors Kolkata",
        "category": "Real estate agency",
        "address": "Park Street, Kolkata",
        "locality": "Kolkata",
        "website": "https://fixtures.intentlead.test/brochure",
        "phone": "+91 98300 12345",
        "email": "info@somanirealtors.in",
        "listing_status": "open",
    }
    evidence = [
        Evidence(
            claim="No property search found",
            evidence_type="verified_observation",
            source_url=listing["website"],
            supporting_excerpt="missing_listing_search",
        ),
        Evidence(
            claim="Inquiry form found",
            evidence_type="verified_observation",
            source_url=listing["website"],
            supporting_excerpt="has_form",
        ),
        Evidence(
            claim="No visible chatbot or booking",
            evidence_type="inference",
            source_url=listing["website"],
            supporting_excerpt="no_visible_chat_or_booking",
        ),
    ]
    res = score_lead(listing, evidence, target_services=["real_estate_listing_portal", "ai_chatbot", "crm_appointment_automation"])
    dim_map = {d.dimension: d for d in res.dimensions}

    assert dim_map["website_opportunity"].points == 16
    assert dim_map["lead_capture_opportunity"].points == 14
    assert dim_map["automation_opportunity"].points == 18
    assert dim_map["business_suitability"].points == 15
    assert dim_map["buying_intent_evidence"].points == 15
    assert dim_map["buying_intent_evidence"].reason_code == reasons.SERVICE_GAP_IDENTIFIED
    assert dim_map["contactability"].points == 5

    # Total score should be 83/100 -> Grade A prime target
    assert res.overall_score == 83
    assert res.priority == "A"
    assert res.recommended_service == "real_estate_listing_portal"


def test_already_equipped_enterprise_lead():
    listing = {
        "title": "Corporate Real Estate Enterprise",
        "category": "Real estate agency",
        "address": "Camac Street, Kolkata",
        "locality": "Kolkata",
        "website": "https://fixtures.intentlead.test/widgets",
        "phone": "+91 98300 99999",
        "email": "enterprise@corporate.in",
        "listing_status": "open",
    }
    evidence = [
        Evidence(
            claim="Property search found",
            evidence_type="verified_observation",
            source_url=listing["website"],
            supporting_excerpt="has_listing_search",
        ),
        Evidence(
            claim="Chatbot visible",
            evidence_type="verified_observation",
            source_url=listing["website"],
            supporting_excerpt="has_chatbot",
        ),
        Evidence(
            claim="Booking visible",
            evidence_type="verified_observation",
            source_url=listing["website"],
            supporting_excerpt="has_booking",
        ),
    ]
    res = score_lead(listing, evidence, target_services=["real_estate_listing_portal", "ai_chatbot", "crm_appointment_automation"])
    assert res.overall_score == 28
    assert res.priority == "D"


