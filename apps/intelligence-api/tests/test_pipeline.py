from app.config import Settings
from app.models import Business, Campaign, Lead, ScrapeJob
from app.services.campaigns import create_campaign
from app.services.pipeline import run_campaign


def test_mock_pipeline_labels_source_and_dedupes(db):
    settings = Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        DISCOVERY_PROVIDER="mock",
        AGENCY_NAME="River Agency",
        AGENCY_SENDER_NAME="Sam Lee",
    )
    payload = {
        "niche": "Real Estate Agencies",
        "location": "Dallas, Texas",
        "requested_quantity": 25,
        "target_services": ["website_development", "website_redesign", "real_estate_listing_portal"],
        "filters": {},
    }
    camp = create_campaign(db, payload, settings)
    assert camp.provider == "mock"

    run_campaign(db, camp.id, settings)

    assert camp.status == "completed"
    businesses = db.query(Business).all()
    assert len(businesses) == 8  # 9 fixtures minus 1 duplicate place_id
    assert all(b.discovery_source == "mock" for b in businesses)

    leads = db.query(Lead).filter_by(campaign_id=camp.id).all()
    assert len(leads) == 8
    assert all(l.outreach_status == "draft" for l in leads)

    # Verify duplicate place_id was deduped to 1 business
    oak_biz = db.query(Business).filter_by(place_id="ChIJ-noweb").all()
    assert len(oak_biz) == 1


def test_live_failure_does_not_insert_mock(db):
    settings = Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        DISCOVERY_PROVIDER="live",
        GOOGLE_MAPS_SCRAPER_BASE_URL="http://127.0.0.1:9",
        AGENCY_NAME="River Agency",
        AGENCY_SENDER_NAME="Sam Lee",
    )
    payload = {
        "niche": "Real Estate Agencies",
        "location": "Dallas, Texas",
        "requested_quantity": 5,
        "target_services": ["website_development"],
        "filters": {},
    }
    camp = create_campaign(db, payload, settings)
    assert camp.provider == "live"

    run_campaign(db, camp.id, settings)

    assert camp.status == "failed"
    job = db.query(ScrapeJob).filter_by(campaign_id=camp.id).one()
    assert job.status == "failed"
    assert db.query(Business).count() == 0
    assert db.query(Lead).count() == 0
