"""
IntentLead AI — Operator Reply Service
Handles sending manual responses from the Unified Inbox, preserving RFC email threading,
pausing automated follow-ups by default, and maintaining audit logging.
"""

from __future__ import annotations

import logging
from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Conversation,
    ConversationMessage,
    MailboxAccount,
    SuppressionEntry,
    utc_now,
)
from app.services.audit import record_audit_log
from app.services.email_dispatcher import send_google_workspace_email, send_smtp_email
from app.services.followup_engine import pause_followups as pause_conv_followups

logger = logging.getLogger("operator_reply")


def send_operator_reply(
    db: Session,
    settings: Settings,
    conversation_id: uuid.UUID,
    body: str | None = None,
    operator_id: str = "operator_web_ui",
    pause_automated_followups: bool = True,
    reply_body: str | None = None,
    pause_followups: bool | None = None,
    subject: str | None = None,
) -> dict[str, Any]:
    """
    Sends an operator response from the Unified Inbox.
    Maintains email threading headers, checks suppression, and pauses automated follow-ups.
    """
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise ValueError(f"Conversation {conversation_id} not found")

    raw_body = body or reply_body or ""
    clean_body = raw_body.strip()
    if not clean_body:
        raise ValueError("Reply message body cannot be empty")

    should_pause = pause_followups if pause_followups is not None else pause_automated_followups

    recipient_email = conv.recipient_email.lower().strip()

    # 1. Gate: Pre-flight suppression check
    suppressed = (
        db.query(SuppressionEntry)
        .filter_by(email=recipient_email)
        .first()
    )
    if suppressed:
        raise ValueError(f"Cannot reply: Recipient '{recipient_email}' is on the suppression list ({suppressed.reason}).")

    # 2. Find latest message for threading headers
    latest_msg = (
        db.query(ConversationMessage)
        .filter_by(conversation_id=conv.id)
        .order_by(ConversationMessage.created_at.desc())
        .first()
    )

    in_reply_to = latest_msg.provider_message_id if latest_msg else None
    references = None
    if in_reply_to:
        references = f"<{in_reply_to}>"

    # Thread subject
    subject = conv.subject if conv.subject.lower().startswith("re:") else f"Re: {conv.subject}"

    # Generate provider message ID
    provider_msg_id = f"intentlead-op-{uuid.uuid4().hex[:12]}@intentlead.agency"

    # 3. Dispatch / Simulation
    sender_name = settings.AGENCY_SENDER_NAME or "Ronit"
    sender_email = conv.sender_email or settings.SENDER_EMAIL or "outreach@ori9in.io"
    delivery_status = "simulated"

    if not settings.OUTREACH_DRY_RUN:
        # Resolve mailbox account credentials if configured
        mailbox = (
            db.query(MailboxAccount)
            .filter_by(email=sender_email, is_active=True)
            .first()
        )
        mb_pass = mailbox.get_password(settings.FIELD_ENCRYPTION_KEY) if mailbox else settings.SMTP_PASSWORD

        try:
            if settings.EMAIL_PROVIDER == "google_workspace":
                send_google_workspace_email(
                    settings=settings,
                    sender_name=sender_name,
                    sender_email=sender_email,
                    recipient_email=recipient_email,
                    subject=subject,
                    body=clean_body,
                    unsubscribe_url="",
                    password=mb_pass,
                )
            else:
                send_smtp_email(
                    settings=settings,
                    sender_name=sender_name,
                    sender_email=sender_email,
                    recipient_email=recipient_email,
                    subject=subject,
                    body=clean_body,
                    unsubscribe_url="",
                    password=mb_pass,
                )
            delivery_status = "sent"
        except Exception as exc:
            logger.error("Failed to send operator reply: %s", exc)
            delivery_status = "failed"
            raise

    # 4. Persist outbound message in conversation
    msg = ConversationMessage(
        conversation_id=conv.id,
        direction="outbound",
        message_type="operator_reply",
        sender=sender_email,
        recipient=recipient_email,
        subject=subject,
        body=clean_body,
        provider_message_id=provider_msg_id,
        in_reply_to=in_reply_to,
        references=references,
        delivery_status=delivery_status,
        created_at=utc_now(),
    )
    db.add(msg)

    # 5. Update conversation state
    conv.last_message_at = utc_now()
    conv.unread_count = 0

    # 6. Pause automated follow-ups by default
    followups_paused = 0
    if should_pause:
        followups_paused = pause_conv_followups(db, conv.id, reason="operator_manual_reply")

    db.commit()

    # 7. Audit Logging
    record_audit_log(
        db,
        action="operator_inbox_reply_sent",
        operator_id=operator_id,
        details={
            "recipient": recipient_email,
            "message_id": str(msg.id),
            "conversation_id": str(conv.id),
            "delivery_status": delivery_status,
            "dry_run": settings.OUTREACH_DRY_RUN,
            "followups_paused": followups_paused,
        },
    )

    return {
        "status": "success",
        "message_id": str(msg.id),
        "delivery_status": delivery_status,
        "followups_paused": followups_paused,
    }
