from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Business, DimensionScore, Evidence, Lead, MessageDraft, ServiceScore
from app.security import check_rate_limit, verify_api_key

router = APIRouter(prefix="/api/leads", tags=["leads"])


@router.get("", dependencies=[Depends(check_rate_limit)])
def list_leads_endpoint(
    campaign_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_session),
    _: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    query = db.query(Lead, Business).join(Business, Lead.business_id == Business.id)
    if campaign_id:
        query = query.filter(Lead.campaign_id == campaign_id)

    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)
    rows = query.order_by(Lead.overall_score.desc()).offset(safe_offset).limit(safe_limit).all()

    return [
        {
            "id": str(lead.id),
            "campaign_id": str(lead.campaign_id),
            "business_id": str(lead.business_id),
            "name": biz.name,
            "category": biz.category,
            "locality": biz.locality,
            "website": biz.website,
            "phone": biz.phone,
            "email": biz.email,
            "overall_score": lead.overall_score,
            "priority": lead.priority,
            "confidence": lead.confidence,
            "recommended_service": lead.recommended_service,
            "outreach_status": lead.outreach_status,
            "crm_stage": lead.crm_stage,
            "discovery_source": biz.discovery_source,
        }
        for lead, biz in rows
    ]


@router.get("/{lead_id}", dependencies=[Depends(check_rate_limit)])
def get_lead_endpoint(
    lead_id: uuid.UUID,
    db: Session = Depends(get_session),
    _: str = Depends(verify_api_key),
) -> dict[str, Any]:
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    biz = db.get(Business, lead.business_id)
    dims = db.query(DimensionScore).filter_by(lead_id=lead_id).all()
    svcs = db.query(ServiceScore).filter_by(lead_id=lead_id).all()
    draft = db.query(MessageDraft).filter_by(lead_id=lead_id).first()
    evs = db.query(Evidence).filter_by(business_id=lead.business_id, campaign_id=lead.campaign_id).all()

    return {
        "id": str(lead.id),
        "campaign_id": str(lead.campaign_id),
        "business": {
            "id": str(biz.id) if biz else None,
            "name": biz.name if biz else "",
            "category": biz.category if biz else "",
            "address": biz.address if biz else "",
            "locality": biz.locality if biz else "",
            "website": biz.website if biz else "",
            "phone": biz.phone if biz else "",
            "email": biz.email if biz else "",
            "discovery_source": biz.discovery_source if biz else "",
        },
        "overall_score": lead.overall_score,
        "priority": lead.priority,
        "confidence": lead.confidence,
        "recommended_service": lead.recommended_service,
        "outreach_status": lead.outreach_status,
        "crm_stage": lead.crm_stage,
        "dimension_scores": [
            {
                "dimension": d.dimension,
                "points": d.points,
                "max_points": d.max_points,
                "reason_code": d.reason_code,
                "evidence_ids": d.evidence_ids,
            }
            for d in dims
        ],
        "service_scores": [
            {
                "service": s.service,
                "points": s.points,
                "reason_code": s.reason_code,
                "evidence_ids": s.evidence_ids,
            }
            for s in svcs
        ],
        "draft": {
            "status": draft.status if draft else None,
            "channel": draft.channel if draft else None,
            "body": draft.body if draft else None,
            "not_recommended_reason": draft.not_recommended_reason if draft else None,
            "evidence_ids": draft.evidence_ids if draft else [],
        }
        if draft
        else None,
        "evidence": [
            {
                "id": str(e.id),
                "claim": e.claim,
                "evidence_type": e.evidence_type,
                "source_url": e.source_url,
                "inspected_scope": e.inspected_scope,
                "confidence": e.confidence,
                "supporting_excerpt": e.supporting_excerpt,
                "caveat": e.caveat,
            }
            for e in evs
        ],
    }
