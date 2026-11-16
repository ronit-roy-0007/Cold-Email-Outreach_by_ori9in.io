from __future__ import annotations

import random
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable
import uuid

import httpx
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Business, Campaign, Lead, MessageDraft, OutboundMessage, utc_now
from app.services.drafts import generate_hook_subject
from app.services.email_compliance import (
    build_unsubscribe_url,
    format_compliant_email_body,
    get_unsubscribe_headers,
)
from app.services.email_gate import (
    check_and_increment_daily_quota,
    is_suppressed,
    preflight_deliverability_gate,
)
from app.services.mailbox_pool import (
    get_mailbox_sent_count,
    get_next_available_mailbox,
    load_mailbox_pool,
)


class EmailDispatchError(Exception):
    pass


def send_smtp_email(
    settings: Settings,
    sender_name: str,
    sender_email: str,
    recipient_email: str,
    subject: str,
    body: str,
    unsubscribe_url: str,
    password: str | None = None,
) -> None:
    if not settings.SMTP_HOST:
        raise EmailDispatchError("SMTP_HOST is not configured")

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    msg["To"] = recipient_email
    msg["Subject"] = subject

    is_casual = (
        "tried to reach you a few times" in body
        or "Should I show you the demo" in body
        or "Where should we go from here" in body
    )
    if not is_casual and unsubscribe_url:
        for k, v in get_unsubscribe_headers(unsubscribe_url).items():
            msg[k] = v

    msg.attach(MIMEText(body, "plain", "utf-8"))

    if settings.SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
        if settings.SMTP_USE_TLS:
            server.starttls()

    eff_user = sender_email or settings.SMTP_USER
    eff_pass = password or settings.SMTP_PASSWORD
    try:
        if eff_user and eff_pass:
            server.login(eff_user, eff_pass)
        server.send_message(msg)
    finally:
        server.quit()


def send_resend_email(
    settings: Settings,
    sender_name: str,
    sender_email: str,
    recipient_email: str,
    subject: str,
    body: str,
    unsubscribe_url: str,
) -> None:
    if not settings.RESEND_API_KEY:
        raise EmailDispatchError("RESEND_API_KEY is not configured")

    from_addr = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    headers = get_unsubscribe_headers(unsubscribe_url)

    resp = httpx.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_addr,
            "to": [recipient_email],
            "subject": subject,
            "text": body,
            "headers": headers,
        },
        timeout=10.0,
    )
    if resp.status_code >= 400:
        raise EmailDispatchError(f"Resend API error ({resp.status_code}): {resp.text}")


def send_google_workspace_email(
    settings: Settings,
    sender_name: str,
    sender_email: str,
    recipient_email: str,
    subject: str,
    body: str,
    unsubscribe_url: str,
    password: str | None = None,
) -> None:
    """
    Google Workspace dispatch: uses Google Workspace SMTP relay or app password.
    Host defaults to smtp.gmail.com:587 with TLS.
    """
    host = settings.SMTP_HOST or "smtp.gmail.com"
    port = settings.SMTP_PORT or 587
    user = sender_email or settings.SMTP_USER
    effective_password = password or settings.SMTP_PASSWORD or settings.GOOGLE_WORKSPACE_CREDENTIALS

    if not effective_password:
        raise EmailDispatchError("Google Workspace credentials/app password not configured")

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    msg["To"] = recipient_email
    msg["Subject"] = subject

    is_casual = (
        "tried to reach you a few times" in body
        or "Should I show you the demo" in body
        or "Where should we go from here" in body
    )
    if not is_casual and unsubscribe_url:
        for k, v in get_unsubscribe_headers(unsubscribe_url).items():
            msg[k] = v

    msg.attach(MIMEText(body, "plain", "utf-8"))

    server = smtplib.SMTP(host, port, timeout=10)
    server.starttls()
    try:
        server.login(user, password)
        server.send_message(msg)
    finally:
        server.quit()


