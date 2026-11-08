from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid

from sqlalchemy.orm import Session

from app.models import Business, Lead
from app.providers.types import NormalizedListing

_WS_RE = re.compile(r"\s+")


def normalize_identity_part(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.lower()
    value = "".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in value)
    value = _WS_RE.sub(" ", value)
    return value.strip()


def identity_key(
    *,
    place_id: str | None,
    name: str,
    address: str,
    locality: str,
) -> str:
    stripped = place_id.strip() if place_id is not None else ""
    if stripped:
        return "place:" + stripped
    payload = "|".join(
        (
            normalize_identity_part(name),
            normalize_identity_part(address),
            normalize_identity_part(locality),
        )
    )
    return "nameaddr:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upsert_business(
    session: Session,
    listing: NormalizedListing,
    scrape_job_id: uuid.UUID | None,
) -> Business:
    key = identity_key(
        place_id=listing.place_id,
        name=listing.name,
        address=listing.address or "",
        locality=listing.locality or "",
    )
    business = session.query(Business).filter_by(identity_key=key).one_or_none()
    if business is None:
        business = Business(identity_key=key, source_fields={}, discovery_source=listing.discovery_source)
        session.add(business)
    business.place_id = listing.place_id
    business.name = listing.name
    business.category = listing.category
    business.address = listing.address
    business.locality = listing.locality
    business.website = listing.website
    business.phone = listing.phone
    business.email = listing.email
    business.rating = listing.rating
    business.review_count = listing.review_count
    business.listing_status = listing.listing_status
    business.source_fields = listing.source_fields
    business.discovery_source = listing.discovery_source
    business.scrape_job_id = scrape_job_id
    session.flush()
    return business


def get_or_create_lead(
    session: Session,
    campaign_id: uuid.UUID,
    business_id: uuid.UUID,
) -> Lead:
    lead = (
        session.query(Lead)
        .filter_by(campaign_id=campaign_id, business_id=business_id)
        .one_or_none()
    )
    if lead is None:
        lead = Lead(
            campaign_id=campaign_id,
            business_id=business_id,
            overall_score=0,
            priority="D",
            confidence="low",
            outreach_status="draft",
            crm_stage="discovered",
        )
        session.add(lead)
        session.flush()
    return lead
