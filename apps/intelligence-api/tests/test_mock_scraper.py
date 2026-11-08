from fastapi import FastAPI
from httpx import ASGITransport, Client

from app.providers.mock_scraper import mock_scraper_router
from app.providers.scraper_client import ScraperClient


def _asgi_client() -> Client:
    app = FastAPI()
    app.include_router(mock_scraper_router)
    return Client(transport=ASGITransport(app=app), base_url="http://testserver")


def test_mock_job_returns_labeled_mock_results():
    client = ScraperClient(base_url="", token="", provider="mock")
    job_id = client.create_job("real estate", "Dallas, Texas", 25, {})
    result = client.get_job(job_id)
    assert result.status == "completed"
    assert len(result.results) == 9
    assert all(r.discovery_source == "mock" for r in result.results)


def test_mock_job_completes_immediately_via_asgi():
    with _asgi_client() as http:
        created = http.post(
            "/scraper/jobs",
            json={
                "query": "real estate",
                "location": "Dallas, Texas",
                "limit": 25,
                "filters": {},
            },
        )
        assert created.status_code == 200
        body = created.json()
        job_id = body["job_id"]
        assert body["status"] == "completed"
        got = http.get(f"/scraper/jobs/{job_id}")
        assert got.status_code == 200
        payload = got.json()
        assert payload["status"] == "completed"
        assert len(payload["results"]) == 9
        assert all("discovery_source" not in row for row in payload["results"])
        oak = [r for r in payload["results"] if r["placeId"] == "ChIJ-noweb"]
        assert len(oak) == 2
        assert {r["phone"] for r in oak} == {"+1 214-555-0101", "+1 214-555-0199"}


def test_mock_job_applies_limit():
    with _asgi_client() as http:
        created = http.post(
            "/scraper/jobs",
            json={
                "query": "real estate",
                "location": "Dallas, Texas",
                "limit": 3,
                "filters": {},
            },
        )
        job_id = created.json()["job_id"]
        payload = http.get(f"/scraper/jobs/{job_id}").json()
        assert len(payload["results"]) == 3


def test_duplicate_included_when_query_matches_real_estate():
    with _asgi_client() as http:
        created = http.post(
            "/scraper/jobs",
            json={
                "query": "real estate",
                "location": "Dallas, Texas",
                "limit": 25,
                "filters": {},
            },
        )
        payload = http.get(f"/scraper/jobs/{created.json()['job_id']}").json()
        place_ids = [r["placeId"] for r in payload["results"]]
        assert place_ids.count("ChIJ-noweb") == 2