def dispatch_single_email(
    db: Session,
    lead: Lead,
    biz: Business,
    settings: Settings,
    *,
    subject: str | None = None,
    pitch_body: str | None = None,
    agency_name: str | None = None,
    sender_name: str | None = None,
    sender_email: str | None = None,
    mailbox_password: str | None = None,
    resolver_fn: Callable[[str], list[str]] | None = None,
) -> OutboundMessage:
    """
    Dispatches or simulates outreach for a single lead with all deliverability and compliance gates.
    """
    recipient_email = (biz.email or "").strip()
    eff_agency_name = (agency_name or settings.AGENCY_NAME or "ori9in.io").strip()
    eff_sender_name = (sender_name or settings.AGENCY_SENDER_NAME or "Ronit").strip()
    eff_sender_email = (sender_email or settings.SENDER_EMAIL or f"outreach@{eff_agency_name.lower().replace(' ', '')}").strip()
    eff_provider = (settings.EMAIL_PROVIDER or "smtp").lower()

    if not pitch_body:
        draft = db.query(MessageDraft).filter_by(lead_id=lead.id).first()
        pitch_body = draft.body if (draft and draft.body) else f"Hello {biz.name},\n\nWe would love to connect."

    eff_subject = subject or generate_hook_subject(biz.name, lead.recommended_service)

    # CAN-SPAM Compliance link & footer
    unsub_url = build_unsubscribe_url(
        recipient_email or "unregistered@intentlead.agency",
        settings.UNSUBSCRIBE_SECRET,
        settings.UNSUBSCRIBE_BASE_URL,
    )
    compliant_body = format_compliant_email_body(
        pitch_body,
        eff_agency_name,
        eff_sender_name,
        settings.AGENCY_PHYSICAL_ADDRESS,
        unsub_url,
    )

    outbound = OutboundMessage(
        lead_id=lead.id,
        campaign_id=lead.campaign_id,
        recipient_email=recipient_email,
        sender_email=eff_sender_email,
        subject=eff_subject,
        body=compliant_body,
        provider=eff_provider,
        status="pending",
    )
    db.add(outbound)
    db.flush()

    # Gate 0: Human Approval Enforcement (Mandatory)
    if getattr(lead, "outreach_status", "") != "approved":
        outbound.status = "rejected"
        outbound.error_message = (
            f"Dispatch rejected: lead status is '{getattr(lead, 'outreach_status', 'unknown')}', "
            "mandatory human approval required before outbound dispatch."
        )
        db.flush()
        return outbound

    # Gate 1: Check recipient email presence
    if not recipient_email:
        outbound.status = "failed"
        outbound.error_message = "no_recipient_email_available"
        lead.outreach_status = "failed"
        db.flush()
        return outbound

    # Gate 2: Pre-Flight MX & Deliverability Gate
    is_valid, reason = preflight_deliverability_gate(recipient_email, db=db, resolver_fn=resolver_fn)
    if not is_valid:
        if reason == "recipient_on_suppression_list":
            outbound.status = "suppressed"
            outbound.error_message = "Suppressed: recipient is on unsubscribe list"
            lead.outreach_status = "suppressed"
        else:
            outbound.status = "bounced"
            outbound.error_message = f"Pre-flight gate rejected: {reason}"
            lead.outreach_status = "bounced"
        db.flush()
        return outbound

    # Gate 3: Pacing & Throttling
    quota_allowed, current_count = check_and_increment_daily_quota(
        db,
        eff_sender_email,
        max_daily=settings.MAX_EMAILS_PER_DAY,
        dry_run=settings.OUTREACH_DRY_RUN,
    )
    if not quota_allowed:
        outbound.status = "failed"
        outbound.error_message = f"Daily sending quota of {settings.MAX_EMAILS_PER_DAY} exceeded ({current_count} already dispatched today)"
        lead.outreach_status = "throttled"
        db.flush()
        return outbound

    # Gate 4: Operator safety toggle (OUTREACH_DRY_RUN)
    if settings.OUTREACH_DRY_RUN:
        outbound.status = "simulated"
        outbound.dispatched_at = utc_now()
        outbound.error_message = "Dry-run simulation: email recorded and validated without sending live message."
        lead.outreach_status = "simulated"
        db.flush()
        return outbound

    # Live Dispatch via selected provider
    try:
        if eff_provider == "resend":
            send_resend_email(
                settings,
                eff_sender_name,
                eff_sender_email,
                recipient_email,
                eff_subject,
                compliant_body,
                unsub_url,
            )
        elif eff_provider == "google_workspace":
            send_google_workspace_email(
                settings,
                eff_sender_name,
                eff_sender_email,
                recipient_email,
                eff_subject,
                compliant_body,
                unsub_url,
                password=mailbox_password,
            )
        else:  # default "smtp"
            send_smtp_email(
                settings,
                eff_sender_name,
                eff_sender_email,
                recipient_email,
                eff_subject,
                compliant_body,
                unsub_url,
                password=mailbox_password,
            )

        outbound.status = "sent"
        outbound.dispatched_at = utc_now()
        lead.outreach_status = "sent"
        db.flush()
    except Exception as exc:
        outbound.status = "failed"
        outbound.error_message = str(exc)
        lead.outreach_status = "failed"
        db.flush()

    return outbound


