import uuid
from app.models import Evidence
from app.scoring.engine import ServiceScoreResult
from app.services.drafts import build_draft


def test_blank_identity_not_recommended():
    r = build_draft(
        agency_name="",
        sender_name="",
        business_name="Acme",
        recommended_service="website_development",
        evidence=[],
        service_scores=[],
    )
    assert r.status == "draft_not_recommended"
    assert r.reason == "agency_identity_not_configured"
    assert r.body is None


def test_does_not_invent_sender():
    r = build_draft(
        agency_name="",
        sender_name="",
        business_name="Acme",
        recommended_service="website_development",
        evidence=[],
        service_scores=[],
    )
    assert r.body is None or "Alex" not in (r.body or "")


def test_residual_chatbot_no_false_gap():
    svc = [
        ServiceScoreResult(
            service="ai_chatbot",
            points=10,
            evidence_ids=[],
            reason_code="residual_existing_tool",
        )
    ]
    r = build_draft(
        agency_name="River Agency",
        sender_name="Sam Lee",
        business_name="Acme",
        recommended_service="ai_chatbot",
        evidence=[],
        service_scores=svc,
    )
    assert r.status == "draft_not_recommended"
    assert "no chatbot" not in (r.body or "").lower()


def test_preview_mentions_verified_observation():
    ev_id = uuid.uuid4()
    ev = Evidence(
        id=ev_id,
        claim="No property search was visible on the inspected website pages",
        evidence_type="verified_observation",
        source_url="https://example.com",
        supporting_excerpt="missing_listing_search",
    )
    svc = [
        ServiceScoreResult(
            service="real_estate_listing_portal",
            points=80,
            evidence_ids=[str(ev_id)],
            reason_code="missing_listing_search",
        )
    ]
    r = build_draft(
        agency_name="River Agency",
        sender_name="Sam Lee",
        business_name="Acme Realty",
        recommended_service="real_estate_listing_portal",
        evidence=[ev],
        service_scores=svc,
    )
    assert r.status == "preview"
    assert "Sam Lee" in r.body
    assert "River Agency" in r.body
    assert "listing" in r.body.lower()
    assert str(ev_id) in r.evidence_ids


def test_never_sent_status():
    r = build_draft(
        agency_name="River Agency",
        sender_name="Sam Lee",
        business_name="Acme",
        recommended_service="website_development",
        evidence=[],
        service_scores=[],
    )
    assert r.status in {"preview", "draft_not_recommended"}


def test_draft_includes_rating_and_review_count_pitch():
    r = build_draft(
        agency_name="ori9in.io",
        sender_name="Roy",
        business_name="London Premier Properties",
        recommended_service="lead_management_followup",
        evidence=[],
        service_scores=[],
        rating=3.9,
        review_count=12,
    )
    assert r.status == "preview"
    assert "3.9★" in r.body
    assert "12 reviews" in r.body
    assert "review system" in r.body.lower()
    assert "online presence and inbound sales" in r.body.lower()

