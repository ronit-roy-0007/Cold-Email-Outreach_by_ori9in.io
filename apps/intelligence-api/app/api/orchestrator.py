from __future__ import annotations

import hmac
import logging
from typing import Any
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import Business, Evidence, Lead, MessageDraft
from app.security import ApprovalActionSchema, check_rate_limit, verify_api_key
from app.services.campaigns import create_campaign
from app.services.pipeline import run_campaign
from app.services.telegram_bot import format_approval_card, handle_telegram_update, record_approval

logger = logging.getLogger("intentlead.api.orchestrator")

router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


@router.post("/webhooks/telegram", dependencies=[Depends(check_rate_limit)])
def telegram_webhook_endpoint(
    update: dict[str, Any],
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    secret_token: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> dict[str, Any]:
    # Production fail-closed: missing TELEGRAM_WEBHOOK_SECRET must reject webhook requests
    if settings.APP_ENV == "production":
        if not settings.TELEGRAM_WEBHOOK_SECRET or not settings.TELEGRAM_WEBHOOK_SECRET.strip():
            logger.critical("TELEGRAM_WEBHOOK_SECRET is not configured in production. Rejecting unsigned webhook.")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Telegram webhook secret is not configured in production. Unsigned webhook requests are rejected.",
            )

    if settings.TELEGRAM_WEBHOOK_SECRET and settings.TELEGRAM_WEBHOOK_SECRET.strip():
        if not secret_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing Telegram secret token header ('X-Telegram-Bot-Api-Secret-Token').",
            )
        if not hmac.compare_digest(secret_token.strip(), settings.TELEGRAM_WEBHOOK_SECRET.strip()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Telegram webhook secret token.",
            )

    res = handle_telegram_update(update, db, settings)
    if res.get("status") == "unauthorized":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=res["message"])
    return res


@router.post("/approvals/{lead_id}", dependencies=[Depends(check_rate_limit)])
def process_approval_endpoint(
    lead_id: uuid.UUID,
    payload: ApprovalActionSchema,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: str = Depends(verify_api_key),
) -> dict[str, Any]:
    user_id = str(payload.user_id or "api_operator")
    action = str(payload.action or "approve")

    if settings.TELEGRAM_ALLOWED_USER_ID and user_id != "api_operator":
        if user_id != str(settings.TELEGRAM_ALLOWED_USER_ID):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized operator")

    res = record_approval(db, lead_id, user_id, action)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@router.get("/pending-approvals", dependencies=[Depends(check_rate_limit)])
def list_pending_approvals(
    campaign_id: uuid.UUID | None = None,
    limit: int = 20,
    db: Session = Depends(get_session),
    _: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    query = (
        db.query(Lead, Business, MessageDraft)
        .join(Business, Lead.business_id == Business.id)
        .outerjoin(MessageDraft, Lead.id == MessageDraft.lead_id)
        .filter(Lead.outreach_status == "draft")
    )
    if campaign_id:
        query = query.filter(Lead.campaign_id == campaign_id)

    results = query.order_by(Lead.overall_score.desc()).limit(limit).all()

    items = []
    for lead, biz, draft in results:
        evs = db.query(Evidence).filter_by(business_id=biz.id, campaign_id=lead.campaign_id).all()
        card_text, buttons = format_approval_card(lead, biz, draft, evs)
        items.append({
            "lead_id": str(lead.id),
            "campaign_id": str(lead.campaign_id),
            "business_name": biz.name,
            "overall_score": lead.overall_score,
            "priority": lead.priority,
            "recommended_service": lead.recommended_service,
            "card_markdown": card_text,
            "inline_keyboard": buttons,
        })
    return items


@router.post("/campaign-run", dependencies=[Depends(check_rate_limit)])
def trigger_orchestrated_campaign(
    payload: dict[str, Any],
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: str = Depends(verify_api_key),
) -> dict[str, Any]:
    try:
        camp = create_campaign(db, payload, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    camp = run_campaign(db, camp.id, settings)
    leads_count = db.query(Lead).filter_by(campaign_id=camp.id).count()

    return {
        "campaign_id": str(camp.id),
        "status": camp.status,
        "niche": camp.niche,
        "location": camp.location,
        "leads_scored": leads_count,
    }
