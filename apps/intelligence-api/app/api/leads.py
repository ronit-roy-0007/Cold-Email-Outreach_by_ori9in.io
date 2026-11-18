from __future__ import annotations

import logging
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import Business, DimensionScore, Evidence, Lead, MessageDraft, ServiceScore, utc_now
from app.security import check_rate_limit, verify_api_key, verify_api_key_or_operator
from app.services.audit import record_audit_log
from app.services.gemini_personalizer import (
    GeminiAPIError,
    GeminiConfigError,
    GeminiRateLimitError,
    generate_gemini_personalized_draft,
)

logger = logging.getLogger("intentlead.leads")

router = APIRouter(prefix="/api/leads", tags=["leads"])


class SaveDraftRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1)
    version: int | None = None


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
            "subject": draft.subject if draft else None,
            "body": draft.body if draft else None,
            "version": draft.version if draft else 1,
            "updated_at": draft.updated_at.isoformat() if (draft and draft.updated_at) else None,
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


@router.post("/{lead_id}/ai-generate", dependencies=[Depends(check_rate_limit)])
@router.post("/{lead_id}/ai-generate/regenerate", dependencies=[Depends(check_rate_limit)])
def generate_ai_draft_endpoint(
    lead_id: uuid.UUID,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    operator: str = Depends(verify_api_key_or_operator),
) -> dict[str, Any]:
    """
    On-demand AI email draft generation for an individual lead.
    Grounds generation in verified reconnaissance and audit evidence.
    Returns preview subject and body without altering database records or sending email.
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    biz = db.get(Business, lead.business_id)
    if not biz:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated business not found")

    evs = (
        db.query(Evidence)
        .filter_by(business_id=lead.business_id, campaign_id=lead.campaign_id)
        .all()
    )

    try:
        res = generate_gemini_personalized_draft(
            business=biz,
            lead=lead,
            evidence=evs,
            settings=settings,
            agency_name=settings.AGENCY_NAME,
            sender_name=settings.AGENCY_SENDER_NAME,
        )
    except GeminiConfigError as exc:
        logger.warning("Gemini config error for lead %s: %s", lead_id, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gemini API key is not configured. Please configure USER_LLM_API_KEY in settings or .env file.",
        )
    except GeminiRateLimitError as exc:
        logger.warning("Gemini rate limit for lead %s: %s", lead_id, exc)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Gemini API rate limit reached (15 RPM). Please wait a moment and retry.",
        )
    except GeminiAPIError as exc:
        logger.warning("Gemini API error for lead %s: %s", lead_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gemini generation failed: {exc}",
        )
    except Exception as exc:
        logger.error("Unexpected error generating draft for lead %s: %s", lead_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate draft: {exc}",
        )

    return {
        "success": True,
        "lead_id": str(lead.id),
        "draft": {
            "subject": res.subject,
            "body": res.body,
        },
        "generation_id": res.generation_id,
        "model": res.model,
    }


@router.put("/{lead_id}/ai-draft", dependencies=[Depends(check_rate_limit)])
def save_ai_draft_endpoint(
    lead_id: uuid.UUID,
    payload: SaveDraftRequest,
    db: Session = Depends(get_session),
    operator: str = Depends(verify_api_key_or_operator),
) -> dict[str, Any]:
    """
    Persists edited draft subject and body to PostgreSQL against the selected lead.
    Enforces optimistic concurrency versioning to avoid accidental overwrites.
    Does NOT auto-approve or trigger dispatch.
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    subject = payload.subject.strip()
    body = payload.body.strip()
    if not subject or not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Draft subject and body cannot be empty.",
        )

    draft = db.query(MessageDraft).filter_by(lead_id=lead.id).first()
    if draft:
        if payload.version is not None and draft.version != payload.version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Conflict: Draft has been modified. Server version is {draft.version}, submitted version was {payload.version}.",
            )
        draft.subject = subject
        draft.body = body
        draft.version = (draft.version or 0) + 1
        draft.updated_at = utc_now()
    else:
        draft = MessageDraft(
            id=uuid.uuid4(),
            lead_id=lead.id,
            channel="email",
            status="preview",
            subject=subject,
            body=body,
            version=1,
            evidence_ids=[],
            updated_at=utc_now(),
        )
        db.add(draft)

    record_audit_log(
        db=db,
        action="save_ai_draft",
        entity_type="lead",
        entity_id=lead.id,
        actor=operator,
        details={
            "draft_id": str(draft.id),
            "version": draft.version,
            "subject": draft.subject,
        },
    )
    db.commit()
    db.refresh(draft)

    return {
        "success": True,
        "lead_id": str(lead.id),
        "draft": {
            "id": str(draft.id),
            "subject": draft.subject,
            "body": draft.body,
            "version": draft.version,
            "status": draft.status,
            "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
        },
    }


@router.get("/{lead_id}/ai-draft", dependencies=[Depends(check_rate_limit)])
def get_ai_draft_endpoint(
    lead_id: uuid.UUID,
    db: Session = Depends(get_session),
    _: str = Depends(verify_api_key_or_operator),
) -> dict[str, Any]:
    """
    Retrieves the persisted draft subject, body, and version metadata for a lead.
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    draft = db.query(MessageDraft).filter_by(lead_id=lead.id).first()
    return {
        "success": True,
        "lead_id": str(lead.id),
        "has_draft": draft is not None and bool(draft.body or draft.subject),
        "draft": {
            "id": str(draft.id) if draft else None,
            "subject": draft.subject if draft else "",
            "body": draft.body if draft else "",
            "version": draft.version if draft else 1,
            "status": draft.status if draft else None,
            "updated_at": draft.updated_at.isoformat() if (draft and draft.updated_at) else None,
        },
    }

