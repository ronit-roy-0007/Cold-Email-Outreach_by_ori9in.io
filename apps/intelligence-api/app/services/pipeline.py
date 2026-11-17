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
from app.services.geo_expansion import get_next_expansion_location
from app.services.sub_campaign_service import is_business_duplicate


def process_listings(
    session: Session,
    campaign: Campaign,
    scrape_job: ScrapeJob,
    listings: list[NormalizedListing],
    settings: Settings,
    *,
    fetcher: Any = None,
    agency_name: str | None = None,
    sender_name: str | None = None,
) -> int:
    added_count = 0
    candidates: list[tuple[Business, Lead]] = []
    for listing in listings:
        if is_business_duplicate(
            session,
            campaign.id,
            place_id=listing.place_id,
            website=listing.website,
            email=listing.email,
        ):
            continue

        listing.discovery_source = "google_maps" if campaign.provider in ("live", "google_maps") else campaign.provider
        biz = upsert_business(session, listing, scrape_job_id=scrape_job.id)
        lead = get_or_create_lead(session, campaign.id, biz.id)
        added_count += 1
        candidates.append((biz, lead))

    if not candidates:
        return 0

    session.flush()

    # Parallelize website audits across a thread pool (6 workers)
    def _audit_task(pair: tuple[Business, Lead]) -> tuple[Business, Lead, list[Evidence]]:
        b, l = pair
        evs = audit_business(None, campaign.id, b, fetcher=fetcher)
        return b, l, evs

    if len(candidates) > 1 and (fetcher is None or campaign.provider in ("live", "google_maps", "scrapling")):
        from concurrent.futures import ThreadPoolExecutor
        workers = min(len(candidates), 16)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            audited_items = list(pool.map(_audit_task, candidates))
    else:
        audited_items = [(b, l, audit_business(None, campaign.id, b, fetcher=fetcher)) for b, l in candidates]

    for biz, lead, evidence_list in audited_items:
        for ev in evidence_list:
            session.add(ev)
        session.flush()

        score_res = score_lead(biz, evidence_list, target_services=campaign.target_services)

        lead.overall_score = score_res.overall_score
        lead.priority = score_res.priority
        lead.confidence = score_res.confidence
        lead.recommended_service = score_res.recommended_service
        lead.outreach_status = "draft"
        lead.crm_stage = "qualified" if score_res.overall_score >= 45 else "discovered"
        session.flush()

        session.query(DimensionScore).filter_by(lead_id=lead.id).delete()
        session.query(ServiceScore).filter_by(lead_id=lead.id).delete()
        session.query(MessageDraft).filter_by(lead_id=lead.id).delete()

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

        services_desc = campaign.filters.get("services_desc") if isinstance(campaign.filters, dict) else None
        use_best_template = campaign.filters.get("use_best_response_template", False) if isinstance(campaign.filters, dict) else False

        if use_best_template:
            raw_name = (biz.name or "").strip()
            target_name = raw_name
            for sep in (" - ", " | ", " — ", " – ", " : "):
                if sep in target_name:
                    target_name = target_name.split(sep)[0].strip()
            target_name = target_name or "there"
            template_body = (
                f"Hey {target_name}, tried to reach you a few times but didn't hear back . . .\n\n\n"
                f"Where should we go from here?"
            )
            session.add(
                MessageDraft(
                    lead_id=lead.id,
                    channel="preview",
                    status="preview",
                    body=template_body,
                    not_recommended_reason=None,
                    evidence_ids=[],
                )
            )
        else:
            draft_res = build_draft(
                agency_name=agency_name or settings.AGENCY_NAME,
                sender_name=sender_name or settings.AGENCY_SENDER_NAME,
                business_name=biz.name,
                recommended_service=score_res.recommended_service,
                evidence=evidence_list,
                service_scores=score_res.service_scores,
                rating=biz.rating,
                review_count=biz.review_count,
                services_desc=services_desc,
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
        payload={"leads_count": len(listings), "added_count": added_count},
    )
    session.add(audit_entry)
    session.flush()
    return added_count


