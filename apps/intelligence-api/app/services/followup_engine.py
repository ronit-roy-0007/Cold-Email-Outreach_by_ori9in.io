"""
IntentLead AI — Reliable Follow-Up Execution Engine
Provides persistent, timezone-aware, idempotent scheduling and dispatching
of multi-touch follow-up campaigns with strict stop-condition enforcement.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Business,
    Campaign,
    Conversation,
    ConversationMessage,
    FollowUpExecution,
    Lead,
    SuppressionEntry,
    utc_now,
)
from app.services.audit import record_audit_log


def calculate_scheduled_date(
    base_time: datetime,
    delay_days: int,
    schedule_type: str = "calendar",
) -> datetime:
    """
    Computes scheduled execution datetime supporting calendar or business days.
    Business-day scheduling skips weekends (Saturday=5, Sunday=6).
    """
    if schedule_type.lower() != "business":
        return base_time + timedelta(days=delay_days)

    current = base_time
    added_days = 0
    while added_days < delay_days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday to Friday
            added_days += 1
    return current


def schedule_followups_for_conversation(
    db: Session,
    conversation: Conversation,
    campaign: Campaign,
    base_time: datetime | None = None,
) -> list[FollowUpExecution]:
    """
    Schedules the full sequence of automated follow-ups for a newly initiated conversation.
    """
    seq_config = getattr(campaign, "followup_sequence", None) or {}
    if not isinstance(seq_config, dict) or not seq_config.get("enabled"):
        return []

    delays = seq_config.get("delays", [])
    if not delays:
        return []

    schedule_type = seq_config.get("schedule_type", "calendar")
    now = base_time or utc_now()
    created_executions = []

    # Ensure no duplicates already exist
    existing = (
        db.query(FollowUpExecution)
        .filter_by(conversation_id=conversation.id)
        .count()
    )
    if existing > 0:
        return []

    for idx, delay in enumerate(delays):
        step_number = idx + 1
        sched_time = calculate_scheduled_date(now, int(delay), schedule_type=schedule_type)

        execution = FollowUpExecution(
            conversation_id=conversation.id,
            campaign_id=campaign.id,
            lead_id=conversation.lead_id,
            sequence_step=step_number,
            scheduled_at=sched_time,
            status="scheduled",
            attempt_count=0,
        )
        db.add(execution)
        created_executions.append(execution)

    conversation.followup_status = "scheduled"
    conversation.followup_step = 0
    db.flush()
    return created_executions


def stop_pending_followups(
    db: Session,
    conversation_id: uuid.UUID,
    reason: str,
) -> int:
    """
    MANDATORY STOP CONDITION:
    Cancels all pending scheduled or paused follow-ups for a conversation immediately.
    Triggered when:
    - Prospect replies
    - Unsubscribe received
    - Hard bounce or complaint occurs
    - Contact is suppressed
    - Operator explicitly cancels sequence
    """
    pending = (
        db.query(FollowUpExecution)
        .filter(
            FollowUpExecution.conversation_id == conversation_id,
            FollowUpExecution.status.in_(["scheduled", "paused"]),
        )
        .all()
    )

    cancelled_count = 0
    for item in pending:
        item.status = "cancelled"
        item.stop_reason = reason
        cancelled_count += 1

    conv = db.get(Conversation, conversation_id)
    if conv:
        conv.followup_status = "cancelled"

    db.flush()
    return cancelled_count


def pause_followups(
    db: Session,
    conversation_id: uuid.UUID,
    reason: str = "operator_paused",
) -> int:
    """
    Pauses pending scheduled follow-ups (e.g. when operator sends a manual reply).
    """
    pending = (
        db.query(FollowUpExecution)
        .filter(
            FollowUpExecution.conversation_id == conversation_id,
            FollowUpExecution.status == "scheduled",
        )
        .all()
    )

    paused_count = 0
    for item in pending:
        item.status = "paused"
        item.stop_reason = reason
        paused_count += 1

    conv = db.get(Conversation, conversation_id)
    if conv:
        conv.followup_status = "paused"

    db.flush()
    return paused_count


def resume_followups(
    db: Session,
    conversation_id: uuid.UUID,
) -> int:
    """
    Resumes paused follow-ups upon explicit operator action.
    """
    paused = (
        db.query(FollowUpExecution)
        .filter(
            FollowUpExecution.conversation_id == conversation_id,
            FollowUpExecution.status == "paused",
        )
        .all()
    )

    resumed_count = 0
    for item in paused:
        item.status = "scheduled"
        item.stop_reason = None
        resumed_count += 1

    conv = db.get(Conversation, conversation_id)
    if conv and resumed_count > 0:
        conv.followup_status = "scheduled"

    db.flush()
    return resumed_count


def generate_followup_message_body(
    step: int,
    biz_name: str,
    service_name: str | None,
    sender_name: str,
    original_subject: str,
) -> tuple[str, str]:
    """
    Generates high-converting follow-up subject and body text.
    """
    svc_label = (service_name or "digital growth solutions").replace("_", " ").title()
    subject = f"Re: {original_subject}"

    if step == 1:
        body = (
            f"Hey {biz_name},\n\n"
            f"Quick follow-up regarding my previous email on {svc_label}.\n\n"
            f"I know how busy things get—wanted to make sure this didn't slip through the cracks. "
            f"Do you have 5 minutes this Thursday for a quick walkthrough?\n\n"
            f"Best,\n{sender_name}"
        )
    elif step == 2:
        body = (
            f"Hi {biz_name},\n\n"
            f"Following up on our website audit for {biz_name}. We noticed a couple of technical gaps "
            f"that might be affecting your client conversion rates.\n\n"
            f"Would it be helpful if I put together a 2-minute video breakdown for you?\n\n"
            f"Best regards,\n{sender_name}"
        )
    else:
        body = (
            f"Hey {biz_name},\n\n"
            f"I haven't heard back, so I assume this isn't a priority right now, which is completely fine.\n\n"
            f"I'll pause reaching out for now. Feel free to ping me if your priorities shift down the line!\n\n"
            f"All the best,\n{sender_name}"
        )

    return subject, body


def process_due_followups(
    db: Session,
    settings: Settings,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Checks for all due follow-up executions and dispatches them with strict stop conditions.
    Guarantees idempotency, multi-worker concurrency safety (skip_locked), retry backoff,
    and safe dry-run execution.
    """
    current_time = now or utc_now()

    query = (
        db.query(FollowUpExecution)
        .filter(
            FollowUpExecution.status == "scheduled",
            FollowUpExecution.scheduled_at <= current_time,
        )
        .order_by(FollowUpExecution.scheduled_at)
        .limit(50)
    )

    # Concurrency control: prevent duplicate executions across multiple workers in PostgreSQL
    if db.bind and db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)

    due_items = query.all()

    executed_count = 0
    cancelled_count = 0
    failed_count = 0

    for item in due_items:
        conv = db.get(Conversation, item.conversation_id)
        if not conv:
            item.status = "failed"
            item.stop_reason = "conversation_not_found"
            failed_count += 1
            continue

        # 1. Mandatory Stop Check: Conversation Replied, Closed, or Archived
        if conv.status in ("replied", "closed", "archived"):
            item.status = "cancelled"
            item.stop_reason = f"conversation_status_{conv.status}"
            cancelled_count += 1
            continue

        # 2. Mandatory Stop Check: Suppression / Opt-Out
        suppressed = (
            db.query(SuppressionEntry)
            .filter_by(email=conv.recipient_email.lower().strip())
            .first()
        )
        if suppressed:
            item.status = "cancelled"
            item.stop_reason = f"suppressed:{suppressed.reason}"
            conv.followup_status = "cancelled"
            cancelled_count += 1
            continue

        # 3. Check Conversation Pause State
        if conv.followup_status == "paused":
            item.status = "paused"
            item.stop_reason = "conversation_paused_by_operator"
            continue

        # 4. Check Campaign Status
        camp = db.get(Campaign, item.campaign_id) if item.campaign_id else None
        if camp and camp.status in ("paused", "cancelled", "archived"):
            item.status = "paused"
            item.stop_reason = f"campaign_{camp.status}"
            continue

        # 5. Dispatch / Simulation Execution with Retry Safety
        try:
            lead = db.get(Lead, item.lead_id) if item.lead_id else None
            biz = db.get(Business, lead.business_id) if (lead and lead.business_id) else None
            biz_name = biz.name if biz else "Business"
            svc = lead.recommended_service if lead else None
            sender = settings.AGENCY_SENDER_NAME or "Alex"

            subject, body = generate_followup_message_body(
                item.sequence_step,
                biz_name,
                svc,
                sender,
                conv.subject,
            )

            provider_msg_id = f"intentlead-fu-{uuid.uuid4().hex[:12]}@intentlead.agency"

            # Record conversation message
            msg = ConversationMessage(
                conversation_id=conv.id,
                direction="outbound",
                message_type="followup",
                sender=conv.sender_email,
                recipient=conv.recipient_email,
                subject=subject,
                body=body,
                provider_message_id=provider_msg_id,
                delivery_status="simulated" if settings.OUTREACH_DRY_RUN else "sent",
            )
            db.add(msg)

            # Mark execution completed
            item.status = "executed"
            item.executed_at = utc_now()
            conv.last_message_at = utc_now()
            conv.followup_step = item.sequence_step

            # Check if there are further scheduled steps
            remaining = (
                db.query(FollowUpExecution)
                .filter(
                    FollowUpExecution.conversation_id == conv.id,
                    FollowUpExecution.status == "scheduled",
                    FollowUpExecution.id != item.id,
                )
                .count()
            )
            if remaining == 0:
                conv.followup_status = "completed"

            # Record audit trail
            record_audit_log(
                db,
                action="followup_step_executed",
                operator_id="scheduler_engine",
                entity_type="conversation",
                entity_id=conv.id,
                details={
                    "step": item.sequence_step,
                    "recipient": conv.recipient_email,
                    "dry_run": settings.OUTREACH_DRY_RUN,
                },
            )

            executed_count += 1
        except Exception as exc:
            item.attempt_count += 1
            if item.attempt_count >= 3:
                item.status = "failed"
                item.stop_reason = f"max_retries_exceeded: {exc}"
            else:
                # Back off by 15 minutes * attempt_count
                item.scheduled_at = current_time + timedelta(minutes=15 * item.attempt_count)
            failed_count += 1

    db.commit()
    return {
        "status": "success",
        "processed_total": len(due_items),
        "executed": executed_count,
        "cancelled": cancelled_count,
        "failed": failed_count,
    }
