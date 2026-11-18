from __future__ import annotations

import csv
import io
import re
from typing import Any, Callable
from urllib.parse import urlparse
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Business,
    Campaign,
    CampaignLeftoverLead,
    DimensionScore,
    Lead,
    MessageDraft,
    OutboundMessage,
    utc_now,
)
from app.services.email_dispatcher import dispatch_single_email
from app.services.mailbox_pool import get_next_available_mailbox, load_mailbox_pool


def get_root_domain(url: str | None) -> str | None:
    if not url:
        return None
    clean = url.strip()
    if not clean.startswith(("http://", "https://")):
        clean = "https://" + clean
    try:
        netloc = urlparse(clean).netloc.lower().split(":")[0]
        parts = [p for p in netloc.split(".") if p]
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return netloc if netloc else None
    except Exception:
        return None


def is_business_duplicate(
    db: Session,
    campaign_id: uuid.UUID,
    *,
    place_id: str | None = None,
    website: str | None = None,
    email: str | None = None,
) -> bool:
    """
    Triple-layer deduplication guarantee:
    1. place_id: Checks if physical location already processed in this campaign.
    2. root domain: Checks if normalized domain already exists in this campaign.
    3. email: Checks if email address has already been contacted in outbound history.
    """
    # Layer 1: Google Maps place_id
    if place_id and place_id.strip():
        existing_place = (
            db.query(Lead)
            .join(Business, Lead.business_id == Business.id)
            .filter(Lead.campaign_id == campaign_id, Business.place_id == place_id.strip())
            .first()
        )
        if existing_place:
            return True

    # Layer 2: Normalized root domain
    target_domain = get_root_domain(website)
    if target_domain:
        # Check in current campaign
        campaign_leads = (
            db.query(Business.website)
            .join(Lead, Lead.business_id == Business.id)
            .filter(Lead.campaign_id == campaign_id, Business.website.isnot(None))
            .all()
        )
        for (biz_web,) in campaign_leads:
            if get_root_domain(biz_web) == target_domain:
                return True

        # Check in global outbound dispatches (never double-contact same domain across campaigns)
        past_sent_domains = (
            db.query(Business.website)
            .join(Lead, Lead.business_id == Business.id)
            .join(OutboundMessage, OutboundMessage.lead_id == Lead.id)
            .filter(
                Business.website.isnot(None),
                OutboundMessage.status.in_(["sent", "simulated"]),
            )
            .all()
        )
        for (past_web,) in past_sent_domains:
            if get_root_domain(past_web) == target_domain:
                return True

    # Layer 3: Email uniqueness
    if email and email.strip():
        clean_email = email.strip().lower()
        # Check in current campaign
        existing_email_lead = (
            db.query(Lead)
            .join(Business, Lead.business_id == Business.id)
            .filter(
                Lead.campaign_id == campaign_id,
                func.lower(Business.email) == clean_email,
            )
            .first()
        )
        if existing_email_lead:
            return True

        # Check in global outbound dispatches (never double-contact across campaigns)
        already_dispatched = (
            db.query(OutboundMessage)
            .filter(
                func.lower(OutboundMessage.recipient_email) == clean_email,
                OutboundMessage.status.in_(["sent", "simulated"]),
            )
            .first()
        )
        if already_dispatched:
            return True

    # Layer 4: Cross-campaign place_id check for successfully emailed businesses
    if place_id and place_id.strip():
        past_sent_place = (
            db.query(OutboundMessage)
            .join(Lead, OutboundMessage.lead_id == Lead.id)
            .join(Business, Lead.business_id == Business.id)
            .filter(
                Business.place_id == place_id.strip(),
                OutboundMessage.status.in_(["sent", "simulated"]),
            )
            .first()
        )
        if past_sent_place:
            return True

    return False


