from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import OutboundMessage, SuppressionEntry
from app.services.email_compliance import verify_unsubscribe_token
from app.services.email_dispatcher import dispatch_approved_campaign_leads
from app.services.email_gate import add_to_suppression_list, is_suppressed

router = APIRouter(prefix="/api/outreach", tags=["outreach"])


class DispatchRequest(BaseModel):
    campaign_id: uuid.UUID
    lead_ids: list[uuid.UUID] | None = None
    agency_name: str | None = None
    sender_name: str | None = None


class SuppressionCreateRequest(BaseModel):
    email: str
    reason: str = "manual"


@router.post("/dispatch")
def dispatch_endpoint(
    req: DispatchRequest,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return dispatch_approved_campaign_leads(
        db=db,
        campaign_id=req.campaign_id,
        settings=settings,
        lead_ids=req.lead_ids,
        agency_name=req.agency_name,
        sender_name=req.sender_name,
    )


@router.get("/stats")
def outreach_stats_endpoint(
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    counts = (
        db.query(OutboundMessage.status, func.count(OutboundMessage.id))
        .group_by(OutboundMessage.status)
        .all()
    )
    suppressed_count = db.query(SuppressionEntry).count()

    stats_dict = {s: cnt for s, cnt in counts}
    return {
        "status_breakdown": stats_dict,
        "total_dispatches": sum(stats_dict.values()),
        "total_suppressed": suppressed_count,
    }


@router.get("/suppression")
def list_suppression_endpoint(
    db: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    entries = db.query(SuppressionEntry).order_by(SuppressionEntry.created_at.desc()).limit(100).all()
    return [
        {
            "id": str(e.id),
            "email": e.email,
            "reason": e.reason,
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]


@router.post("/suppression")
def add_suppression_endpoint(
    req: SuppressionCreateRequest,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    entry = add_to_suppression_list(db, req.email, reason=req.reason)
    db.commit()
    return {"status": "success", "email": entry.email, "reason": entry.reason}


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_endpoint(
    email: str = Query(...),
    token: str = Query(...),
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> str:
    if not verify_unsubscribe_token(email, token, settings.UNSUBSCRIBE_SECRET):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired unsubscribe signature token.",
        )

    add_to_suppression_list(db, email, reason="one_click_unsubscribe")
    db.commit()

    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Unsubscribed</title></head>
    <body style="font-family: sans-serif; text-align: center; padding: 50px;">
        <h2>Unsubscribed Successfully</h2>
        <p>The email address <strong>{email}</strong> has been suppressed from all future communications.</p>
    </body>
    </html>
    """


class EmailEventWebhookRequest(BaseModel):
    email: str
    event: str = "complaint"  # complaint, bounce
    details: str | None = None


@router.post("/webhook/event")
def email_event_webhook_endpoint(
    req: EmailEventWebhookRequest,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    reason = "complaint" if req.event.lower() in ("complaint", "spam_report") else "hard_bounce"
    entry = add_to_suppression_list(db, req.email, reason=reason)
    db.commit()
    return {"status": "success", "email": entry.email, "suppression_reason": entry.reason}
