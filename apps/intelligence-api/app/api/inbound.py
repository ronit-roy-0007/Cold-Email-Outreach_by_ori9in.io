"""
IntentLead AI — Inbound Email Endpoints
Handles inbound webhook ingestion and simulation for prospect replies.
Supports SendGrid Inbound Parse, Resend, Mailgun, Postmark, and generic webhooks
with cryptographic signature verification, replay protection, and fail-closed production security.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.security import check_rate_limit
from app.services.inbound_service import process_inbound_email
from app.services.webhook_security import (
    DistributedReplayUnavailableError,
    verify_hmac_webhook_signature,
    verify_mailgun_webhook_signature,
    verify_resend_svix_signature,
    webhook_cache,
)

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
    Strictly forbidden in production environments.
    """
    if settings.APP_ENV == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Simulation endpoints are strictly disabled in production environments.",
        )

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


@router.post("/webhook", dependencies=[Depends(check_rate_limit)])
async def inbound_email_webhook(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """
    Webhook endpoint to ingest inbound prospect emails from external mail services
    (SendGrid Inbound Parse, Resend, Mailgun, Postmark, or generic JSON webhooks).
    Enforces cryptographic signature verification, replay protection, and RFC 2822 header extraction.
    """
    # 0. Production Security Policy: HTTPS Enforcement & Payload Size Limits
    if settings.APP_ENV == "production":
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme).lower()
        if scheme != "https":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="HTTPS is mandatory for webhook ingestion in production environments.",
            )

    MAX_INBOUND_PAYLOAD_BYTES = 26_214_400  # 25 MB
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_INBOUND_PAYLOAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Inbound payload exceeds maximum size limit ({MAX_INBOUND_PAYLOAD_BYTES} bytes).",
                )
        except ValueError:
            pass

    content_type = request.headers.get("content-type", "")
    raw_body = await request.body()

    sender_email = ""
    recipient_email = settings.SENDER_EMAIL or "outreach@intentlead.agency"
    subject = "Re: Outreach"
    body = ""
    in_reply_to = None
    references = None
    provider_message_id = None
    headers_raw = ""
    event_id = None

    mailgun_token = None
    mailgun_timestamp = None
    mailgun_signature = None

    # 1. Provider-Specific Payload Parsing
    if "application/json" in content_type:
        try:
            data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON payload: {exc}",
            )

        # Mailgun JSON webhook format
        if "signature" in data and isinstance(data["signature"], dict):
            mg_sig = data["signature"]
            mailgun_token = mg_sig.get("token")
            mailgun_timestamp = str(mg_sig.get("timestamp") or "")
            mailgun_signature = mg_sig.get("signature")
            if mailgun_token:
                event_id = mailgun_token

        # Resend / Svix Webhook Format
        if "data" in data and isinstance(data["data"], dict):
            resend_data = data["data"]
            sender_email = resend_data.get("from") or ""
            to_val = resend_data.get("to")
            recipient_email = to_val[0] if isinstance(to_val, list) and to_val else str(to_val or recipient_email)
            subject = resend_data.get("subject") or subject
            body = resend_data.get("text") or resend_data.get("html") or ""
            provider_message_id = resend_data.get("message_id") or resend_data.get("id")
            in_reply_to = resend_data.get("in_reply_to")
            references = resend_data.get("references")

            # Extract RFC headers if structured in Resend
            h_obj = resend_data.get("headers")
            if isinstance(h_obj, list):
                for item in h_obj:
                    if isinstance(item, dict):
                        n = (item.get("name") or "").lower()
                        v = item.get("value") or ""
                        if n == "in-reply-to" and not in_reply_to:
                            in_reply_to = v.strip("<>")
                        elif n == "references" and not references:
                            references = v
                        elif n == "message-id" and not provider_message_id:
                            provider_message_id = v.strip("<>")
            elif isinstance(h_obj, dict):
                for k, v in h_obj.items():
                    k_low = k.lower()
                    if k_low == "in-reply-to" and not in_reply_to:
                        in_reply_to = str(v).strip("<>")
                    elif k_low == "references" and not references:
                        references = str(v)
                    elif k_low == "message-id" and not provider_message_id:
                        provider_message_id = str(v).strip("<>")
            else:
                headers_raw = str(h_obj or "")
        else:
            # Generic JSON Webhook Format
            sender_email = data.get("from") or data.get("sender") or data.get("sender_email") or ""
            recipient_email = data.get("to") or data.get("recipient") or recipient_email
            subject = data.get("subject") or subject
            body = data.get("text") or data.get("body") or data.get("html") or ""
            in_reply_to = data.get("in_reply_to") or data.get("in-reply-to")
            references = data.get("references")
            provider_message_id = data.get("message_id") or data.get("id") or data.get("provider_message_id")
            headers_raw = str(data.get("headers") or "")

        event_id = (
            event_id
            or data.get("id")
            or request.headers.get("svix-id")
            or request.headers.get("x-event-id")
            or provider_message_id
        )

    elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        sender_email = str(form.get("from") or form.get("sender") or "")
        recipient_email = str(form.get("to") or form.get("recipient") or recipient_email)
        subject = str(form.get("subject") or subject)
        body = str(form.get("text") or form.get("body") or form.get("html") or form.get("stripped-text") or form.get("body-plain") or "")
        in_reply_to = str(form.get("in-reply-to") or form.get("In-Reply-To") or "") or None
        references = str(form.get("references") or form.get("References") or "") or None
        provider_message_id = str(form.get("message-id") or form.get("Message-Id") or "") or None
        headers_raw = str(form.get("headers") or form.get("message-headers") or "")

        # Mailgun parameters
        mailgun_token = form.get("token")
        mailgun_timestamp = form.get("timestamp")
        mailgun_signature = form.get("signature")
        if mailgun_token:
            event_id = str(mailgun_token)
        else:
            event_id = str(form.get("id") or provider_message_id or "")

    # 2. RFC 2822 Header Fallback Extraction (SendGrid / Mailgun raw header block)
    if headers_raw:
        if not provider_message_id:
            m_id = re.search(r"(?i)^Message-ID:\s*<([^>]+)>", headers_raw, re.MULTILINE)
            if m_id:
                provider_message_id = m_id.group(1).strip()
        if not in_reply_to:
            m_irt = re.search(r"(?i)^In-Reply-To:\s*<([^>]+)>", headers_raw, re.MULTILINE)
            if m_irt:
                in_reply_to = m_irt.group(1).strip()
        if not references:
            m_ref = re.search(r"(?i)^References:\s*(.+)$", headers_raw, re.MULTILINE)
            if m_ref:
                references = m_ref.group(1).strip()

    # 3. Cryptographic Signature & Shared Secret Verification (Fail-Closed in Production)
    has_svix_headers = "svix-id" in request.headers and "svix-signature" in request.headers
    has_mailgun_sig = bool(mailgun_token and mailgun_timestamp and mailgun_signature)
    has_hmac_headers = "x-webhook-signature" in request.headers or "x-signature-sha256" in request.headers

    # Extract shared secret / token (SendGrid Inbound Parse / Generic webhooks)
    # Prefer header X-Webhook-Secret or Authorization header over URL query string to prevent log leaks
    auth_header = request.headers.get("authorization", "")
    extracted_token = request.headers.get("x-webhook-secret")
    if not extracted_token and auth_header:
        if auth_header.lower().startswith("bearer "):
            extracted_token = auth_header[7:].strip()
        elif auth_header.lower().startswith("basic "):
            import base64
            try:
                decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
                extracted_token = decoded.split(":")[-1].strip()
            except Exception:
                pass
    if not extracted_token:
        # Fallback to query parameter (discouraged in production logs)
        extracted_token = request.query_params.get("token")

    if has_svix_headers:
        secret = settings.RESEND_WEBHOOK_SECRET
        if not secret:
            if settings.APP_ENV == "production":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Svix signature verification failed: RESEND_WEBHOOK_SECRET is not configured.",
                )
        else:
            is_valid, err = verify_resend_svix_signature(raw_body, request.headers, secret)
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid Resend Svix webhook signature: {err}",
                )
    elif has_mailgun_sig:
        secret = settings.MAILGUN_WEBHOOK_SIGNING_KEY or settings.OUTREACH_WEBHOOK_SECRET
        if not secret:
            if settings.APP_ENV == "production":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Mailgun verification failed: MAILGUN_WEBHOOK_SIGNING_KEY is not configured.",
                )
        else:
            is_valid, err = verify_mailgun_webhook_signature(
                str(mailgun_token),
                str(mailgun_timestamp),
                str(mailgun_signature),
                secret,
            )
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid Mailgun webhook signature: {err}",
                )
    elif extracted_token:
        secret = settings.OUTREACH_WEBHOOK_SECRET
        if not secret:
            if settings.APP_ENV == "production":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Shared secret verification failed: OUTREACH_WEBHOOK_SECRET is not configured.",
                )
        else:
            import hmac
            if not hmac.compare_digest(extracted_token.strip(), secret.strip()):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook shared secret authentication credentials.",
                )
    elif has_hmac_headers:
        secret = settings.OUTREACH_WEBHOOK_SECRET
        if not secret:
            if settings.APP_ENV == "production":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="HMAC signature verification failed: OUTREACH_WEBHOOK_SECRET is not configured.",
                )
        else:
            sig = request.headers.get("x-webhook-signature") or request.headers.get("x-signature-sha256") or ""
            ts = request.headers.get("x-webhook-timestamp")
            is_valid, err = verify_hmac_webhook_signature(raw_body, sig, secret, timestamp=ts)
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid webhook HMAC signature: {err}",
                )
    elif settings.OUTREACH_WEBHOOK_SECRET or settings.APP_ENV == "production":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or unauthenticated webhook credentials. Signature headers or shared secret required.",
        )

    # 4. Distributed Replay Protection & Deduplication
    if settings.REDIS_URL and webhook_cache._redis is None:
        webhook_cache.init_redis(settings.REDIS_URL)

    effective_event_id = event_id or f"{sender_email}:{provider_message_id or uuid.uuid4().hex}"
    is_prod = settings.APP_ENV == "production"

    try:
        is_fresh = webhook_cache.check_and_record(
            str(effective_event_id),
            is_production=is_prod,
        )
    except DistributedReplayUnavailableError as exc:
        logger.error("Fail-closed: Distributed replay protection unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook ingestion unavailable: Distributed replay protection cannot be guaranteed in production.",
        )

    if not is_fresh:
        return {
            "status": "duplicate",
            "message": "Webhook event already processed (idempotent ignore)",
            "event_id": str(effective_event_id),
        }

    # 5. Validate Required Fields
    if not sender_email or not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required 'sender' or 'body' in webhook payload",
        )

    # Normalize sender email
    if "<" in sender_email and ">" in sender_email:
        sender_email = sender_email.split("<")[1].split(">")[0].strip()
    sender_email = sender_email.strip().lower()

    # 6. Ingestion & Conversation Resolution
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
