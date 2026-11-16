from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import OutboundMessage, SuppressionEntry
from app.security import check_rate_limit, verify_api_key
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


@router.post("/dispatch", dependencies=[Depends(check_rate_limit)])
def dispatch_endpoint(
    req: DispatchRequest,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: str = Depends(verify_api_key),
) -> dict[str, Any]:
    return dispatch_approved_campaign_leads(
        db=db,
        campaign_id=req.campaign_id,
        settings=settings,
        lead_ids=req.lead_ids,
        agency_name=req.agency_name,
        sender_name=req.sender_name,
    )


@router.post("/followups/process", dependencies=[Depends(check_rate_limit)])
def process_followups_endpoint(
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """
    Triggers batch execution of all due automated follow-ups.
    Protected by API key and rate-limiting.
    """
    from app.services.followup_engine import process_due_followups
    return process_due_followups(db, settings)


@router.get("/stats", dependencies=[Depends(check_rate_limit)])
def outreach_stats_endpoint(
    db: Session = Depends(get_session),
    _: str = Depends(verify_api_key),
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


@router.get("/suppression", dependencies=[Depends(check_rate_limit)])
def list_suppression_endpoint(
    db: Session = Depends(get_session),
    _: str = Depends(verify_api_key),
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


@router.post("/suppression", dependencies=[Depends(check_rate_limit)])
def add_suppression_endpoint(
    req: SuppressionCreateRequest,
    db: Session = Depends(get_session),
    _: str = Depends(verify_api_key),
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
    id: str | None = None


@router.post("/webhook/event", dependencies=[Depends(check_rate_limit)])
async def email_event_webhook_endpoint(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Malformed JSON body: {exc}")

    email = str(data.get("email") or "").strip()
    event = str(data.get("event") or "complaint").strip()
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required 'email' field in webhook payload")

    # 1. Provider-Specific Cryptographic Signature Verification (Fail-Closed)
    if settings.RESEND_WEBHOOK_SECRET:
        from app.services.webhook_security import verify_resend_svix_signature
        is_valid, err = verify_resend_svix_signature(raw_body, request.headers, settings.RESEND_WEBHOOK_SECRET)
        if not is_valid:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid Resend Svix webhook signature: {err}")
    elif settings.OUTREACH_WEBHOOK_SECRET:
        from app.services.webhook_security import verify_hmac_webhook_signature
        sig = request.headers.get("x-webhook-signature") or request.headers.get("x-signature-sha256")
        ts = request.headers.get("x-webhook-timestamp")
        is_valid, err = verify_hmac_webhook_signature(raw_body, sig or "", settings.OUTREACH_WEBHOOK_SECRET, timestamp=ts)
        if not is_valid:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid webhook HMAC signature: {err}")
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook signature verification required: neither RESEND_WEBHOOK_SECRET nor OUTREACH_WEBHOOK_SECRET is configured.",
        )

    # 2. Distributed Replay Protection & Event Deduplication
    from app.services.webhook_security import webhook_cache
    if settings.REDIS_URL and webhook_cache._redis is None:
        webhook_cache.init_redis(settings.REDIS_URL)

    event_id = data.get("id") or request.headers.get("svix-id") or request.headers.get("x-event-id") or f"{email}:{event}"
    if not webhook_cache.check_and_record(str(event_id)):
        return {
            "status": "duplicate",
            "message": "Webhook event already processed (idempotent ignore)",
            "email": email,
        }

    # 3. Process Suppression
    reason = "complaint" if event.lower() in ("complaint", "spam_report") else "hard_bounce"
    entry = add_to_suppression_list(db, email, reason=reason)
    db.commit()
    return {"status": "success", "email": entry.email, "suppression_reason": entry.reason}
