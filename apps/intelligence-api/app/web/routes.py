from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import (
    Business,
    Campaign,
    DimensionScore,
    Evidence,
    Lead,
    MessageDraft,
    ScrapeJob,
    ServiceScore,
)
from app.services.campaigns import create_campaign, get_campaign, list_campaigns
from app.services.pipeline import run_campaign

templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

web_router = APIRouter(tags=["web"])


@web_router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_session)):
    campaigns = list_campaigns(db)
    return templates.TemplateResponse(request=request, name="jobs.html", context={"campaigns": campaigns})


@web_router.get("/campaigns/new", response_class=HTMLResponse)
def new_campaign_form(request: Request):
    return templates.TemplateResponse(request=request, name="campaign_new.html", context={})


@web_router.post("/campaigns/new")
def submit_new_campaign(
    request: Request,
    niche: str = Form(...),
    location: str = Form(...),
    requested_quantity: int = Form(...),
    provider: str = Form("mock"),
    target_services: list[str] = Form(...),
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    payload = {
        "niche": niche,
        "location": location,
        "requested_quantity": requested_quantity,
        "provider": provider,
        "target_services": target_services,
        "filters": {},
    }
    camp = create_campaign(db, payload, settings)
    if camp.provider != "import":
        camp = run_campaign(db, camp.id, settings)

    return RedirectResponse(url=f"/campaigns/{camp.id}", status_code=303)


@web_router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
def campaign_leads_view(
    campaign_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_session),
):
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    leads = (
        db.query(Lead, Business)
        .join(Business, Lead.business_id == Business.id)
        .filter(Lead.campaign_id == campaign_id)
        .order_by(Lead.overall_score.desc())
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="leads.html",
        context={"campaign": campaign, "leads": leads},
    )


@web_router.get("/campaigns/{campaign_id}/export.csv")
def export_campaign_csv(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_session),
):
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    leads = (
        db.query(Lead, Business)
        .join(Business, Lead.business_id == Business.id)
        .filter(Lead.campaign_id == campaign_id)
        .order_by(Lead.overall_score.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "name",
        "location",
        "overall_score",
        "priority",
        "confidence",
        "recommended_service",
        "discovery_source",
        "reason_codes",
        "website",
    ])

    for lead, biz in leads:
        dims = db.query(DimensionScore).filter_by(lead_id=lead.id).all()
        reason_codes = "; ".join(f"{d.dimension}:{d.reason_code}" for d in dims)
        writer.writerow([
            biz.name,
            biz.locality or biz.address or "",
            lead.overall_score,
            lead.priority,
            lead.confidence,
            lead.recommended_service or "",
            biz.discovery_source,
            reason_codes,
            biz.website or "",
        ])

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=campaign_{campaign_id}.csv"},
    )


@web_router.get("/leads/{lead_id}", response_class=HTMLResponse)
def lead_detail_view(
    lead_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_session),
):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    biz = db.get(Business, lead.business_id)
    dims = db.query(DimensionScore).filter_by(lead_id=lead_id).all()
    svcs = db.query(ServiceScore).filter_by(lead_id=lead_id).all()
    draft = db.query(MessageDraft).filter_by(lead_id=lead_id).first()
    evs = (
        db.query(Evidence)
        .filter_by(business_id=lead.business_id, campaign_id=lead.campaign_id)
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="lead_detail.html",
        context={
            "lead": lead,
            "business": biz,
            "dimensions": dims,
            "service_scores": svcs,
            "draft": draft,
            "evidence": evs,
        },
    )
