"""
IntentLead AI — Inbound Email Endpoints
Handles inbound webhook ingestion and simulation for prospect replies.
"""

from __future__ import annotations

import json
import logging
from typing import Any
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.security import check_rate_limit, verify_api_key
from app.services.inbound_service import process_inbound_email

logger = logging.getLogger("intentlead.api.inbound")

router = APIRouter(prefix="/api/inbound", tags=["inbound"])


class InboundSimulateRequest(BaseModel):
    sender_email: str
    recipient_email: str | None = None
    subject: str | None = "Re: Question regarding your online presence"
    body: str
    in_reply_to: str | None = None
    references: str | None = None
    provider_message_id: str | None = None


@router.post("/simulate")
def simulate_inbound_reply(
    req: InboundSimulateRequest,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """
    Simulates receiving an inbound reply from a prospect.
    Used for local testing, QA verification, and staging simulation.
    """
    recipient = req.recipient_email or settings.SENDER_EMAIL or "outreach@intentlead.agency"
    msg_id = req.provider_message_id or f"sim-{uuid.uuid4().hex[:12]}@{req.sender_email.split('@')[-1]}"

    result = process_inbound_email(
        db,
        settings,
        sender_email=req.sender_email,
        recipient_email=recipient,
        subject=req.subject or "Re: Outreach",
        raw_body=req.body,
        provider_message_id=msg_id,
        in_reply_to=req.in_reply_to,
        references=req.references,
        provider="simulation",
    )
    return result


@router.post("/webhook")
async def inbound_email_webhook(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """
    Webhook endpoint to ingest inbound prospect emails from external mail services
    (SendGrid Inbound Parse, Resend, Mailgun, Postmark, or generic JSON webhooks).
    """
    content_type = request.headers.get("content-type", "")
    sender_email = ""
    recipient_email = settings.SENDER_EMAIL or "outreach@intentlead.agency"
    subject = "Re: Outreach"
    body = ""
    in_reply_to = None
    references = None
    provider_message_id = None

    if "application/json" in content_type:
        raw_body = await request.body()
        try:
            data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON payload: {exc}",
            )

        # Optional signature verification if configured and signature header present
        if settings.OUTREACH_WEBHOOK_SECRET and (
            "x-webhook-signature" in request.headers or "x-signature-sha256" in request.headers
        ):
            from app.services.webhook_security import verify_hmac_webhook_signature
            sig = request.headers.get("x-webhook-signature") or request.headers.get("x-signature-sha256")
            ts = request.headers.get("x-webhook-timestamp")
            is_valid, err = verify_hmac_webhook_signature(
                raw_body, sig or "", settings.OUTREACH_WEBHOOK_SECRET, timestamp=ts
            )
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid webhook HMAC signature: {err}",
                )

        sender_email = data.get("from") or data.get("sender") or data.get("sender_email") or ""
        recipient_email = data.get("to") or data.get("recipient") or recipient_email
        subject = data.get("subject") or subject
        body = data.get("text") or data.get("body") or data.get("html") or ""
        in_reply_to = data.get("in_reply_to") or data.get("in-reply-to")
        references = data.get("references")
        provider_message_id = data.get("message_id") or data.get("id") or data.get("provider_message_id")

    elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        sender_email = str(form.get("from") or form.get("sender") or "")
        recipient_email = str(form.get("to") or form.get("recipient") or recipient_email)
        subject = str(form.get("subject") or subject)
        body = str(form.get("text") or form.get("body") or form.get("html") or "")
        in_reply_to = str(form.get("in-reply-to") or "") or None
        references = str(form.get("references") or "") or None
        provider_message_id = str(form.get("message-id") or "") or None

    if not sender_email or not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required 'sender' or 'body' in webhook payload",
        )

    # Clean sender address in case of "Name <email@domain>" format
    if "<" in sender_email and ">" in sender_email:
        sender_email = sender_email.split("<")[1].split(">")[0].strip()

    result = process_inbound_email(
        db,
        settings,
        sender_email=sender_email,
        recipient_email=recipient_email,
        subject=subject,
        raw_body=body,
        provider_message_id=provider_message_id,
        in_reply_to=in_reply_to,
        references=references,
        provider="webhook",
    )
    return result
