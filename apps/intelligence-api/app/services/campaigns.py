from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Campaign, ScrapeJob
from app.services.parser import parse_campaign, ParseError


def create_campaign(session: Session, payload: dict[str, Any], settings: Settings) -> Campaign:
    parsed = parse_campaign(payload)
    if isinstance(parsed, ParseError):
        raise ValueError(f"Campaign validation failed: {', '.join(parsed.fields)}")

    provider = payload.get("provider") or settings.DISCOVERY_PROVIDER

    campaign = Campaign(
        niche=parsed.niche,
        location=parsed.location,
        requested_quantity=parsed.requested_quantity,
        target_services=parsed.target_services,
        filters=parsed.filters,
        provider=provider,
        dry_run=payload.get("dry_run", settings.OUTREACH_DRY_RUN if settings else False),
        status="pending",
    )
    session.add(campaign)
    session.flush()

    scrape_job = ScrapeJob(
        campaign_id=campaign.id,
        provider=provider,
        external_job_id="",
        status="pending",
    )
    session.add(scrape_job)
    session.flush()

    return campaign


def list_campaigns(session: Session) -> list[Campaign]:
    return session.query(Campaign).order_by(Campaign.created_at.desc()).all()


def get_campaign(session: Session, campaign_id: uuid.UUID) -> Campaign | None:
    return session.get(Campaign, campaign_id)
