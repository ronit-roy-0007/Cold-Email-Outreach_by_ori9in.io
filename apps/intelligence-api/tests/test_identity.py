from app.identity import identity_key, normalize_identity_part


def test_place_id_preferred():
    a = identity_key(place_id="ChIJabc", name="Acme", address="1 Main", locality="Dallas")
    b = identity_key(place_id="ChIJabc", name="ACME REALTY", address="other", locality="Austin")
    assert a == b == "place:ChIJabc"


def test_nameaddr_hash_is_stable_under_punctuation_and_case():
    a = identity_key(place_id=None, name="Acme Realty!", address="100 Main St.", locality="Dallas, TX")
    b = identity_key(place_id=None, name="acme realty", address="100 main st", locality="dallas tx")
    assert a == b
    assert a.startswith("nameaddr:")


def test_website_not_in_key():
    a = identity_key(place_id=None, name="Acme", address="1 Main", locality="Dallas")
    b = identity_key(place_id=None, name="Acme", address="1 Main", locality="Dallas")
    assert a == b


def test_duplicate_place_id_one_business_one_lead_per_campaign(db):
    from app.identity import upsert_business, get_or_create_lead
    from app.models import Campaign, Lead, Business
    from app.providers.types import NormalizedListing
    campaign = Campaign(niche="Real Estate Agencies", location="Dallas, Texas", requested_quantity=10, target_services=["website_redesign"], filters={}, provider="mock", dry_run=True, status="running")
    db.add(campaign)
    db.flush()
    listing = NormalizedListing(place_id="ChIJ1", name="Acme", category="Real estate agency", address="1 Main", locality="Dallas", website=None, phone=None, email=None, rating=4.1, review_count=10, listing_status="open", source_fields={}, discovery_source="mock")
    b1 = upsert_business(db, listing, scrape_job_id=None)
    listing2 = listing.model_copy(update={"website": "https://example.com"})
    b2 = upsert_business(db, listing2, scrape_job_id=None)
    assert b1.id == b2.id
    l1 = get_or_create_lead(db, campaign.id, b1.id)
    l2 = get_or_create_lead(db, campaign.id, b1.id)
    assert l1.id == l2.id
    assert db.query(Lead).filter_by(campaign_id=campaign.id).count() == 1
    assert db.query(Business).count() == 1
