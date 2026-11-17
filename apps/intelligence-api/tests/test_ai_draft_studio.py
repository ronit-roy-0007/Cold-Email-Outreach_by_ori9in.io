from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
import uuid

import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import AuditLog, Business, Campaign, Evidence, Lead, MessageDraft, ServiceScore, utc_now
from app.services.gemini_personalizer import (
    GeminiPersonalizationResult,
    generate_gemini_pitch,
    generate_gemini_personalized_draft,
)


@pytest.fixture(autouse=True)
def bypass_gemini_rate_limiter(monkeypatch):
    from app.services import gemini_personalizer
    monkeypatch.setattr(gemini_personalizer._GEMINI_LIMITER, "acquire", lambda: None)


@pytest.fixture
def auth_settings():
    return Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        DISCOVERY_PROVIDER="mock",
        AGENCY_NAME="River Agency",
        AGENCY_SENDER_NAME="Sam Lee",
        USER_LLM_API_KEY="mock_gemini_api_key_test",
        TELEGRAM_ALLOWED_USER_ID="123456789",
        OUTREACH_DRY_RUN=True,
    )


@pytest.fixture
def client(db_session, auth_settings):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: auth_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_lead(db_session):
    biz = Business(
        id=uuid.uuid4(),
        identity_key="apex-realty-austin-tx",
        name="Apex Commercial Realty",
        category="Real Estate",
        locality="Austin, TX",
        website="https://apexrealtyaustin.com",
        phone="+1 512-555-0199",
        email="info@apexrealtyaustin.com",
        source_fields={},
        discovery_source="mock",
    )
    db_session.add(biz)

    camp = Campaign(
        id=uuid.uuid4(),
        niche="Real Estate",
        location="Austin, TX",
        requested_quantity=10,
        target_services=["real_estate_listing_portal"],
        filters={},
        provider="mock",
        status="completed",
    )
    db_session.add(camp)

    lead = Lead(
        id=uuid.uuid4(),
        business_id=biz.id,
        campaign_id=camp.id,
        overall_score=85,
        priority="high",
        confidence="high",
        recommended_service="real_estate_listing_portal",
        outreach_status="draft",
        crm_stage="identified",
    )
    db_session.add(lead)

    ev1 = Evidence(
        id=uuid.uuid4(),
        business_id=biz.id,
        campaign_id=camp.id,
        evidence_type="technical_gap",
        claim="Missing MLS property listing search portal on homepage",
        source_url="https://apexrealtyaustin.com",
        confidence=0.92,
        supporting_excerpt="No search widget found in DOM",
        checked_at=utc_now(),
    )
    db_session.add(ev1)

    svc = ServiceScore(
        id=uuid.uuid4(),
        lead_id=lead.id,
        service="real_estate_listing_portal",
        points=85,
        reason_code="missing_listing_search",
        evidence_ids=[str(ev1.id)],
    )
    db_session.add(svc)

    db_session.commit()
    return lead, biz, camp, ev1


# ==============================================================================
# 1. AI Generate & Regenerate Backend Tests
# ==============================================================================

def test_ai_generate_valid_subject_and_body(client, sample_lead, monkeypatch):
    lead, biz, camp, ev = sample_lead

    # Mock Gemini HTTP response
    mock_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "subject": "Quick question regarding Apex Commercial Realty website",
                                "body": (
                                    "Hi Apex Commercial Realty,\n\n"
                                    "I noticed that your website is currently missing an active MLS listing search "
                                    "portal for commercial buyers in Austin. We recently deployed an MLS-integrated portal "
                                    "for a Texas brokerage that increased buyer inquiries by 40% in 60 days. "
                                    "Would you be open to a brief 5-minute chat this Thursday to see how this works?\n\n"
                                    "Best regards,\nSam Lee"
                                ),
                            })
                        }
                    ]
                }
            }
        ]
    }

    class MockResponse:
        def read(self):
            return json.dumps(mock_payload).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: MockResponse())

    res = client.post(f"/api/leads/{lead.id}/ai-generate")
    assert res.status_code == 200
    data = res.json()

    assert data["success"] is True
    assert data["lead_id"] == str(lead.id)
    assert data["draft"]["subject"] == "Quick question regarding Apex Commercial Realty website"
    assert "Apex Commercial Realty" in data["draft"]["body"]
    assert "MLS listing search" in data["draft"]["body"]
    assert data["generation_id"]
    assert "gemini" in data["model"]

    # CRITICAL SAFEGUARD: Verify generate preview DID NOT persist to database
    draft_in_db = client.app.dependency_overrides[get_session]().query(MessageDraft).filter_by(lead_id=lead.id).first()
    assert draft_in_db is None


