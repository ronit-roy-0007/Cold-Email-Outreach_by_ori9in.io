"""
IntentLead AI — Inbound Email Reply Detection & Ingestion Service
Resolves conversations via Message-ID/In-Reply-To threading, stops pending follow-ups,
persists replies as untrusted text, and notifies operators via Telegram.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Business,
    Campaign,
    Contact,
    Conversation,
    ConversationMessage,
    Lead,
    utc_now,
)
from app.services.audit import record_audit_log
from app.services.followup_engine import stop_pending_followups
from app.services.telegram_bot import send_telegram_text

logger = logging.getLogger("inbound_service")


def sanitize_email_text(raw_text: str | None) -> str:
    """
    Sanitizes untrusted inbound email body text.
    Strips raw HTML script tags, unescapes entities, and protects against XSS injection.
    """
    if not raw_text:
        return ""
    clean = re.sub(r"(?is)<script[^>]*>.*?</script>", "", raw_text)
    clean = re.sub(r"(?is)<style[^>]*>.*?</style>", "", clean)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = html.unescape(clean)
    return clean.strip()


def resolve_conversation_for_inbound(
    db: Session,
    sender_email: str,
    in_reply_to: str | None = None,
    references: str | None = None,
    subject: str | None = None,
) -> Conversation | None:
    """
    Resolves the matching conversation using multi-tier threading hierarchy:
    1. Direct Message-ID / In-Reply-To match
    2. References header match
    3. Sender email match (matching active conversation where prospect was the recipient)
    """
    clean_sender = sender_email.lower().strip()

    # Tier 1: In-Reply-To header matching our outbound provider message id
    if in_reply_to and in_reply_to.strip():
        clean_irt = in_reply_to.strip().strip("<>")
        msg = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.provider_message_id == clean_irt)
            .first()
        )
        if msg:
            return db.get(Conversation, msg.conversation_id)

    # Tier 2: References header matching
    if references and references.strip():
        ref_tokens = re.findall(r"<([^>]+)>", references)
        for ref_id in ref_tokens:
            msg = (
                db.query(ConversationMessage)
                .filter(ConversationMessage.provider_message_id == ref_id)
                .first()
            )
            if msg:
                return db.get(Conversation, msg.conversation_id)

    # Tier 3: Controlled Fallback — Prospect email match on most recent active conversation
    conv = (
        db.query(Conversation)
        .filter(Conversation.recipient_email == clean_sender)
        .order_by(Conversation.last_message_at.desc())
        .first()
    )
    return conv


def send_reply_telegram_notification(
    settings: Settings,
    conv: Conversation,
    business: Business | None,
    lead: Lead | None,
    campaign: Campaign | None,
    reply_body: str,
    contact_name: str | None = None,
) -> bool:
    """
    Notifies authorized operators on Telegram when a prospect replies.
    """
    bot_token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_ALLOWED_USER_ID
    if not bot_token or not chat_id:
        logger.info("Telegram notification skipped: Bot token or allowed chat ID not configured")
        return False

    biz_name = business.name if business else "Unmatched Business"
    site = business.website if (business and business.website) else "None"
    camp_name = campaign.niche if campaign else "Direct Outreach"
    loc = business.locality if (business and business.locality) else ""
    score = lead.overall_score if lead else 0
    classification = "HOT LEAD 🔥" if score >= 75 else ("WARM" if score >= 50 else "ENGAGED")

    # Clean excerpt
    body_excerpt = reply_body[:350] + ("..." if len(reply_body) > 350 else "")

    text = (
        f"🔔 *NEW PROSPECT REPLY RECEIVED!*\n\n"
        f"🏢 *Business:* {biz_name}\n"
        f"👤 *Contact:* {contact_name or 'Business Owner'}\n"
        f"📧 *Email:* `{conv.recipient_email}`\n"
        f"🌐 *Website:* {site}\n"
        f"📍 *Locality:* {loc}\n"
        f"🎯 *Campaign:* {camp_name}\n"
        f"⭐ *Lead Score:* {score}/100 ({classification})\n\n"
        f"💬 *MESSAGE:* \n_{body_excerpt}_\n\n"
        f"🔗 Access the Unified Inbox on your dashboard to respond directly."
    )

    buttons = [
        [
            {"text": "💬 Open Conversation in Inbox", "url": f"http://127.0.0.1:8000/inbox?conversation_id={conv.id}"},
        ],
        [
            {"text": "👤 Inspect Lead Dossier", "url": f"http://127.0.0.1:8000/leads/{conv.lead_id}" if conv.lead_id else "http://127.0.0.1:8000/leads"},
        ]
    ]

    try:
        send_telegram_text(bot_token, chat_id, text, buttons=buttons)
        return True
    except Exception as exc:
        logger.warning("Failed to deliver Telegram reply alert: %s", exc)
        return False


def process_inbound_email(
    db: Session,
    settings: Settings,
    *,
    sender_email: str,
    recipient_email: str,
    subject: str,
    raw_body: str,
    provider_message_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    provider: str = "webhook",
) -> dict[str, Any]:
    """
    Ingests an inbound prospect reply, matches the conversation, stops follow-ups,
    persists the message, and triggers Telegram alerts and audit records.
    """
    clean_sender = sender_email.strip().lower()
    clean_recipient = recipient_email.strip().lower()
    clean_body = sanitize_email_text(raw_body)
    clean_subject = (subject or "Re: Outreach").strip()
    msg_id = provider_message_id or f"inbound-{uuid.uuid4().hex[:12]}@prospect.domain"

    # Deduplication check
    existing_msg = (
        db.query(ConversationMessage)
        .filter_by(provider_message_id=msg_id)
        .first()
    )
    if existing_msg:
        return {
            "status": "already_processed",
            "message_id": str(existing_msg.id),
            "conversation_id": str(existing_msg.conversation_id),
        }

    # Resolve conversation
    conv = resolve_conversation_for_inbound(
        db,
        sender_email=clean_sender,
        in_reply_to=in_reply_to,
        references=references,
        subject=clean_subject,
    )

    lead = None
    biz = None
    camp = None

    if conv:
        lead = db.get(Lead, conv.lead_id) if conv.lead_id else None
        biz = db.get(Business, conv.business_id) if conv.business_id else None
        camp = db.get(Campaign, conv.campaign_id) if conv.campaign_id else None
    else:
        # Fallback: Find lead directly by email
        biz = db.query(Business).filter(Business.email.ilike(clean_sender)).first()
        if biz:
            lead = db.query(Lead).filter_by(business_id=biz.id).order_by(Lead.overall_score.desc()).first()
            if lead:
                camp = db.get(Campaign, lead.campaign_id)

        # Create new unassigned conversation
        conv = Conversation(
            lead_id=lead.id if lead else None,
            campaign_id=camp.id if camp else None,
            business_id=biz.id if biz else None,
            recipient_email=clean_sender,
            sender_email=clean_recipient,
            subject=clean_subject,
            status="active",
            unread_count=0,
            last_message_at=utc_now(),
            followup_status="idle",
        )
        db.add(conv)
        db.flush()

    # 1. Persist inbound message
    msg = ConversationMessage(
        conversation_id=conv.id,
        direction="inbound",
        message_type="prospect_reply",
        sender=clean_sender,
        recipient=clean_recipient,
        subject=clean_subject,
        body=clean_body,
        provider_message_id=msg_id,
        in_reply_to=in_reply_to,
        references=references,
        delivery_status="received",
        created_at=utc_now(),
    )
    db.add(msg)

    # 2. Update conversation status
    conv.status = "replied"
    conv.unread_count += 1
    conv.last_message_at = utc_now()

    # 3. Mandatory Stop Condition: Cancel all pending automated follow-ups immediately
    cancelled_count = stop_pending_followups(db, conv.id, reason="prospect_replied")

    # 4. Update Lead outreach status if linked
    if lead:
        lead.outreach_status = "replied"

    db.commit()

    # 5. Dispatch Operator Telegram Alert
    contact_name = None
    if biz:
        contact_record = db.query(Contact).filter_by(business_id=biz.id).first()
        if contact_record:
            contact_name = contact_record.full_name

    tg_alert_sent = send_reply_telegram_notification(
        settings=settings,
        conv=conv,
        business=biz,
        lead=lead,
        campaign=camp,
        reply_body=clean_body,
        contact_name=contact_name,
    )

    # 6. Record Audit Event
    record_audit_log(
        db,
        action="inbound_prospect_reply_received",
        operator_id="prospect_email",
        details={
            "sender": clean_sender,
            "subject": clean_subject,
            "provider_message_id": msg_id,
            "followups_cancelled": cancelled_count,
            "telegram_alert": tg_alert_sent,
        },
    )

    return {
        "status": "success",
        "conversation_id": str(conv.id),
        "message_id": str(msg.id),
        "stopped_followups": cancelled_count,
        "followups_cancelled": cancelled_count,
        "telegram_notified": tg_alert_sent,
    }
