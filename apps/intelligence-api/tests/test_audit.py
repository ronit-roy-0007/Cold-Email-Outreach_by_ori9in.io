import uuid
import pytest
from app.models import Business, Campaign
from app.services.audit import audit_business, FetchResult, fixture_fetcher


def test_inaccessible_does_not_invent_missing_form(db):
    camp_id = uuid.uuid4()
    biz = Business(
        identity_key="place:ChIJ-unreach",
        name="Deep Ellum Property Group",
        category="Real estate agency",
        address="2650 Main St, Dallas, TX 75226",
        locality="Dallas",
        website="https://fixtures.intentlead.test/unreachable",
        source_fields={},
        discovery_source="mock",
    )
    db.add(biz)
    db.flush()

    ev = audit_business(db, camp_id, biz, fetcher=fixture_fetcher)
    assert any("unreachable" in e.claim.lower() or (e.caveat and "unreachable" in e.caveat.lower()) for e in ev)
    assert not any("no inquiry" in e.claim.lower() for e in ev)
    assert not any("no property search" in e.claim.lower() for e in ev)


def test_ssrf_localhost_not_fetched(db):
    camp_id = uuid.uuid4()
    biz = Business(
        identity_key="place:ChIJ-local",
        name="Localhost Realty",
        category="Real estate agency",
        address="127 Main St",
        locality="Dallas",
        website="http://127.0.0.1/",
        source_fields={},
        discovery_source="mock",
    )
    db.add(biz)
    db.flush()

    ev = audit_business(db, camp_id, biz, fetcher=fixture_fetcher)
    assert any("ssrf" in (e.claim + (e.caveat or "")).lower() or "blocked" in e.claim.lower() for e in ev)
    assert not any("no inquiry" in e.claim.lower() for e in ev)


def test_robots_disallow(db):
    camp_id = uuid.uuid4()
    biz = Business(
        identity_key="place:ChIJ-robots",
        name="Robots Realty",
        category="Real estate agency",
        address="100 Secret St",
        locality="Dallas",
        website="https://example.com/hidden/page",
        source_fields={},
        discovery_source="mock",
    )
    db.add(biz)
    db.flush()

    def fetcher_disallow(url: str) -> FetchResult:
        if "robots.txt" in url:
            return FetchResult(status=200, body_bytes=b"User-agent: *\nDisallow: /hidden\n")
        return FetchResult(status=200, body_bytes=b"<html><body><h1>Page</h1></body></html>")

    ev = audit_business(db, camp_id, biz, fetcher=fetcher_disallow)
    assert any("robots" in e.claim.lower() for e in ev)
    assert not any("no inquiry" in e.claim.lower() for e in ev)


def test_page_cap(db):
    camp_id = uuid.uuid4()
    biz = Business(
        identity_key="place:ChIJ-many",
        name="Many Pages Realty",
        category="Real estate agency",
        address="100 Main St",
        locality="Dallas",
        website="https://fixtures.intentlead.test/brochure",
        source_fields={},
        discovery_source="mock",
    )
    db.add(biz)
    db.flush()

    class CountingFetcher:
        def __init__(self):
            self.calls = 0

        def __call__(self, url: str) -> FetchResult:
            self.calls += 1
            if "robots.txt" in url:
                return FetchResult(status=200, body_bytes=b"User-agent: *\nDisallow:\n")
            links = "".join(f'<a href="https://fixtures.intentlead.test/page{i}">Link {i}</a>' for i in range(10))
            html = f"<html><body>{links}</body></html>".encode("utf-8")
            return FetchResult(status=200, body_bytes=html, headers={"content-type": "text/html"})

    counting_fetcher = CountingFetcher()
    ev = audit_business(db, camp_id, biz, fetcher=counting_fetcher)
    assert counting_fetcher.calls <= 6  # robots.txt + at most 5 pages


def test_explicit_intent_only_from_html(db):
    camp_id = uuid.uuid4()
    biz = Business(
        identity_key="place:ChIJ-intent",
        name="Design District Properties",
        category="Real estate agency",
        address="161 Glass St",
        locality="Dallas",
        website="https://fixtures.intentlead.test/explicit_intent",
        source_fields={},
        discovery_source="mock",
    )
    db.add(biz)
    db.flush()

    ev = audit_business(db, camp_id, biz, fetcher=fixture_fetcher)
    assert any(e.evidence_type == "explicit_intent" for e in ev)