def test_ai_generate_lead_specific_evidence_grounding(client, sample_lead, monkeypatch):
    lead, biz, camp, ev = sample_lead
    captured_prompt = []

    class MockResponse:
        def read(self):
            return json.dumps({
                "candidates": [{
                    "content": {"parts": [{"text": json.dumps({"subject": "MLS test", "body": "Hi Apex,\n\nTest body\n\nSam"})}]}
                }]
            }).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def mock_urlopen(req, timeout=None):
        req_body = json.loads(req.data.decode("utf-8"))
        captured_prompt.append(req_body["contents"][0]["parts"][0]["text"])
        return MockResponse()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = client.post(f"/api/leads/{lead.id}/ai-generate")
    assert res.status_code == 200

    assert len(captured_prompt) == 1
    prompt_text = captured_prompt[0]
    assert "Apex Commercial Realty" in prompt_text
    assert "property listing search" in prompt_text


def test_ai_generate_missing_lead(client):
    non_existent = uuid.uuid4()
    res = client.post(f"/api/leads/{non_existent}/ai-generate")
    assert res.status_code == 404
    assert "Lead not found" in res.json()["detail"]


def test_ai_generate_missing_gemini_api_key(client, sample_lead, monkeypatch, auth_settings):
    lead, _, _, _ = sample_lead
    auth_settings.USER_LLM_API_KEY = ""

    res = client.post(f"/api/leads/{lead.id}/ai-generate")
    assert res.status_code == 400
    assert "Gemini API key is not configured" in res.json()["detail"]


def test_ai_generate_gemini_rate_limit(client, sample_lead, monkeypatch):
    lead, _, _, _ = sample_lead

    def mock_rate_limit_error(req, timeout=None):
        raise urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b"Rate limit exceeded"),
        )

    monkeypatch.setattr(urllib.request, "urlopen", mock_rate_limit_error)

    res = client.post(f"/api/leads/{lead.id}/ai-generate")
    assert res.status_code == 429
    assert "rate limit reached" in res.json()["detail"].lower()


def test_ai_generate_gemini_timeout(client, sample_lead, monkeypatch):
    lead, _, _, _ = sample_lead

    def mock_timeout(req, timeout=None):
        raise TimeoutError("Connection timed out after 10.0s")

    monkeypatch.setattr(urllib.request, "urlopen", mock_timeout)

    res = client.post(f"/api/leads/{lead.id}/ai-generate")
    assert res.status_code == 502
    assert "Gemini generation failed" in res.json()["detail"]


def test_ai_generate_empty_candidates_response(client, sample_lead, monkeypatch):
    lead, _, _, _ = sample_lead

    class MockEmptyResponse:
        def read(self):
            return json.dumps({"candidates": []}).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: MockEmptyResponse())

    res = client.post(f"/api/leads/{lead.id}/ai-generate")
    assert res.status_code == 502
    assert "empty candidate list" in res.json()["detail"]


def test_ai_generate_non_json_fallback_parsing(client, sample_lead, monkeypatch):
    lead, biz, _, _ = sample_lead

    # Gemini returns plain text without JSON markdown
    plain_text = (
        "Subject: Modernizing Apex Commercial Realty's listings\n"
        "Hi Apex Commercial Realty,\n\n"
        "I noticed your site does not offer an interactive MLS listing search for visitors. "
        "We built a similar solution for Texas real estate teams that doubled organic inquiries. "
        "Do you have 5 minutes this week to connect?\n\n"
        "Best,\nSam Lee"
    )

    class MockPlainResponse:
        def read(self):
            return json.dumps({
                "candidates": [{"content": {"parts": [{"text": plain_text}]}}]
            }).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: MockPlainResponse())

    res = client.post(f"/api/leads/{lead.id}/ai-generate")
    assert res.status_code == 200
    data = res.json()
    assert data["draft"]["subject"] == "Modernizing Apex Commercial Realty's listings"
    assert "Hi Apex Commercial Realty" in data["draft"]["body"]


# ==============================================================================
# 2. Authentication & Authorization Tests
# ==============================================================================

