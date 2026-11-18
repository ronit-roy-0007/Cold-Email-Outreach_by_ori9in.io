import pytest
from starlette.testclient import TestClient

from app.config import get_settings
from app.db import get_session
from app.main import app




def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_create_mock_campaign_and_list_leads(client):
    payload = {
        "niche": "Real Estate Agencies",
        "location": "Dallas, Texas",
        "requested_quantity": 25,
        "target_services": ["website_development", "website_redesign"],
        "filters": {},
    }
    r = client.post("/api/campaigns", json=payload)
    assert r.status_code == 201
    camp_id = r.json()["id"]

    leads_res = client.get(f"/api/leads?campaign_id={camp_id}")
    assert leads_res.status_code == 200
    leads = leads_res.json()
    assert len(leads) > 0
    assert all(x["discovery_source"] == "mock" for x in leads)

    # UI checks
    html = client.get("/").text
    assert "Outreach" in html
    assert "Approve & Send" not in html

    detail_html = client.get(f"/leads/{leads[0]['id']}").text
    assert "Approve & Send" not in detail_html
    assert "Outreach" in detail_html


def test_export_csv(client):
    payload = {
        "niche": "Real Estate Agencies",
        "location": "Dallas, Texas",
        "requested_quantity": 5,
        "target_services": ["website_development"],
        "filters": {},
    }
    r = client.post("/api/campaigns", json=payload)
    camp_id = r.json()["id"]

    csv_res = client.get(f"/campaigns/{camp_id}/export.csv")
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers.get("content-type", "")
    content = csv_res.text
    assert "name,location,overall_score" in content


def test_delete_campaign(client, db_session):
    import uuid
    from app.models import Campaign, Lead, DimensionScore, ScrapeJob, Evidence

    payload = {
        "niche": "Roofing Contractors",
        "location": "Miami, Florida",
        "requested_quantity": 5,
        "target_services": ["website_development"],
        "filters": {},
    }
    r = client.post("/api/campaigns", json=payload)
    assert r.status_code == 201
    camp_id = uuid.UUID(r.json()["id"])

    # Verify entities were created in DB
    assert db_session.query(Campaign).filter_by(id=camp_id).first() is not None
    leads_before = db_session.query(Lead).filter_by(campaign_id=camp_id).all()
    assert len(leads_before) > 0
    lead_ids = [l.id for l in leads_before]
    assert db_session.query(DimensionScore).filter(DimensionScore.lead_id.in_(lead_ids)).count() > 0
    assert db_session.query(ScrapeJob).filter_by(campaign_id=camp_id).first() is not None

    # Delete campaign via API
    del_res = client.delete(f"/api/campaigns/{camp_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Verify everything related to the campaign is completely wiped from database
    assert db_session.query(Campaign).filter_by(id=camp_id).first() is None
    assert db_session.query(Lead).filter_by(campaign_id=camp_id).count() == 0
    assert db_session.query(DimensionScore).filter(DimensionScore.lead_id.in_(lead_ids)).count() == 0
    assert db_session.query(ScrapeJob).filter_by(campaign_id=camp_id).first() is None
    assert db_session.query(Evidence).filter_by(campaign_id=camp_id).count() == 0

    # Verify GET returns 404
    get_res = client.get(f"/api/campaigns/{camp_id}")
    assert get_res.status_code == 404