def check_existing_leftover_leads(
    db: Session,
    niche: str,
    location: str,
    min_score: int = 0,
) -> list[CampaignLeftoverLead]:
    """
    Finds unconsumed qualified leftover leads from previous campaigns matching configuration.
    Also auto-sweeps uncontacted leads from matching past campaigns that were not finalized.
    """
    niche_clean = niche.strip().lower()
    loc_clean = location.strip().lower()

    # Auto-sweep past campaigns with matching niche & location to ensure uncontacted leads are preserved
    past_campaigns = (
        db.query(Campaign)
        .filter(
            func.lower(Campaign.niche) == niche_clean,
            func.lower(Campaign.location) == loc_clean,
        )
        .all()
    )
    for past_camp in past_campaigns:
        record_campaign_leftovers(db, past_camp.id, min_score=0)
    db.flush()

    query = (
        db.query(CampaignLeftoverLead)
        .filter(
            CampaignLeftoverLead.is_consumed == False,
            func.lower(CampaignLeftoverLead.niche) == niche_clean,
            func.lower(CampaignLeftoverLead.location) == loc_clean,
        )
    )
    if min_score > 0:
        query = query.filter(CampaignLeftoverLead.overall_score >= min_score)

    return query.order_by(CampaignLeftoverLead.overall_score.desc()).all()


def consume_leftover_leads(
    db: Session,
    campaign_id: uuid.UUID,
    leftovers: list[CampaignLeftoverLead],
) -> int:
    """
    Attaches rollover leads into the new campaign's Sub-Campaign 1.
    """
    camp = db.get(Campaign, campaign_id)
    use_best_template = camp.filters.get("use_best_response_template", False) if (camp and isinstance(camp.filters, dict)) else False

    count = 0
    for item in leftovers:
        # Check if lead already in campaign
        exists = (
            db.query(Lead)
            .filter_by(campaign_id=campaign_id, business_id=item.business_id)
            .first()
        )
        if not exists:
            new_lead = Lead(
                campaign_id=campaign_id,
                business_id=item.business_id,
                overall_score=item.overall_score,
                priority="A" if item.overall_score >= 80 else ("B" if item.overall_score >= 60 else "C"),
                confidence="high",
                outreach_status="draft",
                crm_stage="qualified",
            )
            db.add(new_lead)
            db.flush()

            biz = db.get(Business, item.business_id)
            raw_name = (biz.name or "").strip() if biz else "there"
            target_name = raw_name
            for sep in (" - ", " | ", " — ", " – ", " : "):
                if sep in target_name:
                    target_name = target_name.split(sep)[0].strip()
            target_name = target_name or "there"

            if use_best_template:
                template_body = (
                    f"Hey {target_name}, tried to reach you a few times but didn't hear back . . .\n\n\n"
                    f"Where should we go from here?"
                )
                db.add(
                    MessageDraft(
                        lead_id=new_lead.id,
                        channel="preview",
                        status="preview",
                        body=template_body,
                        not_recommended_reason=None,
                        evidence_ids=[],
                    )
                )
                db.flush()
            elif item.lead_id:
                old_draft = db.query(MessageDraft).filter_by(lead_id=item.lead_id).first()
                if old_draft:
                    db.add(
                        MessageDraft(
                            lead_id=new_lead.id,
                            channel="preview",
                            status=old_draft.status,
                            body=old_draft.body,
                            not_recommended_reason=old_draft.not_recommended_reason,
                            evidence_ids=old_draft.evidence_ids,
                        )
                    )
                    db.flush()
            count += 1
        item.is_consumed = True
        item.consumed_by_campaign_id = campaign_id
    db.flush()
    return count