def test_ai_endpoints_api_key_authentication(client, sample_lead, auth_settings, monkeypatch):
    lead, _, _, _ = sample_lead
    auth_settings.API_KEY = "sec-token-prod-987"

    # 1. Unauthenticated request fails closed with 401
    res = client.post(f"/api/leads/{lead.id}/ai-generate")
    assert res.status_code == 401
    assert "Invalid or missing API key" in res.json()["detail"]

    # 2. Incorrect API key rejected with 401
    res = client.post(f"/api/leads/{lead.id}/ai-generate", headers={"X-API-Key": "wrong-key"})
    assert res.status_code == 401

    # 3. Same-origin web operator request is authorized without exposing API key
    class MockResp:
        def read(self):
            return json.dumps({
                "candidates": [{"content": {"parts": [{"text": json.dumps({"subject": "Sec Test", "body": "Hi Apex,\n\nBody\n\nSam"})}]}}]
            }).encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout=None: MockResp())

    res = client.post(
        f"/api/leads/{lead.id}/ai-generate",
        headers={"Sec-Fetch-Site": "same-origin"}
    )
    assert res.status_code == 200

    # 4. Valid X-API-Key header is authorized
    res = client.post(
        f"/api/leads/{lead.id}/ai-generate",
        headers={"X-API-Key": "sec-token-prod-987"}
    )
    assert res.status_code == 200


# ==============================================================================
# 3. Draft Save, Retrieval, Concurrency & Persistence Tests
# ==============================================================================

def test_save_and_retrieve_ai_draft(client, sample_lead, db_session):
    lead, _, _, _ = sample_lead

    # 1. Initially no draft exists
    get_res = client.get(f"/api/leads/{lead.id}/ai-draft")
    assert get_res.status_code == 200
    assert get_res.json()["has_draft"] is False

    # 2. Save a new draft (first creation -> version 1)
    save_payload = {
        "subject": "Initial Operator Edited Subject",
        "body": "Hi Apex Commercial Realty,\n\nCustom edited pitch.\n\nBest,\nSam",
        "version": 1,
    }
    put_res = client.put(f"/api/leads/{lead.id}/ai-draft", json=save_payload)
    assert put_res.status_code == 200
    save_data = put_res.json()

    assert save_data["success"] is True
    assert save_data["draft"]["subject"] == "Initial Operator Edited Subject"
    assert save_data["draft"]["version"] == 1
    assert save_data["draft"]["status"] == "preview"

    # 3. Update the draft (version increments from 1 -> 2)
    update_payload = {
        "subject": "Updated Operator Subject",
        "body": "Hi Apex Commercial Realty,\n\nUpdated pitch.\n\nBest,\nSam",
        "version": 1,
    }
    update_res = client.put(f"/api/leads/{lead.id}/ai-draft", json=update_payload)
    assert update_res.status_code == 200
    assert update_res.json()["draft"]["version"] == 2

    # 4. Verify in PostgreSQL/SQLite database
    draft_record = db_session.query(MessageDraft).filter_by(lead_id=lead.id).first()
    assert draft_record is not None
    assert draft_record.subject == "Updated Operator Subject"
    assert draft_record.version == 2
    assert draft_record.body == update_payload["body"]

    # CRITICAL SAFEGUARDS: Outreach status NOT approved, no email sent
    lead_in_db = db_session.get(Lead, lead.id)
    assert lead_in_db.outreach_status == "draft"

    # Audit log check
    audit = db_session.query(AuditLog).filter_by(action="save_ai_draft", entity_id=lead.id).order_by(AuditLog.created_at.desc()).first()
    assert audit is not None
    assert audit.payload["subject"] == "Updated Operator Subject"

    # 5. Retrieve via GET endpoint
    ret_res = client.get(f"/api/leads/{lead.id}/ai-draft")
    assert ret_res.status_code == 200
    ret_data = ret_res.json()
    assert ret_data["has_draft"] is True
    assert ret_data["draft"]["subject"] == "Updated Operator Subject"
    assert ret_data["draft"]["version"] == 2


def test_save_draft_validation(client, sample_lead):
    lead, _, _, _ = sample_lead

    # Empty subject rejected
    res = client.put(f"/api/leads/{lead.id}/ai-draft", json={"subject": "", "body": "Body text"})
    assert res.status_code == 422 or res.status_code == 400

    # Empty body rejected
    res = client.put(f"/api/leads/{lead.id}/ai-draft", json={"subject": "Subject text", "body": "   "})
    assert res.status_code == 400


