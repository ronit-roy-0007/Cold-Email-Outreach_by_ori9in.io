from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.config import Settings
from app.identity import get_or_create_lead, upsert_business
from app.models import (
    AuditLog,
    Business,
    Campaign,
    DimensionScore,
    Lead,
    MessageDraft,
    ScrapeJob,
    ServiceScore,
)
from app.providers.scraper_client import ScraperClient, ScraperError
from app.providers.types import NormalizedListing
from app.scoring.engine import score_lead
from app.services.audit import audit_business
from app.services.drafts import build_draft


def process_listings(
    session: Session,
    campaign: Campaign,
    scrape_job: ScrapeJob,
    listings: list[NormalizedListing],
    settings: Settings,
    *,
    fetcher: Any = None,
) -> None:
    for listing in listings:
        listing.discovery_source = campaign.provider
        biz = upsert_business(session, listing, scrape_job_id=scrape_job.id)
        lead = get_or_create_lead(session, campaign.id, biz.id)

        evidence_list = audit_business(session, campaign.id, biz, fetcher=fetcher)
        score_res = score_lead(biz, evidence_list, target_services=campaign.target_services)

        lead.overall_score = score_res.overall_score
        lead.priority = score_res.priority
        lead.confidence = score_res.confidence
        lead.recommended_service = score_res.recommended_service
        lead.outreach_status = "draft"
        lead.crm_stage = "qualified" if score_res.overall_score >= 45 else "discovered"
        session.flush()

        for d in score_res.dimensions:
            session.add(
                DimensionScore(
                    lead_id=lead.id,
                    dimension=d.dimension,
                    points=d.points,
                    max_points=d.max_points,
                    evidence_ids=d.evidence_ids,
                    reason_code=d.reason_code,
                )
            )

        for s in score_res.service_scores:
            session.add(
                ServiceScore(
                    lead_id=lead.id,
                    service=s.service,
                    points=s.points,
                    evidence_ids=s.evidence_ids,
                    reason_code=s.reason_code,
                )
            )

        draft_res = build_draft(
            agency_name=settings.AGENCY_NAME,
            sender_name=settings.AGENCY_SENDER_NAME,
            business_name=biz.name,
            recommended_service=score_res.recommended_service,
            evidence=evidence_list,
            service_scores=score_res.service_scores,
        )

        session.add(
            MessageDraft(
                lead_id=lead.id,
                channel="preview",
                status=draft_res.status,
                body=draft_res.body,
                not_recommended_reason=draft_res.reason,
                evidence_ids=draft_res.evidence_ids,
            )
        )
        session.flush()

    audit_entry = AuditLog(
        action="campaign_run_completed",
        entity_type="campaign",
        entity_id=campaign.id,
        payload={"leads_count": len(listings)},
    )
    session.add(audit_entry)
    session.flush()


def run_campaign(
    session: Session,
    campaign_id: uuid.UUID,
    settings: Settings,
    *,
    scraper: ScraperClient | None = None,
    fetcher: Any = None,
) -> Campaign:
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError(f"Campaign {campaign_id} not found")

    scrape_job = session.query(ScrapeJob).filter_by(campaign_id=campaign_id).one()

    if campaign.provider == "import":
        scrape_job.status = "awaiting_import"
        campaign.status = "awaiting_import"
        session.flush()
        return campaign

    if scraper is None:
        scraper = ScraperClient(
            base_url=settings.GOOGLE_MAPS_SCRAPER_BASE_URL,
            token=settings.GOOGLE_MAPS_SCRAPER_API_TOKEN,
            provider=campaign.provider,
        )

    try:
        scrape_job.status = "running"
        campaign.status = "running"
        scrape_job.started_at = datetime.now(timezone.utc)
        session.flush()

        external_job_id = scraper.create_job(
            campaign.niche,
            campaign.location,
            campaign.requested_quantity,
            campaign.filters,
        )
        scrape_job.external_job_id = external_job_id
        session.flush()

        job_res = scraper.get_job(external_job_id)
        if job_res.status == "failed" or job_res.error:
            raise ScraperError(job_res.error or "Scraper job failed")

        scrape_job.status = "completed"
        scrape_job.finished_at = datetime.now(timezone.utc)
        scrape_job.raw_snapshot = job_res.raw_snapshot
        session.flush()

        process_listings(
            session=session,
            campaign=campaign,
            scrape_job=scrape_job,
            listings=job_res.results,
            settings=settings,
            fetcher=fetcher,
        )

        campaign.status = "completed"
        session.flush()

    except Exception as exc:
        scrape_job.status = "failed"
        scrape_job.error = str(exc)
        campaign.status = "failed"
        session.flush()

    return campaign