def record_campaign_leftovers(
    db: Session,
    campaign_id: uuid.UUID,
    min_score: int = 0,
) -> int:
    """
    Saves uncontacted qualified leads into CampaignLeftoverLead when a campaign completes.
    Strictly targets leads in draft/approved status that were never checked or attempted for email sending.
    """
    camp = db.get(Campaign, campaign_id)
    if not camp:
        return 0

    query = (
        db.query(Lead)
        .join(Business, Lead.business_id == Business.id)
        .filter(
            Lead.campaign_id == campaign_id,
            Lead.outreach_status.in_(["draft", "approved"]),
            Business.email.isnot(None),
            Business.email != "",
        )
    )
    if min_score > 0:
        query = query.filter(Lead.overall_score >= min_score)

    uncontacted = query.all()
    saved = 0
    for lead in uncontacted:
        already_saved = (
            db.query(CampaignLeftoverLead)
            .filter_by(campaign_id=campaign_id, lead_id=lead.id)
            .first()
        )
        if not already_saved:
            # Check if business or email was dispatched in any outbound message
            is_dispatched = (
                db.query(OutboundMessage)
                .join(Lead, OutboundMessage.lead_id == Lead.id)
                .filter(
                    Lead.business_id == lead.business_id,
                    OutboundMessage.status.in_(["sent", "simulated"]),
                )
                .first()
            )
            if is_dispatched:
                continue

            record = CampaignLeftoverLead(
                campaign_id=campaign_id,
                business_id=lead.business_id,
                lead_id=lead.id,
                niche=camp.niche,
                location=camp.location,
                overall_score=lead.overall_score,
                is_consumed=False,
            )
            db.add(record)
            saved += 1
    db.flush()
    return saved