def test_optimistic_concurrency_conflict(client, sample_lead):
    lead, _, _, _ = sample_lead

    # First save -> creates draft with version 1
    r1 = client.put(f"/api/leads/{lead.id}/ai-draft", json={
        "subject": "V1 Subject",
        "body": "V1 Body",
        "version": 1,
    })
    assert r1.status_code == 200
    assert r1.json()["draft"]["version"] == 1

    # Second save -> updates draft to version 2
    r2 = client.put(f"/api/leads/{lead.id}/ai-draft", json={
        "subject": "V2 Subject",
        "body": "V2 Body",
        "version": 1,
    })
    assert r2.status_code == 200
    assert r2.json()["draft"]["version"] == 2

    # Third save with outdated version (version 1 instead of 2) -> 409 Conflict
    res = client.put(f"/api/leads/{lead.id}/ai-draft", json={
        "subject": "Conflicting Subject",
        "body": "Conflicting Body",
        "version": 1,
    })
    assert res.status_code == 409
    assert "Conflict" in res.json()["detail"]


def test_regeneration_does_not_overwrite_saved_draft(client, sample_lead, db_session, monkeypatch):
    lead, _, _, _ = sample_lead

    # 1. Operator saves a customized draft
    client.put(f"/api/leads/{lead.id}/ai-draft", json={
        "subject": "Preserved Operator Subject",
        "body": "Preserved Operator Body",
        "version": 1,
    })

    # 2. Operator clicks Regenerate
    class MockRegenResp:
        def read(self):
            return json.dumps({
                "candidates": [{
                    "content": {"parts": [{"text": json.dumps({
                        "subject": "Brand New AI Generated Subject",
                        "body": "Brand New AI Generated Body",
                    })}]}
                }]
            }).encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout=None: MockRegenResp())

    regen_res = client.post(f"/api/leads/{lead.id}/ai-generate/regenerate")
    assert regen_res.status_code == 200
    regen_data = regen_res.json()
    assert regen_data["draft"]["subject"] == "Brand New AI Generated Subject"

    # 3. Database MUST still have the saved draft, unaffected by regeneration preview
    db_session.expire_all()
    saved = db_session.query(MessageDraft).filter_by(lead_id=lead.id).first()
    assert saved.subject == "Preserved Operator Subject"
    assert saved.body == "Preserved Operator Body"


# ==============================================================================
# 4. Frontend Lead Detail & AI Draft Studio UI Tests
# ==============================================================================

def test_lead_detail_html_renders_ai_draft_studio(client, sample_lead):
    lead, biz, _, _ = sample_lead

    res = client.get(f"/leads/{lead.id}")
    assert res.status_code == 200
    html = res.text

    # Section heading and buttons
    assert "AI Draft Studio" in html
    assert "Generate with AI" in html
    assert 'id="btn-ai-generate"' in html
    assert 'id="btn-ai-regenerate"' in html
    assert 'id="btn-save-draft"' in html

    # Editable fields
    assert 'id="draft-subject-input"' in html
    assert 'id="draft-body-textarea"' in html

    # Clipboard action buttons
    assert 'id="btn-copy-subject"' in html
    assert 'id="btn-copy-body"' in html
    assert 'id="btn-copy-full"' in html

    # Safeguard badge & notice
    assert "Safeguard: Dry-run mode active. Generating or saving a draft does not send emails" in html


def test_saved_draft_rendered_in_html_after_reload(client, sample_lead):
    lead, _, _, _ = sample_lead

    # Save draft
    client.put(f"/api/leads/{lead.id}/ai-draft", json={
        "subject": "Persistent Subject Check",
        "body": "Persistent Body Check",
        "version": 1,
    })

    # Reload page
    res = client.get(f"/leads/{lead.id}")
    assert res.status_code == 200
    html = res.text

    assert "Persistent Subject Check" in html
    assert "Persistent Body Check" in html
    assert "Saved (v1)" in html


# ==============================================================================
# 5. Telegram & Shared Personalization Engine Regressions
# ==============================================================================

def test_shared_engine_generate_gemini_pitch_backward_compatible(sample_lead, monkeypatch, auth_settings):
    lead, biz, _, ev = sample_lead

    class MockResp:
        def read(self):
            return json.dumps({
                "candidates": [{
                    "content": {"parts": [{"text": json.dumps({
                        "subject": "Pitch Subject",
                        "body": "Hi Apex Commercial Realty,\n\nPitch body line.\n\nSam",
                    })}]}
                }]
            }).encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout=None: MockResp())

    # Direct call as done by Telegram bot
    pitch = generate_gemini_pitch(
        business=biz,
        lead=lead,
        evidence=[ev],
        settings=auth_settings,
        sender_name="Sam",
        agency_name="River Agency",
    )
    assert pitch is not None
    assert "Hi Apex Commercial Realty" in pitch
    assert "Pitch body line" in pitch
