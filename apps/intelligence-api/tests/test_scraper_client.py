import httpx
import pytest

from app.providers.scraper_client import ScraperClient, ScraperError, map_gosom_listing
from app.providers.types import NormalizedListing


def test_live_client_does_not_swap_in_mock_on_failure(monkeypatch):
    client = ScraperClient(base_url="http://127.0.0.1:9", token="", provider="live")
    with pytest.raises(ScraperError):
        client.create_job("real estate", "Dallas, Texas", 5, {})


def test_live_missing_base_url_raises():
    client = ScraperClient(base_url="", token="", provider="live")
    with pytest.raises(ScraperError, match="GOOGLE_MAPS_SCRAPER_BASE_URL missing"):
        client.create_job("real estate", "Dallas, Texas", 5, {})


def test_mock_provider_does_not_call_live_url():
    client = ScraperClient(base_url="http://127.0.0.1:9", token="", provider="mock")
    job_id = client.create_job("real estate", "Dallas, Texas", 5, {})
    result = client.get_job(job_id)
    assert result.status == "completed"
    assert len(result.results) == 5
    assert all(isinstance(r, NormalizedListing) for r in result.results)
    assert all(r.discovery_source == "mock" for r in result.results)


def test_maps_gosom_json_to_normalized_listing():
    raw = {
        "title": "Oak Lawn Realty",
        "category": "Real estate agency",
        "address": "3900 Oak Lawn Ave, Dallas, TX 75219",
        "locality": "Dallas",
        "website": "https://example.com",
        "phone": "+1 214-555-0101",
        "emails": ["info@oaklawn.test", "other@oaklawn.test"],
        "rating": 4.2,
        "reviewCount": 27,
        "placeId": "ChIJ-noweb",
        "reviews": ["Responsive agent"],
        "listingStatus": "open",
    }
    listing = map_gosom_listing(raw, "live")
    assert listing.place_id == "ChIJ-noweb"
    assert listing.name == "Oak Lawn Realty"
    assert listing.category == "Real estate agency"
    assert listing.address == "3900 Oak Lawn Ave, Dallas, TX 75219"
    assert listing.locality == "Dallas"
    assert listing.website == "https://example.com"
    assert listing.phone == "+1 214-555-0101"
    assert listing.email == "info@oaklawn.test"
    assert listing.rating == 4.2
    assert listing.review_count == 27
    assert listing.listing_status == "open"
    assert listing.reviews == ["Responsive agent"]
    assert listing.discovery_source == "live"
    assert listing.source_fields == raw


def test_source_fields_preserved_as_raw_object():
    raw = {"title": "Acme", "placeId": "ChIJ-acme", "emails": []}
    listing = map_gosom_listing(raw, "mock")
    assert listing.source_fields == raw
    assert listing.name == "Acme"
    assert listing.place_id == "ChIJ-acme"


def test_discovery_source_from_client_provider_not_payload():
    raw = {
        "title": "Acme",
        "placeId": "ChIJ-acme",
        "emails": [],
        "discovery_source": "live",
    }
    listing = map_gosom_listing(raw, "mock")
    assert listing.discovery_source == "mock"


def test_empty_website_maps_to_none():
    listing = map_gosom_listing({"title": "X", "website": "", "emails": []}, "import")
    assert listing.website is None
    assert listing.discovery_source == "import"


def test_retries_on_502_then_succeeds():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return httpx.Response(502, json={"error": "bad gateway"})
        return httpx.Response(200, json={"job_id": "job-1", "status": "pending"})

    client = ScraperClient(
        base_url="http://scraper.test/scraper",
        token="",
        provider="live",
        transport=httpx.MockTransport(handler),
    )
    job_id = client.create_job("real estate", "Dallas, Texas", 5, {})
    assert job_id == "job-1"
    assert attempts["n"] == 3


def test_retries_on_503_and_429_only_twice():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    client = ScraperClient(
        base_url="http://scraper.test/scraper",
        token="",
        provider="live",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ScraperError):
        client.create_job("real estate", "Dallas, Texas", 5, {})
    assert attempts["n"] == 3


def test_does_not_retry_on_400():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    client = ScraperClient(
        base_url="http://scraper.test/scraper",
        token="",
        provider="live",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ScraperError):
        client.create_job("real estate", "Dallas, Texas", 5, {})
    assert attempts["n"] == 1


def test_live_timeout_is_10s():
    client = ScraperClient(base_url="http://example.com", token="", provider="live")
    assert client.timeout == 10
