from unittest.mock import MagicMock, patch
import json
import uuid

from app.config import Settings
from app.models import Business, Evidence, Lead
from app.services.gemini_personalizer import generate_gemini_pitch


def test_gemini_personalizer_empty_key_returns_none():
    settings = Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        USER_LLM_API_KEY="",
    )
    biz = Business(
        id=uuid.uuid4(),
        name="Apex Properties",
        locality="London",
        rating=4.1,
        review_count=18,
        source_fields={},
    )
    lead = Lead(
        id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        business_id=biz.id,
        overall_score=85,
        priority="A",
        confidence="high",
        recommended_service="lead_management_followup",
    )
    pitch = generate_gemini_pitch(
        business=biz,
        lead=lead,
        evidence=[],
        settings=settings,
    )
    assert pitch is None


def test_gemini_personalizer_success_with_mock():
    settings = Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        USER_LLM_API_KEY="test-gemini-key",
        USER_LLM_MODEL="gemini-1.5-flash",
        AGENCY_NAME="ori9in.io",
        AGENCY_SENDER_NAME="Roy",
    )
    biz = Business(
        id=uuid.uuid4(),
        name="London Prime Realty",
        locality="London",
        rating=3.9,
        review_count=14,
        source_fields={"reviews": ["Slow response to inquiries"]},
    )
    lead = Lead(
        id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        business_id=biz.id,
        overall_score=88,
        priority="A",
        confidence="high",
        recommended_service="lead_management_followup",
    )
    ev = Evidence(
        id=uuid.uuid4(),
        business_id=biz.id,
        campaign_id=lead.campaign_id,
        claim="No property search found",
        evidence_type="verified_observation",
        confidence="high",
    )

    mock_resp_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                "Hi London Prime Realty,\n\n"
                                "I noticed your 3.9★ Google rating and feedback regarding response times in London. "
                                "We help local agencies install 24/7 AI lead handling that captures inquiries instantly and turns happy clients into 5-star reviews on autopilot. "
                                "Open to a quick 2-minute walkthrough of how this works for London teams?\n\n"
                                "Best,\nRoy\nori9in.io"
                            )
                        }
                    ]
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_resp_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        pitch = generate_gemini_pitch(
            business=biz,
            lead=lead,
            evidence=[ev],
            settings=settings,
        )

    assert pitch is not None
    assert "London Prime Realty" in pitch
    assert "3.9★" in pitch
    assert "Roy" in pitch
    assert "ori9in.io" in pitch
