from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import Campaign, ScrapeJob
from app.providers.import_loader import load_import
from app.services.campaigns import create_campaign, get_campaign, list_campaigns
from app.services.pipeline import process_listings, run_campaign

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_campaign_endpoint(
    payload: dict[str, Any],
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        campaign = create_campaign(db, payload, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if campaign.provider != "import":
        campaign = run_campaign(db, campaign.id, settings)

    return {
        "id": str(campaign.id),
        "niche": campaign.niche,
        "location": campaign.location,
        "requested_quantity": campaign.requested_quantity,
        "target_services": campaign.target_services,
        "provider": campaign.provider,
        "status": campaign.status,
        "dry_run": campaign.dry_run,
        "created_at": campaign.created_at.isoformat(),
    }


@router.get("")
def list_campaigns_endpoint(
    db: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    campaigns = list_campaigns(db)
    return [
        {
            "id": str(c.id),
            "niche": c.niche,
            "location": c.location,
            "requested_quantity": c.requested_quantity,
            "provider": c.provider,
            "status": c.status,
            "created_at": c.created_at.isoformat(),
        }
        for c in campaigns
    ]


@router.get("/{campaign_id}")
def get_campaign_endpoint(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    job = db.query(ScrapeJob).filter_by(campaign_id=campaign_id).first()

    return {
        "id": str(campaign.id),
        "niche": campaign.niche,
        "location": campaign.location,
        "requested_quantity": campaign.requested_quantity,
        "target_services": campaign.target_services,
        "provider": campaign.provider,
        "status": campaign.status,
        "scrape_job": {
            "status": job.status if job else None,
            "error": job.error if job else None,
        }
        if job
        else None,
        "created_at": campaign.created_at.isoformat(),
    }


@router.post("/{campaign_id}/import")
async def import_listings_endpoint(
    campaign_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    content = await file.read()
    import_res = load_import(content, file.filename or "import.csv")
    if not import_res.listings:
        raise HTTPException(
            status_code=400,
            detail=f"Import failed: {', '.join(import_res.row_errors)}",
        )

    scrape_job = db.query(ScrapeJob).filter_by(campaign_id=campaign_id).one()
    scrape_job.status = "completed"
    campaign.status = "running"
    db.flush()

    process_listings(
        session=db,
        campaign=campaign,
        scrape_job=scrape_job,
        listings=import_res.listings,
        settings=settings,
    )
    campaign.status = "completed"
    db.flush()

    return {
        "status": "completed",
        "imported_count": len(import_res.listings),
        "errors": import_res.row_errors,
    }