def run_campaign(
    session: Session,
    campaign_id: uuid.UUID,
    settings: Settings,
    *,
    scraper: ScraperClient | None = None,
    fetcher: Any = None,
    agency_name: str | None = None,
    sender_name: str | None = None,
    location_override: str | None = None,
    target_count: int | None = None,
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
        eff_provider = campaign.provider or settings.DISCOVERY_PROVIDER
        if settings.DISCOVERY_PROVIDER == "scrapling" and eff_provider in ("mock", None):
            eff_provider = "scrapling"
        if eff_provider == "scrapling":
            from app.providers.scrapling_client import ScraplingClient
            scraper = ScraplingClient()
        else:
            scraper = ScraperClient(
                base_url=settings.GOOGLE_MAPS_SCRAPER_BASE_URL,
                token=settings.GOOGLE_MAPS_SCRAPER_API_TOKEN,
                provider=eff_provider,
            )

    try:
        scrape_job.status = "running"
        campaign.status = "running"
        scrape_job.started_at = datetime.now(timezone.utc)
        session.flush()

        min_score = campaign.filters.get("min_score", 0) if isinstance(campaign.filters, dict) else 0
        target_qualified = target_count or campaign.requested_quantity
        attempt = 0
        max_attempts = 5 if min_score > 0 else 1

        search_location = location_override or campaign.location

        while attempt < max_attempts:
            attempt += 1
            depth = max(5, min(10 + (attempt - 1) * 5, 25))
            current_filters = dict(campaign.filters or {})
            current_filters["depth"] = depth
            current_filters["attempt"] = attempt

            batch_limit = max(target_qualified * 3, 60) if min_score > 0 else max(target_qualified, 25)

            # In large metros, explore directional sectors on subsequent attempts to discover fresh businesses
            if attempt == 1:
                attempt_loc = search_location
            else:
                prefixes = ["Central", "North", "South", "East", "West"]
                clean_loc = search_location
                for p in prefixes:
                    if clean_loc.lower().startswith(p.lower() + " "):
                        clean_loc = clean_loc[len(p) + 1:].strip()
                prefix = prefixes[(attempt - 2) % len(prefixes)]
                attempt_loc = f"{prefix} {clean_loc}"

            external_job_id = scraper.create_job(
                campaign.niche,
                attempt_loc,
                limit=batch_limit,
                filters=current_filters,
            )
            scrape_job.external_job_id = external_job_id
            session.flush()

            job_res = scraper.get_job(external_job_id)
            if campaign.provider == "live" and job_res.status == "pending":
                import time
                for _ in range(45):  # poll up to 90 seconds
                    time.sleep(2)
                    job_res = scraper.get_job(external_job_id)
                    if job_res.status != "pending":
                        break

            if job_res.status == "failed" or job_res.error:
                if attempt == 1:
                    raise ScraperError(job_res.error or "Scraper job failed")
                break

            scrape_job.status = "completed"
            scrape_job.finished_at = datetime.now(timezone.utc)
            scrape_job.raw_snapshot = job_res.raw_snapshot
            session.flush()

            added = process_listings(
                session=session,
                campaign=campaign,
                scrape_job=scrape_job,
                listings=job_res.results,
                settings=settings,
                fetcher=fetcher,
                agency_name=agency_name,
                sender_name=sender_name,
            )

            # If no new businesses were added in this attempt, this specific location is exhausted
            if not job_res.results or added == 0:
                campaign.is_exhausted = True
                break

            # Check if we reached target unattempted qualified count
            if min_score > 0:
                unattempted_count = (
                    session.query(Lead)
                    .filter(
                        Lead.campaign_id == campaign.id,
                        Lead.overall_score >= min_score,
                        Lead.outreach_status.in_(["draft", "approved"]),
                    )
                    .count()
                )
                if unattempted_count >= target_qualified:
                    campaign.is_exhausted = False
                    break
            else:
                campaign.is_exhausted = False
                break

        # If after all scrape attempts, unattempted qualified count is still less than requested, location is exhausted
        if min_score > 0:
            final_unattempted = (
                session.query(Lead)
                .filter(
                    Lead.campaign_id == campaign.id,
                    Lead.overall_score >= min_score,
                    Lead.outreach_status.in_(["draft", "approved"]),
                )
                .count()
            )
            if final_unattempted < target_qualified:
                campaign.is_exhausted = True

        if campaign.is_auto_mode and campaign.target_sent_emails and campaign.total_sent_emails < campaign.target_sent_emails:
            campaign.status = "in_progress"
        else:
            campaign.status = "completed"
        session.flush()

    except Exception as exc:
        scrape_job.status = "failed"
        scrape_job.error = str(exc)
        campaign.status = "failed"
        session.flush()

    return campaign