def dispatch_subcampaign_batch(
    db: Session,
    campaign_id: uuid.UUID,
    max_to_send: int,
    settings: Settings,
    *,
    lead_ids: list[uuid.UUID] | None = None,
    agency_name: str | None = None,
    sender_name: str | None = None,
    resolver_fn: Callable[[str], list[str]] | None = None,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> dict[str, Any]:
    """
    Sends outreach serially down the qualified queue until max_to_send is hit.
    Stops precisely at the limit. Unsent leads remain in draft state.
    """
    camp = db.get(Campaign, campaign_id)
    if not camp:
        raise ValueError(f"Campaign {campaign_id} not found")

    query = (
        db.query(Lead, Business)
        .join(Business, Lead.business_id == Business.id)
        .filter(Lead.campaign_id == campaign_id)
        .filter(Lead.outreach_status == "approved")
        .filter(Business.email.isnot(None))
        .filter(Business.email != "")
    )
    if lead_ids:
        query = query.filter(Lead.id.in_(lead_ids))

    query = query.order_by(Lead.overall_score.desc())
    candidates = query.all()

    summary: dict[str, Any] = {
        "total_candidates": len(candidates),
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

    for idx, (lead, biz) in enumerate(candidates, 1):
        if summary["sent"] + summary["simulated"] >= max_to_send:
            # Reached exact target sent count! Stop immediately.
            break

        mailbox, next_idx = get_next_available_mailbox(pool, db, current_mailbox_idx)
        if mailbox is None:
            lead.outreach_status = "throttled"
            summary["throttled"] += 1
            summary["records"].append({
                "lead_id": str(lead.id),
                "business_name": biz.name,
                "recipient_email": (biz.email or "").strip(),
                "sender_mailbox": "none_available",
                "status": "throttled",
                "error": "All mailboxes have hit daily quota",
            })
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

        summary["records"].append({
            "lead_id": str(lead.id),
            "business_name": biz.name,
            "recipient_email": msg.recipient_email,
            "sender_mailbox": msg.sender_email,
            "status": msg.status,
            "error": msg.error_message,
        })

        if progress_callback and (idx % 15 == 0 or idx == len(candidates)):
            try:
                progress_callback(idx, len(candidates), summary["sent"] + summary["simulated"])
            except Exception:
                pass

    # Update master campaign stats
    new_sends = summary["sent"] + summary["simulated"]
    camp.total_sent_emails += new_sends
    db.commit()

    return summary


# ==========================================
# The 3 Deliverable CSV Generators
# ==========================================

def generate_total_volume_csv(db: Session, campaign_id: uuid.UUID) -> str:
    """
    CSV 1: Total volume of campaign.csv
    Every single lead ATTEMPTED for email sending across all sub-campaign loops
    (including those that failed security/deliverability checks like bounced, suppressed, throttled, failed).
    Strictly EXCLUDES remaining leads that were never checked or attempted!
    """
    camp = db.get(Campaign, campaign_id)
    niche = camp.niche if camp else "Campaign"

    leads = (
        db.query(Lead, Business)
        .join(Business, Lead.business_id == Business.id)
        .filter(
            Lead.campaign_id == campaign_id,
            Lead.outreach_status.in_(["sent", "simulated", "bounced", "suppressed", "throttled", "failed"]),
        )
        .order_by(Lead.overall_score.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "rank",
        "name",
        "location",
        "overall_score",
        "rating",
        "review_count",
        "priority",
        "recommended_service",
        "website",
        "phone",
        "email",
        "address",
        "outreach_status",
    ])

    for rank, (lead, biz) in enumerate(leads, start=1):
        writer.writerow([
            rank,
            biz.name,
            biz.locality or biz.address or "",
            lead.overall_score,
            f"{biz.rating:.1f}" if biz.rating is not None else "N/A",
            biz.review_count if biz.review_count is not None else "N/A",
            lead.priority,
            lead.recommended_service or "",
            biz.website or "",
            biz.phone or "",
            biz.email or "",
            biz.address or "",
            lead.outreach_status,
        ])

    return output.getvalue()


def generate_gmail_success_csv(db: Session, campaign_id: uuid.UUID) -> str:
    """
    CSV 2: Final campaign gmail success.csv
    Strictly the leads that received an outreach message (status in sent/simulated).
    """
    records = (
        db.query(OutboundMessage, Business, Lead)
        .join(Lead, OutboundMessage.lead_id == Lead.id)
        .join(Business, Lead.business_id == Business.id)
        .filter(
            OutboundMessage.campaign_id == campaign_id,
            OutboundMessage.status.in_(["sent", "simulated"]),
        )
        .order_by(OutboundMessage.dispatched_at.asc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "index",
        "business_name",
        "recipient_email",
        "sender_mailbox",
        "subject",
        "status",
        "dispatched_at",
        "lead_score",
        "website",
        "phone",
        "address",
    ])

    for idx, (msg, biz, lead) in enumerate(records, start=1):
        disp_time = msg.dispatched_at.strftime("%Y-%m-%d %H:%M:%S UTC") if msg.dispatched_at else "Simulated"
        writer.writerow([
            idx,
            biz.name,
            msg.recipient_email,
            msg.sender_email,
            msg.subject,
            msg.status.upper(),
            disp_time,
            lead.overall_score,
            biz.website or "",
            biz.phone or "",
            biz.address or "",
        ])

    return output.getvalue()


def generate_remaining_leads_csv(db: Session, campaign_id: uuid.UUID, min_score: int = 0) -> str:
    """
    CSV 3: Remaining leads.csv
    Qualified leads (Score >= min_score) that were NOT checked or attempted for email.
    """
    query = (
        db.query(Lead, Business)
        .join(Business, Lead.business_id == Business.id)
        .filter(
            Lead.campaign_id == campaign_id,
            Lead.outreach_status.in_(["draft", "approved"]),
            Business.email.isnot(None),
            Business.email != "",
        )
    )
    if min_score > 0:
        query = query.filter(Lead.overall_score >= min_score)

    leads = query.order_by(Lead.overall_score.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "index",
        "business_name",
        "location",
        "overall_score",
        "rating",
        "review_count",
        "recommended_service",
        "website",
        "phone",
        "email",
        "address",
        "status",
    ])

    for idx, (lead, biz) in enumerate(leads, start=1):
        writer.writerow([
            idx,
            biz.name,
            biz.locality or biz.address or "",
            lead.overall_score,
            f"{biz.rating:.1f}" if biz.rating is not None else "N/A",
            biz.review_count if biz.review_count is not None else "N/A",
            lead.recommended_service or "",
            biz.website or "",
            biz.phone or "",
            biz.email or "",
            biz.address or "",
            lead.outreach_status,
        ])

    return output.getvalue()