def dispatch_approved_campaign_leads(
    db: Session,
    campaign_id: uuid.UUID,
    settings: Settings,
    *,
    lead_ids: list[uuid.UUID] | None = None,
    agency_name: str | None = None,
    sender_name: str | None = None,
    resolver_fn: Callable[[str], list[str]] | None = None,
) -> dict[str, Any]:
    """
    Dispatches all approved leads for a given campaign.
    """
    query = (
        db.query(Lead, Business)
        .join(Business, Lead.business_id == Business.id)
        .filter(Lead.campaign_id == campaign_id)
        .filter(Lead.outreach_status == "approved")
    )
    if lead_ids:
        query = query.filter(Lead.id.in_(lead_ids))

    leads = query.all()

    summary: dict[str, Any] = {
        "total_candidates": len(leads),
        "sent": 0,
        "simulated": 0,
        "suppressed": 0,
        "bounced": 0,
        "failed": 0,
        "throttled": 0,
        "records": [],
    }

    pool = load_mailbox_pool(db, settings)
    current_mailbox_idx = 0

    for lead_idx, (lead, biz) in enumerate(leads):
        # Round-robin selection of next available mailbox with quota headroom
        mailbox, next_idx = get_next_available_mailbox(pool, db, current_mailbox_idx)

        if mailbox is None:
            # All mailboxes in the pool have hit their daily quota limit (e.g. 50/day each)
            lead.outreach_status = "throttled"
            summary["throttled"] += 1
            summary["records"].append(
                {
                    "lead_id": str(lead.id),
                    "business_name": biz.name,
                    "recipient_email": (biz.email or "").strip(),
                    "sender_mailbox": "none_available",
                    "status": "throttled",
                    "error": f"All {len(pool)} mailboxes have reached their daily sending limit ({settings.MAX_EMAILS_PER_DAY}/day)",
                }
            )
            continue

        current_mailbox_idx = next_idx
        eff_sender = mailbox.sender_name or sender_name or settings.AGENCY_SENDER_NAME

        msg = dispatch_single_email(
            db=db,
            lead=lead,
            biz=biz,
            settings=settings,
            agency_name=agency_name,
            sender_name=eff_sender,
            sender_email=mailbox.email,
            mailbox_password=mailbox.password,
            resolver_fn=resolver_fn,
        )
        if msg.status == "sent":
            summary["sent"] += 1
        elif msg.status == "simulated":
            summary["simulated"] += 1
        elif msg.status == "suppressed":
            summary["suppressed"] += 1
        elif msg.status == "bounced":
            summary["bounced"] += 1
        elif msg.status == "throttled":
            summary["throttled"] += 1
        else:
            summary["failed"] += 1

        summary["records"].append(
            {
                "lead_id": str(lead.id),
                "business_name": biz.name,
                "recipient_email": msg.recipient_email,
                "sender_mailbox": msg.sender_email,
                "status": msg.status,
                "error": msg.error_message,
            }
        )

        # Smart Safety Pacing Guard:
        # Enforces human-like delays and protects mailboxes if the active pool shrinks
        if (
            msg.status == "sent"
            and not settings.OUTREACH_DRY_RUN
            and getattr(settings, "ENABLE_DISPATCH_PACING", True)
            and "pytest" not in sys.modules
            and (lead_idx < len(leads) - 1)
        ):
            remaining_active_mailboxes = [
                m for m in pool if get_mailbox_sent_count(db, m.email) < m.daily_limit
            ]
            active_count = len(remaining_active_mailboxes)

            if active_count < 3:
                # High Risk: Pool has narrowed to 1 or 2 accounts.
                # Enforce a strict 30-40s cooldown between sends to protect the surviving mailboxes.
                cooldown = random.uniform(30.0, 40.0)
                time.sleep(cooldown)
            else:
                # Normal Healthy Rotation (3+ mailboxes):
                # A subtle 5-8s human jitter is applied.
                jitter = random.uniform(5.0, 8.0)
                time.sleep(jitter)

    db.commit()
    return summary
