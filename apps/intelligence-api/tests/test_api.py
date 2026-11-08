import pytest
from starlette.testclient import TestClient

from app.db import get_session
from app.main import app


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


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
    assert "Dry-run mode" in html
    assert "Approve & Send" not in html

    detail_html = client.get(f"/leads/{leads[0]['id']}").text
    assert "Approve & Send" not in detail_html
    assert "Dry-run mode" in detail_html


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
