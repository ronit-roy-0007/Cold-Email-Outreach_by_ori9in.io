from __future__ import annotations

import csv
import io
from pathlib import Path
import re
from typing import Any
import uuid

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Approval,
    AuditLog,
    Business,
    Campaign,
    CampaignLeftoverLead,
    DimensionScore,
    Evidence,
    Lead,
    MailboxAccount,
    MessageDraft,
    OperatorProfile,
)
from app.services.campaigns import create_campaign
from app.services.pipeline import run_campaign
from app.services.gemini_personalizer import generate_gemini_pitch
from app.services.social import get_business_social_links, get_lead_messages, sanitize_website
from app.services.email_dispatcher import dispatch_approved_campaign_leads
from app.services.geo_expansion import get_nearby_regions, get_next_expansion_location
from app.services.sub_campaign_service import (
    check_existing_leftover_leads,
    consume_leftover_leads,
    dispatch_subcampaign_batch,
    generate_gmail_success_csv,
    generate_remaining_leads_csv,
    generate_total_volume_csv,
    record_campaign_leftovers,
)
from app.services.mailbox_pool import (
    add_mailbox_account,
    format_app_password,
    get_pool_status,
    parse_addmailbox_args,
    remove_mailbox_account,
    verify_gmail_credentials,
)


def format_approval_card(
    lead: Lead,
    biz: Business,
    draft: MessageDraft | None,
    evidence: list[Evidence],
    is_review_mode: bool = False,
    remaining_count: int | None = None,
) -> tuple[str, list[list[dict[str, str]]]]:
    rec_svc = (lead.recommended_service or "lead_management_followup").replace("_", " ")

    verified_gaps = [
        e.claim
        for e in evidence
        if e.evidence_type in ("verified_observation", "explicit_intent")
    ]
    gaps_text = "\n".join(f"• {g}" for g in verified_gaps[:3]) if verified_gaps else "• Digital outreach & lead management gap identified"

    source_fields = biz.source_fields if isinstance(biz.source_fields, dict) else {}
    reviews = source_fields.get("reviews") or []
    review_excerpt = f"\n💬 *Customer Feedback:* \"{reviews[0]}\"" if reviews else ""

    rating_display = f"{biz.rating:.1f}★" if biz.rating is not None else "N/A"
    reviews_count_display = f"({biz.review_count} reviews)" if biz.review_count is not None else ""

    reason = draft.not_recommended_reason if (draft and draft.not_recommended_reason) else "criteria not met"
    draft_text = draft.body if (draft and draft.body) else f"(Draft not recommended: {reason})"
    rem_hdr = f" (Remaining: {remaining_count})" if remaining_count is not None else ""
    clean_site = sanitize_website(biz.name, biz.website)
    socials = get_business_social_links(biz)

    social_pills = []
    if socials.get("telegram"):
        social_pills.append(f"[Telegram]({socials['telegram']})")
    if socials.get("linkedin"):
        social_pills.append(f"[LinkedIn]({socials['linkedin']})")
    if socials.get("instagram"):
        social_pills.append(f"[Instagram]({socials['instagram']})")
    if socials.get("facebook"):
        social_pills.append(f"[Facebook]({socials['facebook']})")
    if socials.get("twitter"):
        social_pills.append(f"[X/Twitter]({socials['twitter']})")
    if socials.get("reddit"):
        social_pills.append(f"[Reddit]({socials['reddit']})")

    socials_display = f"\n📱 Socials: {' • '.join(social_pills)}" if social_pills else ""

    card_text = (
        f"🎯 *LEAD APPROVAL CARD (DRY-RUN)*{rem_hdr}\n\n"
        f"🏢 *{biz.name}*\n"
        f"📍 Location: {biz.locality or biz.address or 'Local Area'}\n"
        f"🌐 Website: {clean_site or 'No website listed'}\n"
        f"⭐ Rating: *{rating_display}* {reviews_count_display}\n"
        f"📞 Phone: `{biz.phone or 'N/A'}` | ✉️ `{biz.email or 'N/A'}`"
        f"{socials_display}\n\n"
        f"⭐ *Priority {lead.priority}* — Score: *{lead.overall_score}/100* ({lead.confidence} confidence)\n"
        f"💼 *Recommended Service:* {rec_svc}\n\n"
        f"🔍 *Key Verified Evidence:*\n{gaps_text}{review_excerpt}\n\n"
        f"📝 *Outreach Draft Preview:*\n```\n{draft_text}\n```\n\n"
        f"⚠️ _Outreach is in dry-run mode. Approving marks the lead as approved in CRM without live sending._"
    )

    prefix = "review_" if is_review_mode else ""
    buttons = [
        [
            {"text": "✅ Approve & Next" if is_review_mode else "✅ Approve", "callback_data": f"{prefix}approve:{lead.id}"},
            {"text": "⏭️ Skip", "callback_data": f"{prefix}skip:{lead.id}"},
        ],
        [
            {"text": "🔄 AI Regenerate", "callback_data": f"{prefix}regen:{lead.id}"},
            {"text": "❌ Reject", "callback_data": f"{prefix}reject:{lead.id}"},
        ],
    ]

    if socials.get("telegram"):
        buttons.append([
            {"text": "💬 Open Telegram Chat", "url": socials["telegram"]},
        ])

    if is_review_mode:
        buttons.append([
            {"text": "🚪 Exit Review", "callback_data": f"review_exit:{lead.campaign_id}"},
        ])

    return card_text, buttons


def approve_entire_campaign(
    db: Session,
    campaign_id: uuid.UUID,
    user_id: str,
    min_score: int = 80,
) -> dict[str, Any]:
    camp = db.get(Campaign, campaign_id)
    if not camp:
        return {"status": "error", "message": f"Campaign {campaign_id} not found."}

    leads = (
        db.query(Lead)
        .filter(Lead.campaign_id == campaign_id, Lead.overall_score >= min_score)
        .all()
    )

    approved_count = 0
    for lead in leads:
        if lead.outreach_status != "approved":
            lead.outreach_status = "approved"
            lead.crm_stage = "approved"
            ai_draft = db.query(MessageDraft).filter_by(lead_id=lead.id, channel="ai_regenerated").first()
            if ai_draft:
                ai_draft.status = "approved"
            else:
                init_draft = db.query(MessageDraft).filter_by(lead_id=lead.id).first()
                if init_draft:
                    init_draft.status = "approved"

            approval_entry = Approval(
                lead_id=lead.id,
                user_id=user_id,
                action="approved",
            )
            db.add(approval_entry)
            approved_count += 1

    if approved_count > 0:
        audit_entry = AuditLog(
            action="campaign_batch_approved",
            entity_type="campaign",
            entity_id=campaign_id,
            payload={"user_id": user_id, "approved_count": approved_count, "min_score": min_score},
        )
        db.add(audit_entry)
        db.flush()

    return {
        "status": "success",
        "approved_count": approved_count,
        "total_matching": len(leads),
        "campaign_niche": camp.niche,
        "campaign_location": camp.location,
        "message": f"🚀 Successfully approved *{approved_count} qualified leads* (Score ≥ {min_score}) for *{camp.niche}* ({camp.location})! Ready for outreach.",
    }


def get_next_pending_lead(
    db: Session,
    campaign_id: uuid.UUID | None = None,
    min_score: int = 80,
) -> tuple[Lead | None, int]:
    query = db.query(Lead).filter(Lead.overall_score >= min_score, Lead.outreach_status == "draft")
    if campaign_id:
        query = query.filter(Lead.campaign_id == campaign_id)
    else:
        latest_camp = db.query(Campaign).order_by(Campaign.created_at.desc()).first()
        if latest_camp:
            query = query.filter(Lead.campaign_id == latest_camp.id)

    total_pending = query.count()
    lead = query.order_by(Lead.overall_score.desc()).first()
    return lead, total_pending


def generate_campaign_csv(
    db: Session,
    campaign_id: uuid.UUID,
    min_score: int = 0,
    limit: int = 0,
    only_unattempted: bool = False,
) -> str:
    query = (
        db.query(Lead, Business)
        .join(Business, Lead.business_id == Business.id)
        .filter(Lead.campaign_id == campaign_id)
    )
    if min_score > 0:
        query = query.filter(Lead.overall_score >= min_score)
    if only_unattempted:
        query = query.filter(Lead.outreach_status.in_(["draft", "approved"]))

    query = query.order_by(Lead.overall_score.desc())
    if limit > 0:
        query = query.limit(limit)

    leads = query.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "rank",
        "name",
        "location",
        "overall_score",
        "rating",
        "review_count",
        "benchmark_met",
        "priority",
        "confidence",
        "recommended_service",
        "discovery_source",
        "reason_codes",
        "website",
        "phone",
        "email",
        "address",
        "linkedin",
        "facebook",
        "instagram",
        "twitter",
        "reddit",
        "telegram",
        "drafts",
        "approved_messages",
        "outreach_status",
    ])

    for rank, (lead, biz) in enumerate(leads, start=1):
        dims = db.query(DimensionScore).filter_by(lead_id=lead.id).all()
        reason_codes = "; ".join(f"{d.dimension}:{d.reason_code}" for d in dims)
        clean_site = sanitize_website(biz.name, biz.website)
        socials = get_business_social_links(biz)
        draft_msg, approved_msg = get_lead_messages(db, lead)

        writer.writerow([
            rank,
            biz.name,
            biz.locality or biz.address or "",
            lead.overall_score,
            f"{biz.rating:.1f}" if biz.rating is not None else "N/A",
            biz.review_count if biz.review_count is not None else "N/A",
            f"Yes (>={min_score})" if min_score > 0 else "All",
            lead.priority,
            lead.confidence,
            lead.recommended_service or "",
            "google_maps" if biz.discovery_source in ("live", "google_maps", "mock") else biz.discovery_source,
            reason_codes,
            clean_site,
            biz.phone or "",
            biz.email or "",
            biz.address or "",
            socials.get("linkedin", ""),
            socials.get("facebook", ""),
            socials.get("instagram", ""),
            socials.get("twitter", ""),
            socials.get("reddit", ""),
            socials.get("telegram", ""),
            draft_msg,
            approved_msg,
            lead.outreach_status,
        ])

    return output.getvalue()


def deliver_campaign_final_csvs(
    db: Session,
    camp: Campaign,
    settings: Settings,
    user_id: int | str | None,
    bench_score: int = 0,
) -> tuple[str, dict[str, str]]:
    total_csv = generate_total_volume_csv(db, camp.id)
    success_csv = generate_gmail_success_csv(db, camp.id)
    remaining_csv = generate_remaining_leads_csv(db, camp.id, min_score=bench_score)

    leftover_saved = record_campaign_leftovers(db, camp.id, min_score=bench_score)

    files = {
        "Total volume of campaign.csv": total_csv,
        "Final campaign gmail success.csv": success_csv,
        "Remaining leads.csv": remaining_csv,
    }

    if settings.TELEGRAM_BOT_TOKEN and user_id:
        send_telegram_document(
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            chat_id=user_id,
            file_bytes=total_csv.encode("utf-8"),
            filename="Total volume of campaign.csv",
            caption="📊 Deliverable 1/3: Total Volume of Campaign (All discovered & audited leads across all sub-campaign loops)",
        )
        send_telegram_document(
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            chat_id=user_id,
            file_bytes=success_csv.encode("utf-8"),
            filename="Final campaign gmail success.csv",
            caption="🎯 Deliverable 2/3: Final Campaign Gmail Success (Strictly the prospects who received outreach emails)",
        )
        send_telegram_document(
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            chat_id=user_id,
            file_bytes=remaining_csv.encode("utf-8"),
            filename="Remaining leads.csv",
            caption=f"📁 Deliverable 3/3: Remaining Leads ({leftover_saved} qualified leads saved for your next campaign rollover)",
        )

    completion_text = (
        f"🏁 *Campaign Finished!*\n\n"
        f"• Target Niche: *{camp.niche}*\n"
        f"• Location: *{camp.location}*\n"
        f"• Outreach Emails Delivered: *{camp.total_sent_emails} / {camp.target_sent_emails}*\n"
        f"• Sub-Campaign Rounds: *{camp.sub_campaign_index}*\n"
        f"• Remaining Qualified Leads Saved: *{leftover_saved}*\n\n"
        f"📁 *All 3 Final CSV Deliverables have been sent above:*\n"
        f"1. `Total volume of campaign.csv`\n"
        f"2. `Final campaign gmail success.csv`\n"
        f"3. `Remaining leads.csv`\n\n"
        f"💡 *Next Campaign:* Your {leftover_saved} remaining leads will automatically rollover into your next matching campaign!"
    )
    return completion_text, files


def build_expansion_prompt(
    camp: Campaign,
    current_search_loc: str,
    next_loc: str,
    qualified_count: int,
    target_count: int,
    bench_score: int,
) -> tuple[str, list[list[dict[str, str]]]]:
    remaining_sent_gap = max(0, camp.target_sent_emails - camp.total_sent_emails)
    gap = remaining_sent_gap if camp.target_sent_emails > 0 else max(0, target_count - qualified_count)
    prompt = (
        f"⚠️ *Primary Location Exhausted: {current_search_loc}*\n\n"
        f"📊 *Campaign Outreach Progress:*\n"
        f"• Emails Sent: *{camp.total_sent_emails} / {camp.target_sent_emails}* ({remaining_sent_gap} remaining to reach target)\n"
        f"• Uncontacted Leads in Current Pool: *{qualified_count}*\n"
        f"• Benchmark Filter: *Score ≥ {bench_score}*\n"
        f"• Status: All unique {camp.niche} in *{current_search_loc}* meeting Score ≥ {bench_score} have been audited.\n\n"
        f"📍 *Would you like to expand search radius to {next_loc} (nearby region centered on {camp.location}) to find the remaining {gap} leads?*\n"
        f"_(Niche and benchmark score criteria remain 100% strictly enforced)_"
    )
    row1 = [{"text": f"🌍 Expand Search to {next_loc}", "callback_data": f"expand_radius:{camp.id}"}]
    if qualified_count > 0:
        row1.append({"text": f"🚀 Proceed with {qualified_count} Leads", "callback_data": f"proceed_batch:{camp.id}"})
    buttons = [
        row1,
        [
            {"text": f"🏁 Finish Early with {camp.total_sent_emails} Sent", "callback_data": f"finish_campaign_early:{camp.id}"},
        ],
    ]
    return prompt, buttons


def send_telegram_document(
    bot_token: str,
    chat_id: str | int,
    file_bytes: bytes,
    filename: str,
    caption: str = "",
) -> bool:
    if not bot_token:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    files = {"document": (filename, file_bytes, "text/csv")}
    data = {"chat_id": str(chat_id), "caption": caption}
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, data=data, files=files)
            return resp.status_code == 200
    except Exception:
        return False


def send_telegram_text(
    bot_token: str,
    chat_id: str | int,
    text: str,
) -> bool:
    if not bot_token:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "Markdown"}
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code != 200:
                payload.pop("parse_mode", None)
                fallback_resp = client.post(url, json=payload)
                return fallback_resp.status_code == 200
            return True
    except Exception:
        return False


def record_approval(
    db: Session,
    lead_id: uuid.UUID,
    user_id: str,
    action: str,
) -> dict[str, Any]:
    lead = db.get(Lead, lead_id)
    if not lead:
        return {"status": "error", "message": f"Lead {lead_id} not found"}

    biz = db.get(Business, lead.business_id)
    biz_name = biz.name if biz else "Business"

    action_clean = action.lower().strip()
    if action_clean not in ("approve", "reject", "skip"):
        return {"status": "error", "message": f"Invalid action: {action}"}

    target_status = {
        "approve": "approved",
        "reject": "rejected",
        "skip": "skipped",
    }[action_clean]

    # Idempotency check
    if lead.outreach_status == target_status:
        return {
            "status": "already_processed",
            "message": f"Lead '{biz_name}' is already {target_status}.",
            "lead_id": str(lead.id),
        }

    lead.outreach_status = target_status
    if target_status == "approved":
        lead.crm_stage = "approved"
        ai_draft = db.query(MessageDraft).filter_by(lead_id=lead.id, channel="ai_regenerated").first()
        if ai_draft:
            ai_draft.status = "approved"
        else:
            init_draft = db.query(MessageDraft).filter_by(lead_id=lead.id).first()
            if init_draft:
                init_draft.status = "approved"

    approval_entry = Approval(
        lead_id=lead.id,
        user_id=user_id,
        action=target_status,
    )
    db.add(approval_entry)

    audit_entry = AuditLog(
        action=f"lead_{target_status}",
        entity_type="lead",
        entity_id=lead.id,
        payload={"user_id": user_id, "action": target_status},
    )
    db.add(audit_entry)
    db.flush()

    return {
        "status": "success",
        "message": f"Lead '{biz_name}' successfully {target_status} by operator {user_id}.",
        "lead_id": str(lead.id),
        "outreach_status": target_status,
    }


ALL_SERVICES = [
    "website_development",
    "website_redesign",
    "real_estate_listing_portal",
    "ai_chatbot",
    "business_process_automation",
    "lead_management_followup",
    "crm_appointment_automation",
]


# In-memory wizard sessions for multi-step interactive setup
_USER_WIZARD_SESSIONS: dict[str, dict[str, Any]] = {}
_USER_ONBOARDING_SESSIONS: dict[str, dict[str, Any]] = {}
_USER_SETTINGS_SESSIONS: set[str] = set()
_USER_AWAITING_MAILBOX_INPUT: set[str] = set()
_USER_EDIT_PROFILE_SESSIONS: dict[str, str] = {}


def format_settings_dashboard(
    db: Session,
    settings: Settings,
    user_key: str,
    sender_name: str,
    agency_name: str,
) -> tuple[str, list[list[dict[str, str]]]]:
    prof = db.get(OperatorProfile, user_key) if user_key else None
    disp_name = prof.sender_name if prof and prof.sender_name else sender_name
    disp_agency = prof.agency_name if prof and prof.agency_name else agency_name

    statuses = get_pool_status(db, settings)

    lines = [
        "⚙️ *System Settings & Mailbox Management*\n",
        "👤 *Operator Profile:*",
        f"• Sender Name: *{disp_name}*",
        f"• Business / Agency: *{disp_agency}*",
        "_(Send `/profile` or tap button below to update)_\n",
    ]

    buttons: list[list[dict[str, str]]] = []

    if not statuses:
        lines.append("📬 *Connected Sending Mailboxes:* None registered yet.\n")
        lines.append("➕ *How to Add a Mailbox:*")
        lines.append("Send: `/addemailaddress <email> <16-letter_password>`")
        lines.append("Example: `/addemailaddress outreach@gmail.com abcd efgh ijkl mnop`\n")
        lines.append("🔑 *Google App Password:*")
        lines.append("1. Turn ON 2-Step Verification at myaccount.google.com/security")
        lines.append("2. Generate 16 letters at myaccount.google.com/apppasswords")
    else:
        lines.append(f"📬 *Connected Mailbox Pool ({len(statuses)} Inboxes):*")
        total_remaining = 0
        for i, s in enumerate(statuses, 1):
            total_remaining += s.get("remaining_today", 0)
            status_icon = "🟢" if s.get("is_active") else "🔴"
            pw_raw = s.get("password") or ""
            pw_disp = format_app_password(pw_raw) if pw_raw else "•••• •••• •••• ••••"
            lines.append(
                f"{i}. {status_icon} *{s['email']}*\n"
                f"   • Password: `{pw_disp}`\n"
                f"   • Sent Today: *{s['sent_today']}/{s['daily_limit']}* (Remaining: {s['remaining_today']})\n"
                f"   • Sender: *{s.get('sender_name', disp_name)}*"
            )

        lines.append(f"\n🚀 *Total Remaining Capacity Today:* **{total_remaining} emails**\n")
        lines.append("🛠️ *Actions:*")
        lines.append("• Add: `/addemailaddress <email> <app_password>`")
        lines.append("• Delete: `/deleteemail <email>` (or tap Delete below)")

    # Action buttons
    buttons.append([
        {"text": "➕ Add New Gmail", "callback_data": "settings_add_email"},
        {"text": "✏️ Edit Profile", "callback_data": "open_profile"},
    ])

    for s in statuses:
        buttons.append([
            {"text": f"🗑️ Delete {s['email']}", "callback_data": f"del_mailbox:{s['email']}"}
        ])

    buttons.append([
        {"text": "🔄 Refresh", "callback_data": "open_settings"},
    ])

    return "\n".join(lines), buttons


def format_profile_card(
    db: Session,
    user_key: str,
    default_name: str,
    default_agency: str,
) -> tuple[str, list[list[dict[str, str]]]]:
    prof = db.get(OperatorProfile, user_key) if user_key else None
    disp_name = prof.sender_name if prof and prof.sender_name else default_name
    disp_agency = prof.agency_name if prof and prof.agency_name else default_agency

    text = (
        f"👤 *Operator Profile*\n\n"
        f"• Sender Name: *{disp_name}*\n"
        f"• Business / Agency: *{disp_agency}*\n"
        f"• Telegram User ID: `{user_key}`\n\n"
        f"✏️ *To update your details:*\n"
        f"• Send `/setname <Your Name>` (e.g. `/setname Alex`)\n"
        f"• Send `/setagency <Your Business Name>` (e.g. `/setagency Apex Digital`)\n\n"
        f"Or tap a quick button below to update:"
    )
    buttons = [
        [
            {"text": "✏️ Change Name", "callback_data": "edit_profile:name"},
            {"text": "🏢 Change Business", "callback_data": "edit_profile:agency"},
        ],
        [
            {"text": "⚙️ Open Settings", "callback_data": "open_settings"},
        ],
    ]
    return text, buttons


def format_commands_menu(prof_name: str, prof_agency: str) -> str:
    return (
        f"🤖 *IntentLead AI Operator Hub*\n"
        f"👤 *Operator:* *{prof_name}* ({prof_agency})\n\n"
        f"Here are all your commands — simple and ready to use:\n\n"
        f"🎯 `/findleads` — Start finding clients! Search any business type in any city\n"
        f"🔍 `/review` — Review leads one by one and read their custom AI email pitches\n"
        f"⚡ `/approve_campaign` — Approve all top-scoring leads in one quick click\n"
        f"🚀 `/dispatch` — Send cold emails to all your approved leads\n"
        f"📥 `/export_csv` — Download your leads as a spreadsheet (with emails, phones & addresses)\n"
        f"⚙️ `/settings` — Connect or remove your sending Gmail accounts and view quotas\n"
        f"🚀 `/live` / `/dryrun` — Toggle between LIVE sending and simulation mode (check with `/mode`)\n"
        f"👤 `/profile` — View or update your sender name and business name\n"
        f"📊 `/status` — See the status and lead count of your recent searches\n"
        f"🧹 `/clean_memory` — Reset all data and restart the bot fresh from the beginning\n"
        f"❌ `/cancel` — Stop or reset your current question"
    )


def get_operator_profile(db: Session, user_id: str | int | None, settings: Settings) -> tuple[str, str]:
    """
    Returns (sender_name, agency_name) for the operator.
    Prioritizes the saved OperatorProfile in the database;
    falls back to Settings.
    """
    if user_id:
        prof = db.get(OperatorProfile, str(user_id))
        if prof and prof.sender_name and prof.agency_name:
            return prof.sender_name.strip(), prof.agency_name.strip()
    return (settings.AGENCY_SENDER_NAME or "Roy").strip(), (settings.AGENCY_NAME or "ori9in.io").strip()


def has_operator_profile(db: Session, user_id: str | int | None) -> bool:
    """
    Checks if an OperatorProfile with both sender_name and agency_name
    already exists in the database for the given user_id.
    """
    if not user_id:
        return False
    prof = db.get(OperatorProfile, str(user_id))
    return bool(prof and prof.sender_name and prof.agency_name)


def map_service_keywords(services_str: str) -> list[str]:
    if not services_str.strip():
        return list(ALL_SERVICES)
    selected = set()
    s = services_str.lower()
    if any(k in s for k in ("chat", "ai", "bot", "assistant")):
        selected.add("ai_chatbot")
    if any(k in s for k in ("crm", "book", "appoint", "calendar", "schedul")):
        selected.add("crm_appointment_automation")
    if any(k in s for k in ("follow", "lead", "capture", "handling", "ad", "marketing")):
        selected.add("lead_management_followup")
    if any(k in s for k in ("process", "work", "flow", "auto", "system")):
        selected.add("business_process_automation")
    if any(k in s for k in ("portal", "list", "propert", "estate")):
        selected.add("real_estate_listing_portal")
    if any(k in s for k in ("redesign", "mobile", "responsiv", "speed")):
        selected.add("website_redesign")
    if any(k in s for k in ("web", "site", "dev", "provid", "page")):
        selected.add("website_development")
    return list(selected) if selected else list(ALL_SERVICES)


def _execute_wizard_campaign(
    db: Session,
    settings: Settings,
    user_id: int | str | None,
    user_key: str,
    session_data: dict[str, Any],
    use_best_response_template: bool,
    agency_name: str,
    sender_name: str,
) -> dict[str, Any]:
    niche = session_data.get("niche", "Real Estate")
    location = session_data.get("location", "Dallas, Texas")
    services_desc = session_data.get("services", "")
    qty = session_data.get("quantity", 50)
    bench_score = session_data.get("benchmark", 80)

    _USER_WIZARD_SESSIONS.pop(user_key, None)
    target_services = map_service_keywords(services_desc)

    payload = {
        "niche": niche,
        "location": location,
        "requested_quantity": qty,
        "max_limit": 100,
        "target_services": target_services,
        "filters": {
            "min_score": bench_score,
            "services_desc": services_desc,
            "use_best_response_template": use_best_response_template,
        },
        "provider": settings.DISCOVERY_PROVIDER,
    }

    template_note = "🎯 *Template Mode:* Best-Response Outreach Message\n" if use_best_response_template else ""

    # Send immediate acknowledgement to user
    if settings.TELEGRAM_BOT_TOKEN and user_id:
        send_telegram_text(
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            chat_id=user_id,
            text=(
                f"⏳ *Campaign Queued & Processing!*\n\n"
                f"• Target Niche: *{niche}*\n"
                f"• Location: *{location}*\n"
                f"• Benchmark Filter: *Score ≥ {bench_score}*\n"
                f"{template_note}"
                f"• Outreach Mode: *{'🟢 LIVE (Real Sending)' if not settings.OUTREACH_DRY_RUN else '🟡 DRY-RUN (Simulated)'}*\n\n"
                f"🔍 Discovering businesses and auditing websites for {agency_name} now...\n"
                f"Your scored leads and `.csv` file will be sent here shortly!"
            ),
        )

    try:
        leftovers = check_existing_leftover_leads(db, niche, location, min_score=bench_score)
        leftover_msg = ""
        consumed_count = 0
        scrape_gap = qty

        camp = create_campaign(db, payload, settings)
        camp.target_sent_emails = qty
        camp.total_sent_emails = 0
        camp.sub_campaign_index = 1
        camp.is_auto_mode = False
        db.commit()

        if leftovers:
            consumed_count = consume_leftover_leads(db, camp.id, leftovers[:qty])
            scrape_gap = max(0, qty - consumed_count)
            leftover_msg = (
                f"\n🎯 *Smart Rollover Activated!*\n"
                f"Loaded *{consumed_count}* uncontacted qualified leads from your previous {niche} campaign.\n"
                f"Remaining fresh leads to discover: *{scrape_gap}*.\n"
            )

        if scrape_gap > 0:
            run_campaign(
                db,
                camp.id,
                settings,
                agency_name=agency_name,
                sender_name=sender_name,
                target_count=qty,
            )
    except Exception as exc:
        if settings.TELEGRAM_BOT_TOKEN and user_id:
            send_telegram_text(
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                chat_id=user_id,
                text=f"⚠️ *Campaign Notice:* {exc}\nPlease check `/status` or send `/findleads` to retry.",
            )
        raise

    total_leads = db.query(Lead).filter_by(campaign_id=camp.id).count()
    matching_leads = (
        db.query(Lead)
        .filter(Lead.campaign_id == camp.id, Lead.overall_score >= bench_score)
        .count()
    )

    csv_str = generate_campaign_csv(db, camp.id, min_score=bench_score, limit=qty)
    filename = f"Sub_Campaign_1_Preview.csv"

    buttons = None
    if matching_leads > 0:
        row1 = [{"text": "🚀 Approve Batch 1", "callback_data": f"subcamp_approve:{camp.id}:1"}]
        if not use_best_response_template:
            row1.append({"text": "🔍 Review 1-by-1", "callback_data": f"start_review:{camp.id}:{bench_score}"})
        buttons = [
            row1,
            [
                {"text": "🤖 Auto Mode (Run All Next Loops)", "callback_data": f"subcamp_auto:{camp.id}:1"},
            ]
        ]
        if settings.TELEGRAM_BOT_TOKEN and user_id:
            caption = f"📄 Sub-Campaign 1 Preview: {min(matching_leads, qty)} qualified leads ready (Score ≥ {bench_score})"
            send_telegram_document(
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                chat_id=user_id,
                file_bytes=csv_str.encode("utf-8"),
                filename=filename,
                caption=caption,
            )

        review_line = "" if use_best_response_template else "• *Review 1-by-1*: Inspect each business and pitch individually\n"
        reply = (
            f"🚀 *Campaign Completed & Scored: Sub-Campaign 1 Ready!*\n\n"
            f"• Target Niche: *{niche}*\n"
            f"• Location: *{location}*\n"
            f"• Services Offered: *{services_desc or 'Full Automation Suite'}*\n"
            f"• Target Sent Emails: *{qty}*\n"
            f"• Benchmark Filter: *Score ≥ {bench_score}*\n"
            f"• Batch 1 Qualified Leads: *{matching_leads}* (out of {total_leads} audited across discovery batches){leftover_msg}\n"
            f"• Campaign ID: `{camp.id}`\n\n"
            f"📄 *Attached:* `{filename}`\n"
            f"Top *{min(matching_leads, qty)}* leads strictly ordered in descending intent score have been sent above!\n\n"
            f"👇 *Choose Outreach Mode:*\n"
            f"• *Approve Batch 1*: Sends current batch, then pauses for Sub-Campaign 2\n"
            f"{review_line}"
            f"• *Auto Mode*: Runs all subsequent sub-campaigns automatically until {qty} emails are delivered!"
        )
    elif total_leads == 0:
        reply = (
            f"⚠️ *No Businesses Found for Location: '{location}'*\n\n"
            f"• Target Niche: *{niche}*\n"
            f"• Location Searched: *{location}*\n"
            f"• Businesses Audited: *0*\n\n"
            f"Google Maps was unable to find any physical business listings for '{location}'.\n\n"
            f"💡 *Tip:* Google Maps operates on physical cities, towns, or metropolitan areas (e.g., *Delhi, Mumbai, Dallas, London, New York, California*).\n\n"
            f"👉 Please retry with `/findleads` and specify a real city or region!"
        )
    else:
        max_score = db.query(func.max(Lead.overall_score)).filter(Lead.campaign_id == camp.id).scalar() or 0
        suggested_thresh = 40 if max_score >= 40 else (30 if max_score >= 30 else max_score)
        viable_count = db.query(Lead).filter(Lead.campaign_id == camp.id, Lead.overall_score >= suggested_thresh).count()

        buttons = []
        if viable_count > 0:
            buttons.append([
                {"text": f"🎯 Qualify Top {viable_count} Leads (Score ≥ {suggested_thresh})", "callback_data": f"adjust_threshold:{camp.id}:{suggested_thresh}"}
            ])
        buttons.append([
            {"text": "🌍 Expand Search Radius to Nearby Areas", "callback_data": f"expand_radius:{camp.id}"}
        ])

        reply = (
            f"⚠️ *No Leads Met Score ≥ {bench_score}*\n\n"
            f"• Target Niche: *{niche}*\n"
            f"• Location Searched: *{location}*\n"
            f"• Businesses Audited: *{total_leads}*\n"
            f"• Highest Score Found: *{max_score}/100*\n\n"
            f"💡 *Why this happened:*\n"
            f"The {total_leads} businesses found in {location} are established with live websites, so their automation & digital gap scores average between 35 and 50. A score of {bench_score}+ is too high for this market.\n\n"
            f"👇 *Choose an option below:*\n"
            f"• Tap below to qualify the top *{viable_count}* leads (Score ≥ {suggested_thresh})\n"
            f"• Or expand search radius to nearby areas"
        )

    return {
        "status": "success",
        "reply": reply,
        "buttons": buttons,
        "filename": filename,
        "csv_content": csv_str,
        "campaign_id": str(camp.id),
        "matching_leads": matching_leads,
    }


def handle_telegram_update(
    update: dict[str, Any],
    db: Session,
    settings: Settings,
) -> dict[str, Any]:
    # Extract user ID
    user_id: int | str | None = None
    if "message" in update:
        user_id = update["message"].get("from", {}).get("id")
    elif "callback_query" in update:
        user_id = update["callback_query"].get("from", {}).get("id")

    user_key = str(user_id) if user_id is not None else ""
    sender_name, agency_name = get_operator_profile(db, user_id, settings)

    # Security check: verify allowed operator
    if settings.TELEGRAM_ALLOWED_USER_ID:
        if str(user_id) != str(settings.TELEGRAM_ALLOWED_USER_ID):
            return {
                "status": "unauthorized",
                "message": f"Access denied: Telegram User ID '{user_id}' is not authorized.",
            }

    # 1. Handle Callback Query (Button clicks)
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_data = cb.get("data", "")

        # 1A. Bulk approve entire campaign
        if cb_data.startswith("bulk_approve:"):
            parts = cb_data.split(":")
            camp_uuid = uuid.UUID(parts[1])
            score_filter = int(parts[2]) if len(parts) > 2 else 80
            res = approve_entire_campaign(db, camp_uuid, str(user_id), min_score=score_filter)
            buttons = [
                [
                    {"text": "📥 Export CSV", "callback_data": f"export_csv:{camp_uuid}"},
                    {"text": "🚀 Dispatch Outreach", "callback_data": f"dispatch_campaign:{camp_uuid}"},
                ],
            ]
            return {"status": "success", "message": res["message"], "reply": res["message"], "buttons": buttons}

        # 1B. Export CSV directly from button
        elif cb_data.startswith("export_csv:"):
            parts = cb_data.split(":")
            camp_uuid = uuid.UUID(parts[1]) if len(parts) > 1 and parts[1] else None
            camp = db.get(Campaign, camp_uuid) if camp_uuid else db.query(Campaign).order_by(Campaign.created_at.desc()).first()
            if not camp:
                return {"status": "error", "reply": "No campaign found to export."}

            csv_str = generate_campaign_csv(db, camp.id)
            filename = f"intentlead_{camp.niche.replace(' ', '_').lower()}_{camp.id}.csv"
            if settings.TELEGRAM_BOT_TOKEN and user_id:
                send_telegram_document(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=user_id,
                    file_bytes=csv_str.encode("utf-8"),
                    filename=filename,
                    caption=f"📄 Leads CSV for {camp.niche} in {camp.location} (with drafts & approved messages)",
                )
            return {
                "status": "success",
                "message": "CSV sent to chat",
                "reply": f"✅ Sent CSV document for *{camp.niche}* ({camp.location}) to chat with drafts and approved messages!",
                "filename": filename,
                "csv_content": csv_str,
            }

        # 1B.2 Dispatch outreach directly from button
        elif cb_data.startswith("dispatch_campaign:"):
            parts = cb_data.split(":")
            camp_uuid = uuid.UUID(parts[1]) if len(parts) > 1 and parts[1] else None
            camp = db.get(Campaign, camp_uuid) if camp_uuid else db.query(Campaign).order_by(Campaign.created_at.desc()).first()
            if not camp:
                return {"status": "error", "reply": "No campaign found to dispatch."}

            summary = dispatch_approved_campaign_leads(
                db=db,
                campaign_id=camp.id,
                settings=settings,
                agency_name=agency_name,
                sender_name=sender_name,
            )
            mode_label = "🟡 DRY-RUN (Simulated)" if settings.OUTREACH_DRY_RUN else "🟢 LIVE"
            reply = (
                f"📨 *Outreach Dispatch Completed!*\n\n"
                f"• Safety Mode: *{mode_label}*\n"
                f"• Provider: *{(settings.EMAIL_PROVIDER or 'smtp').upper()}*\n"
                f"• Total Processed: *{summary['total_candidates']}*\n"
                f"• Sent / Simulated: *{summary['sent'] + summary['simulated']}*\n"
                f"• Throttled (Daily Quota): *{summary['throttled']}*\n"
                f"• Bounced (Pre-flight MX): *{summary['bounced']}*\n"
                f"• Suppressed (Unsubscribed): *{summary['suppressed']}*\n"
                f"• Failed: *{summary['failed']}*\n\n"
                f"All dispatched records have been logged in the outbound audit database."
            )
            return {"status": "success", "message": "Dispatched", "reply": reply}

        # 1B.3 Sub-campaign batch approval
        elif cb_data.startswith("subcamp_approve:"):
            parts = cb_data.split(":")
            camp_uuid = uuid.UUID(parts[1])
            sub_idx = int(parts[2]) if len(parts) > 2 else 1
            camp = db.get(Campaign, camp_uuid)
            if not camp:
                return {"status": "error", "reply": "Campaign not found."}

            bench_score = camp.filters.get("min_score", 0) if isinstance(camp.filters, dict) else 0
            remaining_needed = max(0, camp.target_sent_emails - camp.total_sent_emails)
            max_batch_send = min(remaining_needed, camp.requested_quantity) if camp.requested_quantity > 0 else remaining_needed

            if settings.TELEGRAM_BOT_TOKEN and user_id:
                send_telegram_text(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=user_id,
                    text=(
                        f"🚀 *Batch {sub_idx} Approved!*\n\n"
                        f"• Validating recipient deliverability (Pre-flight MX check)...\n"
                        f"• Dispatching outbound emails via active Gmail mailboxes...\n\n"
                        f"⚡ Dispatching up to {max_batch_send} emails. Please stand by..."
                    ),
                )

            disp_summary = dispatch_subcampaign_batch(
                db=db,
                campaign_id=camp.id,
                max_to_send=max_batch_send,
                settings=settings,
                agency_name=agency_name,
                sender_name=sender_name,
            )
            batch_sent = disp_summary["sent"] + disp_summary["simulated"]

            if camp.total_sent_emails >= camp.target_sent_emails:
                camp.status = "completed"
                db.commit()
                text, files = deliver_campaign_final_csvs(db, camp, settings, user_id, bench_score)
                return {"status": "success", "reply": text, "files": files}

            # Still need more sent emails to reach target -> auto-trigger Sub-Campaign 2
            next_sub_idx = camp.sub_campaign_index + 1
            camp.sub_campaign_index = next_sub_idx
            db.commit()

            current_search_loc = camp.expanded_locations[-1] if camp.expanded_locations else camp.location

            unattempted = (
                db.query(Lead)
                .filter(
                    Lead.campaign_id == camp.id,
                    Lead.overall_score >= bench_score,
                    Lead.outreach_status.in_(["draft", "approved"]),
                )
                .count()
            )

            if camp.is_exhausted and unattempted == 0:
                next_loc = get_next_expansion_location(camp.location, camp.expanded_locations)
                prompt, buttons = build_expansion_prompt(
                    camp=camp,
                    current_search_loc=current_search_loc,
                    next_loc=next_loc,
                    qualified_count=unattempted,
                    target_count=camp.requested_quantity,
                    bench_score=bench_score,
                )
                return {"status": "paused_exhaustion", "reply": prompt, "buttons": buttons}

            remaining_gap = max(0, camp.target_sent_emails - camp.total_sent_emails)
            if settings.TELEGRAM_BOT_TOKEN and user_id:
                send_telegram_text(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=user_id,
                    text=(
                        f"📨 *Batch {sub_idx} Outreach Complete!*\n\n"
                        f"• Successfully Sent: *{batch_sent}* emails\n"
                        f"• Total Progress: *{camp.total_sent_emails} / {camp.target_sent_emails}* emails ({remaining_gap} remaining)\n\n"
                        f"🔄 *Auto-Triggering Sub-Campaign {next_sub_idx}...*\n"
                        f"Gathering next batch of {camp.requested_quantity} qualified leads to reach your target of {camp.target_sent_emails} sent emails!"
                    ),
                )

            unattempted = (
                db.query(Lead)
                .filter(
                    Lead.campaign_id == camp.id,
                    Lead.overall_score >= bench_score,
                    Lead.outreach_status.in_(["draft", "approved"]),
                )
                .count()
            )
            if unattempted < camp.requested_quantity:
                run_campaign(
                    db,
                    camp.id,
                    settings,
                    agency_name=agency_name,
                    sender_name=sender_name,
                    location_override=current_search_loc,
                    target_count=camp.requested_quantity,
                )

            unattempted = (
                db.query(Lead)
                .filter(
                    Lead.campaign_id == camp.id,
                    Lead.overall_score >= bench_score,
                    Lead.outreach_status.in_(["draft", "approved"]),
                )
                .count()
            )

            if unattempted < camp.requested_quantity and camp.is_exhausted:
                next_loc = get_next_expansion_location(camp.location, camp.expanded_locations)
                prompt, buttons = build_expansion_prompt(
                    camp=camp,
                    current_search_loc=current_search_loc,
                    next_loc=next_loc,
                    qualified_count=unattempted,
                    target_count=camp.requested_quantity,
                    bench_score=bench_score,
                )
                return {"status": "paused_exhaustion", "reply": prompt, "buttons": buttons}

            sub_csv = generate_campaign_csv(
                db,
                camp.id,
                min_score=bench_score,
                limit=camp.requested_quantity,
                only_unattempted=True,
            )
            sub_filename = f"Sub_Campaign_{next_sub_idx}_Preview.csv"
            delivered_batch = min(unattempted, camp.requested_quantity)
            if settings.TELEGRAM_BOT_TOKEN and user_id:
                send_telegram_document(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=user_id,
                    file_bytes=sub_csv.encode("utf-8"),
                    filename=sub_filename,
                    caption=f"📄 Preview for Sub-Campaign {next_sub_idx} ({delivered_batch} qualified leads ready)",
                )

            prompt = (
                f"🚀 *Sub-Campaign {next_sub_idx} Ready*\n\n"
                f"• Previous Batch Sent: *{batch_sent}* emails\n"
                f"• Total Progress: *{camp.total_sent_emails} / {camp.target_sent_emails}* emails sent\n"
                f"• Remaining to Goal: *{remaining_gap}*\n"
                f"• Batch {next_sub_idx} Qualified Leads: *{delivered_batch}*\n\n"
                f"📄 Preview CSV attached above.\n"
                f"Choose your action below:"
            )
            use_best_template = camp.filters.get("use_best_response_template", False) if isinstance(camp.filters, dict) else False
            row1 = [{"text": f"🚀 Approve Batch {next_sub_idx}", "callback_data": f"subcamp_approve:{camp.id}:{next_sub_idx}"}]
            if not use_best_template:
                row1.append({"text": "🔍 Review 1-by-1", "callback_data": f"start_review:{camp.id}:{bench_score}"})
            buttons = [
                row1,
                [
                    {"text": "🤖 Auto Mode (Run All Next Loops)", "callback_data": f"subcamp_auto:{camp.id}:{next_sub_idx}"},
                ]
            ]
            return {"status": "success", "reply": prompt, "buttons": buttons}

        # 1B.4 Sub-campaign Auto Mode
        elif cb_data.startswith("subcamp_auto:"):
            parts = cb_data.split(":")
            camp_uuid = uuid.UUID(parts[1])
            camp = db.get(Campaign, camp_uuid)
            if not camp:
                return {"status": "error", "reply": "Campaign not found."}

            camp.is_auto_mode = True
            bench_score = camp.filters.get("min_score", 0) if isinstance(camp.filters, dict) else 0

            max_loops = 10
            loop_count = 0
            while camp.total_sent_emails < camp.target_sent_emails and loop_count < max_loops:
                loop_count += 1
                remaining_needed = camp.target_sent_emails - camp.total_sent_emails
                max_batch_send = min(remaining_needed, camp.requested_quantity) if camp.requested_quantity > 0 else remaining_needed

                disp_summary = dispatch_subcampaign_batch(
                    db=db,
                    campaign_id=camp.id,
                    max_to_send=max_batch_send,
                    settings=settings,
                    agency_name=agency_name,
                    sender_name=sender_name,
                )
                batch_sent = disp_summary["sent"] + disp_summary["simulated"]
                if settings.TELEGRAM_BOT_TOKEN and user_id and batch_sent > 0:
                    send_telegram_text(
                        bot_token=settings.TELEGRAM_BOT_TOKEN,
                        chat_id=user_id,
                        text=f"⚡ *Sub-Campaign {camp.sub_campaign_index} Auto-Dispatched:*\nSent *{batch_sent}* emails. Total Progress: *{camp.total_sent_emails} / {camp.target_sent_emails}*.",
                    )

                if camp.total_sent_emails >= camp.target_sent_emails:
                    break

                camp.sub_campaign_index += 1
                db.commit()

                current_search_loc = camp.expanded_locations[-1] if camp.expanded_locations else camp.location
                unattempted = (
                    db.query(Lead)
                    .filter(
                        Lead.campaign_id == camp.id,
                        Lead.overall_score >= bench_score,
                        Lead.outreach_status.in_(["draft", "approved"]),
                    )
                    .count()
                )
                if unattempted < camp.requested_quantity:
                    run_campaign(
                        db,
                        camp.id,
                        settings,
                        agency_name=agency_name,
                        sender_name=sender_name,
                        location_override=current_search_loc,
                        target_count=camp.requested_quantity,
                    )

                unattempted = (
                    db.query(Lead)
                    .filter(
                        Lead.campaign_id == camp.id,
                        Lead.overall_score >= bench_score,
                        Lead.outreach_status.in_(["draft", "approved"]),
                    )
                    .count()
                )

                if unattempted < camp.requested_quantity and camp.is_exhausted:
                    next_loc = get_next_expansion_location(camp.location, camp.expanded_locations)
                    prompt, buttons = build_expansion_prompt(
                        camp=camp,
                        current_search_loc=current_search_loc,
                        next_loc=next_loc,
                        qualified_count=unattempted,
                        target_count=camp.requested_quantity,
                        bench_score=bench_score,
                    )
                    return {"status": "paused_exhaustion", "reply": prompt, "buttons": buttons}

            if camp.total_sent_emails >= camp.target_sent_emails:
                camp.status = "completed"
                db.commit()
                text, files = deliver_campaign_final_csvs(db, camp, settings, user_id, bench_score)
                return {"status": "success", "reply": text, "files": files}

            prompt = (
                f"⏸️ *Sub-Campaign Batch Paused*\n"
                f"• Sent: *{camp.total_sent_emails} / {camp.target_sent_emails}*\n"
                f"Click below to continue next round:"
            )
            buttons = [
                [
                    {"text": f"🚀 Continue Next Sub-Campaign", "callback_data": f"subcamp_auto:{camp.id}:{camp.sub_campaign_index}"},
                    {"text": f"🏁 Finish Early with {camp.total_sent_emails} Sent", "callback_data": f"finish_campaign_early:{camp.id}"},
                ]
            ]
            return {"status": "in_progress", "reply": prompt, "buttons": buttons}

        # 1B.5 Expand Search Radius (multi-hop with user permission)
        elif cb_data.startswith("expand_radius:"):
            parts = cb_data.split(":")
            camp_uuid = uuid.UUID(parts[1])
            target_override = parts[2] if len(parts) > 2 and parts[2].strip() else None
            camp = db.get(Campaign, camp_uuid)
            if not camp:
                return {"status": "error", "reply": "Campaign not found."}

            bench_score = camp.filters.get("min_score", 0) if isinstance(camp.filters, dict) else 0
            visited = list(camp.expanded_locations or [])
            next_loc = target_override or get_next_expansion_location(camp.location, visited)
            if not next_loc:
                next_loc = f"Greater {camp.location}"

            if next_loc not in visited:
                visited.append(next_loc)
            camp.expanded_locations = visited
            camp.radius_expanded = True
            camp.is_exhausted = False
            camp.status = "in_progress"
            db.commit()

            if settings.TELEGRAM_BOT_TOKEN and user_id:
                send_telegram_text(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=user_id,
                    text=f"🌍 *Expanding Search Radius to {next_loc}*\nSearching strictly for *{camp.niche}* (Score ≥ {bench_score})...",
                )

            run_campaign(
                db,
                camp.id,
                settings,
                agency_name=agency_name,
                sender_name=sender_name,
                location_override=next_loc,
                target_count=camp.requested_quantity,
            )

            matching_leads = (
                db.query(Lead)
                .filter(
                    Lead.campaign_id == camp.id,
                    Lead.overall_score >= bench_score,
                    Lead.outreach_status.in_(["draft", "approved"]),
                )
                .count()
            )

            if matching_leads < camp.requested_quantity and camp.is_exhausted:
                next_next_loc = get_next_expansion_location(camp.location, camp.expanded_locations)
                prompt, buttons = build_expansion_prompt(
                    camp=camp,
                    current_search_loc=next_loc,
                    next_loc=next_next_loc,
                    qualified_count=matching_leads,
                    target_count=camp.requested_quantity,
                    bench_score=bench_score,
                )
                return {"status": "paused_exhaustion", "reply": prompt, "buttons": buttons}

            if camp.is_auto_mode:
                return handle_telegram_update(
                    {"callback_query": {"data": f"subcamp_auto:{camp.id}:{camp.sub_campaign_index}", "from": {"id": user_id}}},
                    db,
                    settings,
                )

            delivered_count = min(matching_leads, camp.requested_quantity)
            sub_csv = generate_campaign_csv(
                db,
                camp.id,
                min_score=bench_score,
                limit=camp.requested_quantity,
                only_unattempted=True,
            )
            sub_filename = f"Sub_Campaign_{camp.sub_campaign_index}_Preview.csv"
            if settings.TELEGRAM_BOT_TOKEN and user_id:
                send_telegram_document(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=user_id,
                    file_bytes=sub_csv.encode("utf-8"),
                    filename=sub_filename,
                    caption=f"📄 Preview for Sub-Campaign {camp.sub_campaign_index} in {next_loc} ({delivered_count} qualified leads ready)",
                )

            remaining_gap = max(0, camp.target_sent_emails - camp.total_sent_emails)
            prompt = (
                f"🌍 *Search Radius Expanded to {next_loc}!*\n\n"
                f"• Target Niche: *{camp.niche}* (Preserved strictly)\n"
                f"• Benchmark Filter: *Score ≥ {bench_score}*\n"
                f"• Batch {camp.sub_campaign_index} Qualified Leads: *{delivered_count}*\n"
                f"• Total Sent So Far: *{camp.total_sent_emails} / {camp.target_sent_emails}* ({remaining_gap} remaining)\n\n"
                f"Choose your action below:"
            )
            use_best_template = camp.filters.get("use_best_response_template", False) if isinstance(camp.filters, dict) else False
            row1 = [{"text": f"🚀 Approve Batch {camp.sub_campaign_index}", "callback_data": f"subcamp_approve:{camp.id}:{camp.sub_campaign_index}"}]
            if not use_best_template:
                row1.append({"text": "🔍 Review 1-by-1", "callback_data": f"start_review:{camp.id}:{bench_score}"})
            buttons = [
                row1,
                [
                    {"text": "🤖 Auto Mode (Run All Next Loops)", "callback_data": f"subcamp_auto:{camp.id}:{camp.sub_campaign_index}"},
                ]
            ]
            return {"status": "success", "reply": prompt, "buttons": buttons}

        # 1B.6 Proceed with current batch leads (skip further expansion)
        elif cb_data.startswith("proceed_batch:"):
            parts = cb_data.split(":")
            camp_uuid = uuid.UUID(parts[1])
            camp = db.get(Campaign, camp_uuid)
            if not camp:
                return {"status": "error", "reply": "Campaign not found."}

            bench_score = camp.filters.get("min_score", 0) if isinstance(camp.filters, dict) else 0
            matching = db.query(Lead).filter(
                Lead.campaign_id == camp.id,
                Lead.overall_score >= bench_score,
                Lead.outreach_status.in_(["draft", "approved"]),
            ).count()

            if matching == 0:
                return {"status": "error", "reply": "No qualified leads ready to proceed. Please expand search radius or adjust threshold."}

            sub_csv = generate_campaign_csv(db, camp.id, min_score=bench_score, limit=matching, only_unattempted=True)
            sub_filename = f"Sub_Campaign_{camp.sub_campaign_index}_Preview.csv"
            if settings.TELEGRAM_BOT_TOKEN and user_id:
                send_telegram_document(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=user_id,
                    file_bytes=sub_csv.encode("utf-8"),
                    filename=sub_filename,
                    caption=f"📄 Preview for Sub-Campaign {camp.sub_campaign_index} ({matching} qualified leads ready)",
                )

            remaining_gap = max(0, camp.target_sent_emails - camp.total_sent_emails)
            reply = (
                f"🚀 *Sub-Campaign {camp.sub_campaign_index} Ready!*\n\n"
                f"• Target Niche: *{camp.niche}*\n"
                f"• Location: *{camp.location}*\n"
                f"• Target Sent Emails: *{camp.target_sent_emails}*\n"
                f"• Benchmark Filter: *Score ≥ {bench_score}*\n"
                f"• Batch {camp.sub_campaign_index} Qualified Leads: *{matching}*\n"
                f"• Total Sent So Far: *{camp.total_sent_emails}* ({remaining_gap} remaining)\n\n"
                f"📄 Preview CSV attached above.\n"
                f"Choose your action below:"
            )
            use_best_template = camp.filters.get("use_best_response_template", False) if isinstance(camp.filters, dict) else False
            row1 = [{"text": f"🚀 Approve Batch {camp.sub_campaign_index}", "callback_data": f"subcamp_approve:{camp.id}:{camp.sub_campaign_index}"}]
            if not use_best_template:
                row1.append({"text": "🔍 Review 1-by-1", "callback_data": f"start_review:{camp.id}:{bench_score}"})
            buttons = [
                row1,
                [
                    {"text": "🤖 Auto Mode (Run All Next Loops)", "callback_data": f"subcamp_auto:{camp.id}:{camp.sub_campaign_index}"},
                ],
            ]
            return {"status": "success", "reply": reply, "buttons": buttons}

        # 1B.6 Finish Campaign Early
        elif cb_data.startswith("finish_campaign_early:"):
            parts = cb_data.split(":")
            camp_uuid = uuid.UUID(parts[1])
            camp = db.get(Campaign, camp_uuid)
            if not camp:
                return {"status": "error", "reply": "Campaign not found."}

            bench_score = camp.filters.get("min_score", 0) if isinstance(camp.filters, dict) else 0
            camp.status = "completed"
            db.commit()
            text, files = deliver_campaign_final_csvs(db, camp, settings, user_id, bench_score)
            return {"status": "success", "reply": text, "files": files}

        # 1B.7 Adjust Benchmark Threshold
        elif cb_data.startswith("adjust_threshold:"):
            parts = cb_data.split(":")
            camp_uuid = uuid.UUID(parts[1])
            new_score = int(parts[2]) if len(parts) > 2 else 40
            camp = db.get(Campaign, camp_uuid)
            if not camp:
                return {"status": "error", "reply": "Campaign not found."}

            filters = dict(camp.filters or {})
            filters["min_score"] = new_score
            camp.filters = filters
            db.commit()

            matching_leads = (
                db.query(Lead)
                .filter(Lead.campaign_id == camp.id, Lead.overall_score >= new_score)
                .count()
            )

            csv_str = generate_campaign_csv(db, camp.id, min_score=new_score, limit=camp.target_sent_emails)
            filename = f"Sub_Campaign_1_Preview.csv"

            if settings.TELEGRAM_BOT_TOKEN and user_id:
                caption = f"📄 Sub-Campaign 1 Preview: {matching_leads} qualified leads ready (Score ≥ {new_score})"
                send_telegram_document(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=user_id,
                    file_bytes=csv_str.encode("utf-8"),
                    filename=filename,
                    caption=caption,
                )

            use_best_template = camp.filters.get("use_best_response_template", False) if isinstance(camp.filters, dict) else False
            row1 = [{"text": "🚀 Approve Batch 1", "callback_data": f"subcamp_approve:{camp.id}:1"}]
            if not use_best_template:
                row1.append({"text": "🔍 Review 1-by-1", "callback_data": f"start_review:{camp.id}:{new_score}"})
            buttons = [
                row1,
                [
                    {"text": "🤖 Auto Mode (Run All Next Loops)", "callback_data": f"subcamp_auto:{camp.id}:1"},
                ]
            ]

            review_line = "" if use_best_template else "• *Review 1-by-1*: Inspect each business and pitch individually\n"
            reply = (
                f"✅ *Benchmark Threshold Adjusted to Score ≥ {new_score}!*\n\n"
                f"• Target Niche: *{camp.niche}*\n"
                f"• Location: *{camp.location}*\n"
                f"• Qualified Leads Ready: *{matching_leads}*\n"
                f"• Outreach Goal: Deliver *{camp.target_sent_emails}* emails\n"
                f"• Campaign ID: `{camp.id}`\n\n"
                f"📄 *Attached:* `{filename}`\n"
                f"Top *{matching_leads}* leads ordered by intent score have been sent above!\n\n"
                f"👇 *Choose Outreach Mode:*\n"
                f"• *Approve Batch 1*: Sends current batch, then pauses for Sub-Campaign 2\n"
                f"{review_line}"
                f"• *Auto Mode*: Runs all subsequent sub-campaigns automatically until {camp.target_sent_emails} emails are delivered!"
            )
            return {"status": "success", "reply": reply, "buttons": buttons}

        # 1C. Exit Review Mode
        elif cb_data.startswith("review_exit:"):
            parts = cb_data.split(":")
            camp_uuid = uuid.UUID(parts[1]) if len(parts) > 1 and parts[1] else None
            camp = db.get(Campaign, camp_uuid) if camp_uuid else db.query(Campaign).order_by(Campaign.created_at.desc()).first()
            if not camp:
                return {"status": "error", "reply": "No active campaign found to exit review."}

            pending_count = (
                db.query(Lead)
                .filter(Lead.campaign_id == camp.id, Lead.overall_score >= 80, Lead.outreach_status == "draft")
                .count()
            )
            approved_count = (
                db.query(Lead)
                .filter(Lead.campaign_id == camp.id, Lead.outreach_status == "approved")
                .count()
            )

            reply = (
                f"⏸️ *Review Paused*\n\n"
                f"🏢 Campaign: *{camp.niche}* ({camp.location})\n"
                f"• ✅ *{approved_count} approved*\n"
                f"• ⏳ *{pending_count} remaining pending* (Score ≥ 80)\n\n"
                f"Choose your next step below:"
            )
            pause_buttons = []
            if pending_count > 0:
                pause_buttons.append([
                    {"text": f"🚀 Approve All Remaining ({pending_count})", "callback_data": f"bulk_approve:{camp.id}:80"},
                ])
                pause_buttons.append([
                    {"text": f"🔍 Resume Review One-by-One", "callback_data": f"start_review:{camp.id}:80"},
                ])
            pause_buttons.append([
                {"text": "📥 Export CSV", "callback_data": f"export_csv:{camp.id}"},
            ])

            return {
                "status": "success",
                "message": "Exited review mode",
                "reply": reply,
                "buttons": pause_buttons,
            }

        # 1B. Start review from button
        elif cb_data.startswith("start_review:"):
            parts = cb_data.split(":")
            camp_uuid = uuid.UUID(parts[1]) if len(parts) > 1 and parts[1] else None
            score_filter = int(parts[2]) if len(parts) > 2 else 80
            lead, pending_count = get_next_pending_lead(db, campaign_id=camp_uuid, min_score=score_filter)
            if not lead:
                return {"status": "success", "message": "All leads reviewed!", "reply": "🎉 All leads have already been reviewed!"}
            biz = db.get(Business, lead.business_id)
            draft = db.query(MessageDraft).filter_by(lead_id=lead.id).first()
            evs = db.query(Evidence).filter_by(business_id=lead.business_id, campaign_id=lead.campaign_id).all()

            camp = db.get(Campaign, lead.campaign_id) if lead else None
            services_desc = camp.filters.get("services_desc") if (camp and isinstance(camp.filters, dict)) else None
            if settings.USER_LLM_API_KEY and (not draft or not draft.body or "(Draft" in draft.body):
                ai_pitch = generate_gemini_pitch(
                    business=biz,
                    lead=lead,
                    evidence=evs,
                    settings=settings,
                    custom_instruction=services_desc,
                    agency_name=agency_name,
                    sender_name=sender_name,
                )
                if ai_pitch:
                    if not draft:
                        draft = MessageDraft(lead_id=lead.id, channel="preview", status="preview", body=ai_pitch, evidence_ids=[])
                        db.add(draft)
                    else:
                        draft.body = ai_pitch
                    db.flush()

            card_text, buttons = format_approval_card(lead, biz, draft, evs, is_review_mode=True, remaining_count=pending_count)
            return {"status": "success", "message": "Opening lead review...", "reply": card_text, "buttons": buttons}

        # 1C. Review actions (review_approve, review_skip, review_reject, review_regen)
        elif cb_data.startswith("review_"):
            raw_action = cb_data.replace("review_", "", 1)
            action, lead_id_str = raw_action.split(":", 1)
            try:
                lead_uuid = uuid.UUID(lead_id_str)
            except ValueError:
                return {"status": "error", "message": "Invalid lead UUID in callback"}

            curr_lead = db.get(Lead, lead_uuid)
            curr_biz = db.get(Business, curr_lead.business_id) if curr_lead else None
            camp_id = curr_lead.campaign_id if curr_lead else None

            if action == "regen":
                evs = db.query(Evidence).filter_by(business_id=curr_biz.id).all() if curr_biz else []
                camp = db.get(Campaign, camp_id) if camp_id else None
                services_desc = camp.filters.get("services_desc") if (camp and isinstance(camp.filters, dict)) else None
                new_pitch = generate_gemini_pitch(
                    business=curr_biz,
                    lead=curr_lead,
                    evidence=evs,
                    settings=settings,
                    custom_instruction=services_desc,
                    agency_name=agency_name,
                    sender_name=sender_name,
                ) if curr_biz and curr_lead else None
                if new_pitch:
                    ai_draft = (
                        db.query(MessageDraft)
                        .filter_by(lead_id=lead_uuid, channel="ai_regenerated")
                        .first()
                    )
                    if not ai_draft:
                        ai_draft = MessageDraft(
                            lead_id=lead_uuid,
                            channel="ai_regenerated",
                            status="preview",
                            body=new_pitch,
                            evidence_ids=[],
                        )
                        db.add(ai_draft)
                    else:
                        ai_draft.body = new_pitch
                        ai_draft.status = "preview"
                    db.flush()
                    card_text, buttons = format_approval_card(curr_lead, curr_biz, ai_draft, evs, is_review_mode=True)
                    return {"status": "success", "message": "✨ AI Pitch Regenerated!", "reply": f"✨ *Regenerated with Gemini for {curr_biz.name}:*\n\n" + card_text, "buttons": buttons}
                else:
                    return {"status": "error", "message": "Gemini API key not configured or returned no output."}

            res = record_approval(db, lead_uuid, str(user_id), action)

            # Fetch the next pending lead
            next_lead, pending_count = get_next_pending_lead(db, campaign_id=camp_id, min_score=80)
            if not next_lead:
                action_word = "Approved" if action == "approve" else ("Skipped" if action == "skip" else "Rejected")
                finish_buttons = [
                    [{"text": "📥 Export CSV", "callback_data": f"export_csv:{camp_id}"}],
                ]
                return {
                    "status": "success",
                    "message": f"Lead {action_word}. All caught up!",
                    "reply": f"🎉 *Review Complete!*\n\nAll qualified leads in this campaign have been processed. Click below to export the CSV or send `/findleads` for new leads.",
                    "buttons": finish_buttons,
                }

            next_biz = db.get(Business, next_lead.business_id)
            next_draft = (
                db.query(MessageDraft)
                .filter_by(lead_id=next_lead.id, channel="ai_regenerated")
                .first()
            ) or db.query(MessageDraft).filter_by(lead_id=next_lead.id).first()
            next_evs = db.query(Evidence).filter_by(business_id=next_lead.business_id, campaign_id=next_lead.campaign_id).all()

            if settings.USER_LLM_API_KEY and (not next_draft or not next_draft.body or "(Draft" in next_draft.body):
                ai_pitch = generate_gemini_pitch(
                    business=next_biz,
                    lead=next_lead,
                    evidence=next_evs,
                    settings=settings,
                    agency_name=agency_name,
                    sender_name=sender_name,
                )
                if ai_pitch:
                    if not next_draft:
                        next_draft = MessageDraft(lead_id=next_lead.id, channel="preview", status="preview", body=ai_pitch, evidence_ids=[])
                        db.add(next_draft)
                    else:
                        next_draft.body = ai_pitch
                    db.flush()

            card_text, buttons = format_approval_card(next_lead, next_biz, next_draft, next_evs, is_review_mode=True, remaining_count=pending_count)
            action_tag = "✅ Approved" if action == "approve" else ("⏭️ Skipped" if action == "skip" else "❌ Rejected")
            return {
                "status": "success",
                "message": f"{action_tag} '{curr_biz.name if curr_biz else 'Lead'}'. Next lead loaded.",
                "reply": f"{action_tag} *{curr_biz.name if curr_biz else 'Lead'}*!\n\n" + card_text,
                "buttons": buttons,
            }

        # 1D. Settings & Profile Interactive Callbacks
        elif cb_data == "open_settings":
            _USER_SETTINGS_SESSIONS.add(user_key)
            reply, buttons = format_settings_dashboard(db, settings, user_key, sender_name, agency_name)
            return {"status": "success", "reply": reply, "buttons": buttons}

        elif cb_data == "settings_add_email":
            _USER_SETTINGS_SESSIONS.add(user_key)
            _USER_AWAITING_MAILBOX_INPUT.add(user_key)
            prompt = (
                "➕ *Connect Outreach Gmail Account*\n\n"
                "Please send your Gmail address and 16-letter App Password in this format:\n"
                "`/addemailaddress <email> <app_password>`\n\n"
                "*Example:*\n"
                "`/addemailaddress outreach@gmail.com abcd efgh ijkl mnop`\n\n"
                "💡 *Or simply reply directly with:*\n"
                "`outreach@gmail.com abcd efgh ijkl mnop`\n\n"
                "🔑 *Need an App Password?*\n"
                "1. Turn ON 2-Step Verification: [myaccount.google.com/security](https://myaccount.google.com/security)\n"
                "2. Generate password: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)"
            )
            buttons = [[{"text": "❌ Cancel", "callback_data": "open_settings"}]]
            return {"status": "success", "reply": prompt, "buttons": buttons}

        elif cb_data.startswith("del_mailbox:"):
            target_em = cb_data.split(":", 1)[1]
            prompt = (
                f"⚠️ *Delete Mailbox Confirmation*\n\n"
                f"Are you sure you want to remove *{target_em}* from your active rotation pool?"
            )
            buttons = [
                [
                    {"text": "🗑️ Yes, Delete", "callback_data": f"confirm_del:{target_em}"},
                    {"text": "❌ Cancel", "callback_data": "open_settings"},
                ]
            ]
            return {"status": "success", "reply": prompt, "buttons": buttons}

        elif cb_data.startswith("confirm_del:"):
            target_em = cb_data.split(":", 1)[1]
            remove_mailbox_account(db, target_em)
            reply, buttons = format_settings_dashboard(db, settings, user_key, sender_name, agency_name)
            return {
                "status": "success",
                "message": f"Mailbox {target_em} removed",
                "reply": f"✅ Mailbox *{target_em}* removed from rotation pool.\n\n" + reply,
                "buttons": buttons,
            }

        elif cb_data == "open_profile":
            reply, buttons = format_profile_card(db, user_key, sender_name, agency_name)
            return {"status": "success", "reply": reply, "buttons": buttons}

        elif cb_data == "edit_profile:name":
            _USER_EDIT_PROFILE_SESSIONS[user_key] = "name"
            prompt = (
                "✏️ *Update Sender Name*\n\n"
                "Please reply with your new Name (e.g., `Alex Rivera`):\n\n"
                "_(Or send `/cancel` to abort)_"
            )
            return {"status": "success", "reply": prompt}

        elif cb_data == "edit_profile:agency":
            _USER_EDIT_PROFILE_SESSIONS[user_key] = "agency"
            prompt = (
                "🏢 *Update Business / Agency Name*\n\n"
                "Please reply with your new Business Name (e.g., `Apex Digital Solutions`):\n\n"
                "_(Or send `/cancel` to abort)_"
            )
            return {"status": "success", "reply": prompt}

        elif cb_data.startswith("wizard_template:"):
            choice = cb_data.split(":", 1)[1].lower()
            use_best = choice in ("yes", "y", "true", "1")
            session_data = _USER_WIZARD_SESSIONS.get(user_key)
            if not session_data or session_data.get("step") != "awaiting_template_choice":
                return {"status": "error", "reply": "⚠️ Campaign setup session expired or invalid. Please start again with `/findleads`."}
            return _execute_wizard_campaign(
                db=db,
                settings=settings,
                user_id=user_id,
                user_key=user_key,
                session_data=session_data,
                use_best_response_template=use_best,
                agency_name=agency_name,
                sender_name=sender_name,
            )

        elif cb_data == "start_findleads":
            _USER_WIZARD_SESSIONS[user_key] = {"step": "awaiting_niche", "data": {}}
            reply = (
                "🎯 *Universal Client Discovery (Step 1/6)*\n\n"
                "Built for any agency or freelancer offering B2B services.\n\n"
                "What is your *target client niche or industry*?\n"
                "_(e.g., Real Estate, Dental Clinics, Law Firms, Roofers, E-commerce, Gyms)_\n\n"
                "💡 _Tip: You can cancel at any time by sending `/cancel`._"
            )
            return {"status": "wizard_step", "reply": reply}

        # 1E. Standard single callback (approve:uuid, reject:uuid, skip:uuid)
        elif ":" in cb_data:
            action, lead_id_str = cb_data.split(":", 1)
            try:
                lead_uuid = uuid.UUID(lead_id_str)
                res = record_approval(db, lead_uuid, str(user_id), action)
                return res
            except ValueError:
                return {"status": "error", "message": "Invalid lead UUID in callback"}
        return {"status": "ignored", "message": "Unrecognized callback data"}

    # 2. Handle Text Messages & Commands
    msg = update.get("message", {})
    text = msg.get("text", "").strip()
    user_key = str(user_id)

    if not text:
        return {"status": "empty", "message": "No text in message"}

    if text in ("/cancel", "/reset"):
        if user_key in _USER_ONBOARDING_SESSIONS:
            _USER_ONBOARDING_SESSIONS.pop(user_key, None)
            return {"status": "cancelled", "reply": "❌ Setup cancelled. Send `/start` whenever you are ready!"}
        if user_key in _USER_WIZARD_SESSIONS:
            _USER_WIZARD_SESSIONS.pop(user_key, None)
            return {
                "status": "cancelled",
                "reply": "❌ Campaign setup cancelled. Send `/findleads` whenever you are ready!",
            }
        if user_key in _USER_EDIT_PROFILE_SESSIONS:
            _USER_EDIT_PROFILE_SESSIONS.pop(user_key, None)
            return {"status": "cancelled", "reply": "❌ Profile edit cancelled. Send `/profile` to view your profile."}
        if user_key in _USER_AWAITING_MAILBOX_INPUT:
            _USER_AWAITING_MAILBOX_INPUT.discard(user_key)
            return {"status": "cancelled", "reply": "❌ Add mailbox cancelled. Send `/settings` to view settings."}
        return {"status": "cancelled", "reply": "No active setup in progress."}

    if text.lower() in ("/live", "/makelive", "/setlive"):
        settings.OUTREACH_DRY_RUN = False
        try:
            for p in (Path(".env"), Path("apps/intelligence-api/.env")):
                if p.exists():
                    c = p.read_text(encoding="utf-8")
                    c = re.sub(r"OUTREACH_DRY_RUN=\w+", "OUTREACH_DRY_RUN=false", c, flags=re.IGNORECASE)
                    p.write_text(c, encoding="utf-8")
        except Exception:
            pass
        return {
            "status": "success",
            "reply": (
                "🚀 *Outreach Mode Set to LIVE!*\n\n"
                "• Mode: *🟢 LIVE (Real Outbound Emails)*\n"
                "• When you approve leads or sub-campaign batches, real emails will be dispatched to prospects through your connected mailboxes.\n\n"
                "_(Send `/dryrun` anytime if you wish to switch back to simulation mode.)_"
            ),
        }

    if text.lower() in ("/dryrun", "/dry_run", "/simulated"):
        settings.OUTREACH_DRY_RUN = True
        try:
            for p in (Path(".env"), Path("apps/intelligence-api/.env")):
                if p.exists():
                    c = p.read_text(encoding="utf-8")
                    c = re.sub(r"OUTREACH_DRY_RUN=\w+", "OUTREACH_DRY_RUN=true", c, flags=re.IGNORECASE)
                    p.write_text(c, encoding="utf-8")
        except Exception:
            pass
        return {
            "status": "success",
            "reply": (
                "🟡 *Outreach Mode Set to DRY-RUN!*\n\n"
                "• Mode: *🟡 DRY-RUN (Simulation)*\n"
                "• Approvals will record drafts and validate deliverables without sending live emails.\n\n"
                "_(Send `/live` to switch to real dispatch.)_"
            ),
        }

    if text.lower() in ("/mode", "/safetymode"):
        current_mode = "🟢 LIVE (Real Outbound Emails)" if not settings.OUTREACH_DRY_RUN else "🟡 DRY-RUN (Simulated)"
        return {
            "status": "success",
            "reply": (
                f"⚙️ *Current Outreach Mode:*\n\n"
                f"• Status: *{current_mode}*\n\n"
                f"Commands:\n"
                f"• `/live` — Switch to real email dispatch\n"
                f"• `/dryrun` — Switch to simulation mode"
            ),
        }

    if text.lower().startswith(("/clean memory", "/clean_memory", "/cleandata", "/resetall")) or text.lower() == "/clean":
        # 1. Clear all in-memory session states
        _USER_ONBOARDING_SESSIONS.pop(user_key, None)
        _USER_WIZARD_SESSIONS.pop(user_key, None)
        _USER_EDIT_PROFILE_SESSIONS.pop(user_key, None)
        _USER_SETTINGS_SESSIONS.discard(user_key)
        _USER_AWAITING_MAILBOX_INPUT.discard(user_key)

        # 2. Delete user database records (Profile and Mailbox Accounts)
        prof = db.get(OperatorProfile, user_key)
        if prof:
            db.delete(prof)
        db.query(MailboxAccount).delete()
        db.query(CampaignLeftoverLead).delete()
        db.commit()

        # 3. Start fresh first-chat onboarding
        _USER_ONBOARDING_SESSIONS[user_key] = {"step": "awaiting_sender_name", "trigger_findleads": True}

        reset_reply = (
            "🧹 *App Data & Memory Cleared!*\n"
            "All profiles, settings, and connected mailboxes have been completely wiped clean — just like a fresh app install.\n\n"
            "👋 *Welcome to IntentLead AI!*\n"
            "Let's set up your profile from the very beginning:\n\n"
            "👤 *Step 1/3: What is your Name?* (Sender Name)\n"
            "_(e.g., Roy | Alex | Sarah)_"
        )
        return {"status": "onboarding_start", "reply": reset_reply}

    # Handle Active Profile Edit Session
    if user_key in _USER_EDIT_PROFILE_SESSIONS and not text.startswith("/"):
        field = _USER_EDIT_PROFILE_SESSIONS.pop(user_key)
        prof = db.get(OperatorProfile, user_key)
        if not prof:
            prof = OperatorProfile(user_id=user_key, sender_name=sender_name, agency_name=agency_name)
            db.add(prof)

        new_val = text.strip()
        if field == "name":
            prof.sender_name = new_val
            field_label = "Sender Name"
        else:
            prof.agency_name = new_val
            field_label = "Business / Agency Name"
        db.commit()

        card_text, buttons = format_profile_card(db, user_key, prof.sender_name, prof.agency_name)
        return {
            "status": "success",
            "reply": f"✅ *{field_label} updated to:* **{new_val}**\n\n" + card_text,
            "buttons": buttons,
        }

    if text == "/profile":
        card_text, buttons = format_profile_card(db, user_key, sender_name, agency_name)
        return {
            "status": "success",
            "reply": card_text,
            "buttons": buttons,
        }

    if text.startswith("/setname"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return {"status": "error", "reply": "Usage: `/setname <Your Name>` (e.g., `/setname Roy`)"}
        new_name = parts[1].strip()
        prof = db.get(OperatorProfile, user_key)
        if not prof:
            prof = OperatorProfile(user_id=user_key, sender_name=new_name, agency_name=agency_name)
            db.add(prof)
        else:
            prof.sender_name = new_name
        db.commit()
        card_text, buttons = format_profile_card(db, user_key, prof.sender_name, prof.agency_name)
        return {
            "status": "success",
            "reply": f"✅ Sender name updated to: *{new_name}*\n\n" + card_text,
            "buttons": buttons,
        }

    if text.startswith("/setagency"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return {"status": "error", "reply": "Usage: `/setagency <Your Agency>` (e.g., `/setagency ori9in.io`)"}
        new_agency = parts[1].strip()
        prof = db.get(OperatorProfile, user_key)
        if not prof:
            prof = OperatorProfile(user_id=user_key, sender_name=sender_name, agency_name=new_agency)
            db.add(prof)
        else:
            prof.agency_name = new_agency
        db.commit()
        card_text, buttons = format_profile_card(db, user_key, prof.sender_name, prof.agency_name)
        return {
            "status": "success",
            "reply": f"✅ Business name updated to: *{new_agency}*\n\n" + card_text,
            "buttons": buttons,
        }

    if text in ("/settings", "/mailboxes"):
        _USER_SETTINGS_SESSIONS.add(user_key)
        reply, buttons = format_settings_dashboard(db, settings, user_key, sender_name, agency_name)
        return {"status": "success", "reply": reply, "buttons": buttons}

    if text.startswith(("/addemailaddress", "/addemailadress", "/addmailbox")):
        if user_key not in _USER_SETTINGS_SESSIONS and user_key not in _USER_AWAITING_MAILBOX_INPUT:
            buttons = [[{"text": "⚙️ Open Settings", "callback_data": "open_settings"}]]
            return {
                "status": "error",
                "reply": (
                    "⚠️ *Settings Mode Required*\n\n"
                    "Adding and managing sending email accounts is configured inside Settings.\n"
                    "Please send `/settings` first (or tap below) to view your pool and unlock adding new email addresses."
                ),
                "buttons": buttons,
            }

        prof = db.get(OperatorProfile, user_key)
        default_sender = prof.sender_name if prof and prof.sender_name else sender_name
        try:
            mb_email, mb_pass, mb_sender = parse_addmailbox_args(text, default_sender=default_sender)
        except ValueError as exc:
            return {
                "status": "error",
                "reply": (
                    "⚠️ *Usage:* `/addemailaddress <email> <app_password>`\n\n"
                    "Example:\n`/addemailaddress outreach@gmail.com abcd efgh ijkl mnop`\n\n"
                    f"_{exc}_"
                ),
            }

        # Live credential verification with Google
        is_valid, err_msg = verify_gmail_credentials(
            email=mb_email,
            password=mb_pass,
            smtp_host=settings.SMTP_HOST or "smtp.gmail.com",
            smtp_port=settings.SMTP_PORT or 587,
        )

        if not is_valid:
            return {
                "status": "auth_failed",
                "reply": (
                    f"❌ *Google Authentication Failed!*\n\n"
                    f"Google rejected credentials for *{mb_email}*:\n"
                    f"_{err_msg}_\n\n"
                    f"🔍 *How to fix:*\n"
                    f"1. Make sure **2-Step Verification** is turned ON at [myaccount.google.com/security](https://myaccount.google.com/security).\n"
                    f"2. Generate a **16-letter App Password** at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).\n"
                    f"3. Do **NOT** use your normal Gmail login password."
                ),
            }

        acc = add_mailbox_account(db, mb_email, mb_pass, sender_name=mb_sender, daily_limit=settings.MAX_EMAILS_PER_DAY)
        _USER_AWAITING_MAILBOX_INPUT.discard(user_key)
        pw_disp = format_app_password(acc.password)
        buttons = [[{"text": "⚙️ View All in Settings", "callback_data": "open_settings"}]]
        return {
            "status": "success",
            "reply": (
                f"✅ *Mailbox Verified & Added to Pool!*\n\n"
                f"• Address: *{acc.email}*\n"
                f"• Status: 🟢 *Connected & Authenticated with Google*\n"
                f"• App Password: `{pw_disp}`\n"
                f"• Sender Name: *{acc.sender_name}*\n"
                f"• Daily Quota: *{acc.daily_limit} emails/day*\n\n"
                f"Send `/settings` to view all connected inboxes."
            ),
            "buttons": buttons,
        }

    # If awaiting direct mailbox reply from button prompt
    if user_key in _USER_AWAITING_MAILBOX_INPUT and not text.startswith("/"):
        prof = db.get(OperatorProfile, user_key)
        default_sender = prof.sender_name if prof and prof.sender_name else sender_name
        try:
            mb_email, mb_pass, mb_sender = parse_addmailbox_args(text, default_sender=default_sender)
        except ValueError as exc:
            return {
                "status": "error",
                "reply": (
                    "⚠️ *Invalid Format!*\n\n"
                    "Please send your Gmail and 16-letter App Password separated by a space:\n"
                    "`yourname@gmail.com abcd efgh ijkl mnop`\n\n"
                    "_(Or send `/cancel` to abort)_"
                ),
            }

        is_valid, err_msg = verify_gmail_credentials(
            email=mb_email,
            password=mb_pass,
            smtp_host=settings.SMTP_HOST or "smtp.gmail.com",
            smtp_port=settings.SMTP_PORT or 587,
        )
        if not is_valid:
            return {
                "status": "auth_failed",
                "reply": (
                    f"❌ *Google Authentication Failed!*\n\n"
                    f"Google rejected credentials for *{mb_email}*:\n"
                    f"_{err_msg}_\n\n"
                    f"🔍 *How to fix:*\n"
                    f"1. Make sure **2-Step Verification** is ON at [myaccount.google.com/security](https://myaccount.google.com/security).\n"
                    f"2. Generate a **16-letter App Password** at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).\n"
                    f"3. Do **NOT** use your normal Gmail account password.\n\n"
                    f"Send your Gmail & 16-letter App Password again:\n"
                    f"`{mb_email} abcd efgh ijkl mnop`"
                ),
            }

        acc = add_mailbox_account(db, mb_email, mb_pass, sender_name=mb_sender, daily_limit=settings.MAX_EMAILS_PER_DAY)
        _USER_AWAITING_MAILBOX_INPUT.discard(user_key)
        pw_disp = format_app_password(acc.password)
        buttons = [[{"text": "⚙️ View All in Settings", "callback_data": "open_settings"}]]
        return {
            "status": "success",
            "reply": (
                f"✅ *Mailbox Verified & Added to Pool!*\n\n"
                f"• Address: *{acc.email}*\n"
                f"• Status: 🟢 *Connected & Authenticated with Google*\n"
                f"• App Password: `{pw_disp}`\n"
                f"• Sender Name: *{acc.sender_name}*\n"
                f"• Daily Quota: *{acc.daily_limit} emails/day*\n\n"
                f"Send `/settings` to view all connected inboxes."
            ),
            "buttons": buttons,
        }

    if text.startswith(("/deleteemail", "/removemailbox", "/delemail", "/removeemail")):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return {"status": "error", "reply": "Usage: `/deleteemail <email>`"}
        target_em = parts[1].strip()
        ok = remove_mailbox_account(db, target_em)
        buttons = [[{"text": "⚙️ View Settings", "callback_data": "open_settings"}]]
        if ok:
            return {"status": "success", "reply": f"✅ Mailbox *{target_em}* removed from active rotation pool.", "buttons": buttons}
        return {"status": "error", "reply": f"⚠️ Mailbox *{target_em}* was not found in the database pool.", "buttons": buttons}

    if text.startswith("/testmailbox"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return {"status": "error", "reply": "Usage: `/testmailbox <email>`"}
        target_em = parts[1].strip().lower()
        acc = db.query(MailboxAccount).filter_by(email=target_em, is_active=True).first()
        if not acc:
            return {"status": "error", "reply": f"⚠️ Mailbox *{target_em}* not found in active database pool."}

        is_valid, err_msg = verify_gmail_credentials(
            email=acc.email,
            password=acc.password,
            smtp_host=settings.SMTP_HOST or "smtp.gmail.com",
            smtp_port=settings.SMTP_PORT or 587,
        )
        if is_valid:
            return {"status": "success", "reply": f"🟢 *Authentication Valid!* Successfully connected to Google SMTP for *{acc.email}*."}
        else:
            return {"status": "auth_failed", "reply": f"🔴 *Authentication Failed for {acc.email}:*\n_{err_msg}_"}

    if text in ("/setup", "/onboarding"):
        _USER_ONBOARDING_SESSIONS[user_key] = {"step": "awaiting_sender_name", "trigger_findleads": False}
        return {
            "status": "onboarding_start",
            "reply": (
                "⚙️ *Outreach Profile & Mailbox Setup*\n\n"
                "👤 *Step 1/3: What is your Name?* (Sender Name)\n"
                "_(e.g., Roy | Alex | Sarah)_"
            ),
        }

    # Handle Active Onboarding Session (Step 1, Step 2, Step 3)
    if user_key in _USER_ONBOARDING_SESSIONS and (not text.startswith("/") or text == "/skip"):
        session = _USER_ONBOARDING_SESSIONS[user_key]
        step = session.get("step")

        if step == "awaiting_sender_name":
            entered_name = text.strip()
            session["sender_name"] = entered_name
            session["step"] = "awaiting_agency_name"
            reply = (
                f"✅ Nice to meet you, *{entered_name}*!\n\n"
                f"🏢 *Step 2/3: What is your Agency or Business Name?*\n"
                f"This will be used as the signing company for all outreach messages and audit proposals.\n"
                f"_(e.g., ori9in.io | Apex Digital | Zenith Systems)_"
            )
            return {"status": "onboarding_step", "reply": reply}

        elif step == "awaiting_agency_name":
            entered_agency = text.strip()
            session["agency_name"] = entered_agency
            session["step"] = "awaiting_mailbox"
            reply = (
                f"✅ Got it! *{entered_agency}* configured.\n\n"
                f"📧 *Step 3/3: Connect Outreach Gmail & Password*\n"
                f"To send automated outreach, let's connect your sending Gmail account. This will be stored as your default settings.\n\n"
                f"Please send your Gmail address and 16-letter App Password in this exact format:\n"
                f"`<email> <app_password>`\n\n"
                f"*Example:*\n"
                f"`outreach@gmail.com abcd efgh ijkl mnop`\n\n"
                f"🔑 *How to get your Google App Password:*\n"
                f"1. Turn ON **2-Step Verification** at [myaccount.google.com/security](https://myaccount.google.com/security)\n"
                f"2. Generate a 16-letter App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)\n"
                f"3. Copy the 16 letters and send them here!\n\n"
                f"💡 _Tip: If you want to connect your email later, send `/skip`._"
            )
            return {"status": "onboarding_step", "reply": reply}

        elif step == "awaiting_mailbox":
            entered_name = session.get("sender_name", sender_name)
            entered_agency = session.get("agency_name", agency_name)
            trigger_findleads = session.get("trigger_findleads", True)

            if text.strip().lower() == "/skip":
                prof = db.get(OperatorProfile, user_key)
                if not prof:
                    prof = OperatorProfile(user_id=user_key, sender_name=entered_name, agency_name=entered_agency)
                    db.add(prof)
                else:
                    prof.sender_name = entered_name
                    prof.agency_name = entered_agency
                db.commit()
                _USER_ONBOARDING_SESSIONS.pop(user_key, None)

                commands_menu = format_commands_menu(entered_name, entered_agency)
                base_reply = (
                    f"🎉 *Setup Complete! Permanent Profile Stored:*\n\n"
                    f"• 👤 Sender Name: *{entered_name}*\n"
                    f"• 🏢 Business / Agency: *{entered_agency}*\n\n"
                    f"💡 *Mailbox skipped:* You can connect your sending Gmail anytime by sending `/settings`.\n\n"
                    f"{commands_menu}\n\n"
                    f"👉 *Ready to find your first clients?* Tap the button below or send `/findleads` to start!"
                )
                buttons = [
                    [
                        {"text": "🎯 Find Clients Now (/findleads)", "callback_data": "start_findleads"},
                        {"text": "⚙️ Connect Gmail (/settings)", "callback_data": "open_settings"},
                    ]
                ]
                return {"status": "success", "reply": base_reply, "buttons": buttons}

            # User provided email + password
            try:
                mb_email, mb_pass, mb_sender = parse_addmailbox_args(text, default_sender=entered_name)
            except ValueError as exc:
                return {
                    "status": "error",
                    "reply": (
                        "⚠️ *Invalid Format!*\n\n"
                        "Please send your Gmail and 16-letter App Password separated by a space:\n"
                        "`yourname@gmail.com abcd efgh ijkl mnop`\n\n"
                        f"_{exc}_\n\n"
                        "_(Or send `/skip` to finish profile setup without email for now)_"
                    ),
                }

            is_valid, err_msg = verify_gmail_credentials(
                email=mb_email,
                password=mb_pass,
                smtp_host=settings.SMTP_HOST or "smtp.gmail.com",
                smtp_port=settings.SMTP_PORT or 587,
            )
            if not is_valid:
                return {
                    "status": "auth_failed",
                    "reply": (
                        f"❌ *Google Authentication Failed!*\n\n"
                        f"Google rejected credentials for *{mb_email}*:\n"
                        f"_{err_msg}_\n\n"
                        f"🔍 *How to fix:*\n"
                        f"1. Make sure **2-Step Verification** is turned ON at [myaccount.google.com/security](https://myaccount.google.com/security).\n"
                        f"2. Generate a **16-letter App Password** at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).\n"
                        f"3. Do **NOT** use your normal Gmail login password.\n\n"
                        f"Send your Gmail & 16-letter App Password again:\n"
                        f"`{mb_email} abcd efgh ijkl mnop`\n"
                        f"_(Or send `/skip` to finish profile setup and connect email later)_"
                    ),
                }

            prof = db.get(OperatorProfile, user_key)
            if not prof:
                prof = OperatorProfile(user_id=user_key, sender_name=entered_name, agency_name=entered_agency)
                db.add(prof)
            else:
                prof.sender_name = entered_name
                prof.agency_name = entered_agency

            acc = add_mailbox_account(db, mb_email, mb_pass, sender_name=entered_name, daily_limit=settings.MAX_EMAILS_PER_DAY)
            db.commit()
            _USER_ONBOARDING_SESSIONS.pop(user_key, None)

            pw_disp = format_app_password(acc.password)
            commands_menu = format_commands_menu(entered_name, entered_agency)
            base_reply = (
                f"🎉 *Setup Complete! Default Profile & Mailbox Configured:*\n\n"
                f"• 👤 Sender Name: *{entered_name}*\n"
                f"• 🏢 Business / Agency: *{entered_agency}*\n"
                f"• 📬 Default Mailbox: 🟢 *{acc.email}* (Connected & Authenticated with Google)\n"
                f"• 🔑 App Password: `{pw_disp}`\n"
                f"• ⏱️ Daily Quota: *{acc.daily_limit} emails/day*\n\n"
                f"{commands_menu}\n\n"
                f"👉 *Ready to find your first clients?* Tap the button below or send `/findleads` to start!"
            )
            buttons = [
                [
                    {"text": "🎯 Find Clients Now (/findleads)", "callback_data": "start_findleads"},
                    {"text": "⚙️ Open Settings", "callback_data": "open_settings"},
                ]
            ]
            return {"status": "success", "reply": base_reply, "buttons": buttons}

    if text in ("/exit", "/pause", "/stop"):
        latest_camp = db.query(Campaign).order_by(Campaign.created_at.desc()).first()
        if latest_camp:
            pending_count = (
                db.query(Lead)
                .filter(Lead.campaign_id == latest_camp.id, Lead.overall_score >= 80, Lead.outreach_status == "draft")
                .count()
            )
            approved_count = (
                db.query(Lead)
                .filter(Lead.campaign_id == latest_camp.id, Lead.outreach_status == "approved")
                .count()
            )
            reply = (
                f"⏸️ *Review Paused*\n\n"
                f"🏢 Campaign: *{latest_camp.niche}* ({latest_camp.location})\n"
                f"• ✅ *{approved_count} approved*\n"
                f"• ⏳ *{pending_count} remaining pending* (Score ≥ 80)\n\n"
                f"Choose your next step below:"
            )
            pause_buttons = []
            if pending_count > 0:
                pause_buttons.append([
                    {"text": f"🚀 Approve All Remaining ({pending_count})", "callback_data": f"bulk_approve:{latest_camp.id}:80"},
                ])
                pause_buttons.append([
                    {"text": f"🔍 Resume Review One-by-One", "callback_data": f"start_review:{latest_camp.id}:80"},
                ])
            pause_buttons.append([
                {"text": "📥 Export CSV", "callback_data": f"export_csv:{latest_camp.id}"},
            ])
            return {"status": "success", "reply": reply, "buttons": pause_buttons}
        return {"status": "success", "reply": "No active campaign to pause."}

    # Handle Active Multi-Step Wizard Session
    if user_key in _USER_WIZARD_SESSIONS and not text.startswith("/"):
        session_data = _USER_WIZARD_SESSIONS[user_key]
        step = session_data.get("step")

        if step == "awaiting_niche":
            session_data["niche"] = text.strip()
            session_data["step"] = "awaiting_location"
            reply = (
                f"✅ Target Niche: *{session_data['niche']}*\n\n"
                f"📍 *Step 2/6: Target Location*\n"
                f"Which city, region, or metropolitan area do you want to prospect?\n"
                f"_(e.g., Delhi, India | Dallas, Texas | London, UK | Mumbai | New York)_"
            )
            return {"status": "in_progress", "reply": reply}

        elif step == "awaiting_location":
            session_data["location"] = text.strip()
            session_data["step"] = "awaiting_services"
            reply = (
                f"✅ Location: *{session_data['location']}*\n\n"
                f"💼 *Step 3/6: Services You Offer*\n"
                f"What services or solutions do you offer as a business/freelancer?\n"
                f"_(e.g., automation system for business: ad managing, leads handling and follow ups, website providing)_"
            )
            return {"status": "in_progress", "reply": reply}

        elif step == "awaiting_services":
            session_data["services"] = text.strip()
            session_data["step"] = "awaiting_quantity"
            reply = (
                f"✅ Services recorded!\n\n"
                f"📊 *Step 4/6: Quantity of Leads*\n"
                f"How many leads would you like to discover?\n"
                f"_(e.g., 10, 25, 50, 100)_"
            )
            return {"status": "in_progress", "reply": reply}

        elif step == "awaiting_quantity":
            try:
                qty_val = int(re.sub(r"[^\d]", "", text) or "50")
            except ValueError:
                qty_val = 50
            session_data["quantity"] = max(1, min(qty_val, 100))
            session_data["step"] = "awaiting_benchmark"
            reply = (
                f"✅ Target quantity: *{session_data['quantity']} leads*\n\n"
                f"⭐ *Step 5/6: Benchmark Qualification Score (0–100)*\n"
                f"What is your minimum qualification score? Only leads scoring at or above this threshold will be qualified!\n\n"
                f"💡 *Scoring Guide for Cold Outreach:*\n"
                f"• *35–45:* 🎯 **Recommended Sweet Spot** (Established businesses with high revenue & clear automation gaps)\n"
                f"• *50–60:* Strict filter (Outdated websites or missing inquiry forms)\n"
                f"• *70+:* Severe gaps (Broken websites or missing phone numbers)\n\n"
                f"_(Reply with e.g. 40 or 50)_"
            )
            return {"status": "in_progress", "reply": reply}

        elif step == "awaiting_benchmark":
            try:
                score_val = int(re.sub(r"[^\d]", "", text) or "80")
            except ValueError:
                score_val = 80
            bench_score = max(0, min(score_val, 100))
            session_data["benchmark"] = bench_score
            session_data["step"] = "awaiting_template_choice"

            reply = (
                f"✅ Benchmark score: *Score ≥ {bench_score}*\n\n"
                f"💬 *Step 6/6: High-Converting Cold Outreach Template*\n"
                f"Would you like to send our proven, highest-response cold outreach message instead of generating personalized AI pitches?\n\n"
                f"📝 *Message Preview:*\n"
                f"\"Hey [Business Name], tried to reach you a few times but didn't hear back . . .\n\n\n"
                f"Where should we go from here?\"\n\n"
                f"• *Reply YES:* Super-fast discovery, universal high-converting message for all leads, no review needed.\n"
                f"• *Reply NO:* Standard system, personalized AI proposal generated for each prospect's website audit.\n\n"
                f"_(Reply with Yes or No, or click a button below)_"
            )
            buttons = [
                [
                    {"text": "✅ Yes (Best-Response Template)", "callback_data": "wizard_template:yes"},
                    {"text": "❌ No (Personalized AI Pitches)", "callback_data": "wizard_template:no"},
                ]
            ]
            return {"status": "in_progress", "reply": reply, "buttons": buttons}

        elif step == "awaiting_template_choice":
            clean_ans = text.strip().lower()
            use_best = clean_ans in ("yes", "y", "true", "1", "best", "template")
            return _execute_wizard_campaign(
                db=db,
                settings=settings,
                user_id=user_id,
                user_key=user_key,
                session_data=session_data,
                use_best_response_template=use_best,
                agency_name=agency_name,
                sender_name=sender_name,
            )

    if text in ("/start", "/help"):
        if not has_operator_profile(db, user_key):
            _USER_ONBOARDING_SESSIONS[user_key] = {"step": "awaiting_sender_name", "trigger_findleads": True}
            welcome_text = (
                "👋 *Welcome to IntentLead AI Universal Operator Bot!*\n\n"
                "Before we begin finding high-intent clients, let's configure your default outreach settings.\n"
                "*This is only asked once on your first chat and saved permanently as your default profile.*\n\n"
                "👤 *Step 1/3: What is your Name?* (Sender Name)\n"
                "_(e.g., Roy | Alex | Sarah)_"
            )
            return {"status": "onboarding_start", "reply": welcome_text}

        prof = db.get(OperatorProfile, user_key)
        prof_name = prof.sender_name if prof else sender_name
        prof_agency = prof.agency_name if prof else agency_name
        help_text = format_commands_menu(prof_name, prof_agency)
        buttons = [
            [
                {"text": "🎯 Find Clients (/findleads)", "callback_data": "start_findleads"},
                {"text": "⚙️ Settings", "callback_data": "open_settings"},
            ],
            [
                {"text": "👤 Profile", "callback_data": "open_profile"},
            ],
        ]
        return {"status": "success", "reply": help_text, "buttons": buttons}

    if text == "/status":
        campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).limit(5).all()
        if not campaigns:
            return {"status": "success", "reply": "No campaigns found."}
        lines = ["📊 *Recent Campaigns:*"]
        for c in campaigns:
            leads_count = db.query(Lead).filter_by(campaign_id=c.id).count()
            lines.append(f"• *{c.niche}* ({c.location}): {c.status} — {leads_count} leads")
        return {"status": "success", "reply": "\n".join(lines)}

    if text.startswith("/showpriority"):
        parts = text.split(maxsplit=1)
        band = parts[1].strip().upper() if len(parts) > 1 else "A"
        leads = (
            db.query(Lead, Business)
            .join(Business, Lead.business_id == Business.id)
            .filter(Lead.priority == band)
            .order_by(Lead.overall_score.desc())
            .limit(10)
            .all()
        )
        if not leads:
            return {"status": "success", "reply": f"No leads found in Priority band {band}."}
        lines = [f"🏆 *Priority {band} Leads:*"]
        for l, b in leads:
            lines.append(f"• *{b.name}* — Score: {l.overall_score}/100 | Svc: {l.recommended_service or 'None'}")
            lines.append(f"  ID: `{l.id}`")
        return {"status": "success", "reply": "\n".join(lines)}

    if text.startswith("/card"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return {"status": "error", "reply": "Usage: `/card <lead_id>`"}
        try:
            lead_uuid = uuid.UUID(parts[1].strip())
            lead = db.get(Lead, lead_uuid)
            if not lead:
                return {"status": "error", "reply": f"Lead {lead_uuid} not found"}
            biz = db.get(Business, lead.business_id)
            draft = db.query(MessageDraft).filter_by(lead_id=lead.id).first()
            evs = db.query(Evidence).filter_by(business_id=lead.business_id, campaign_id=lead.campaign_id).all()
            card_text, buttons = format_approval_card(lead, biz, draft, evs)
            return {"status": "success", "reply": card_text, "buttons": buttons}
        except ValueError:
            return {"status": "error", "reply": "Invalid lead UUID format"}

    if text.startswith("/approve_campaign"):
        parts = text.split()
        camp = None
        min_score = 80
        if len(parts) > 1:
            try:
                camp = db.get(Campaign, uuid.UUID(parts[1].strip()))
            except ValueError:
                camp = None
            if len(parts) > 2:
                try:
                    min_score = int(parts[2].strip())
                except ValueError:
                    min_score = 80
        if not camp:
            camp = db.query(Campaign).order_by(Campaign.created_at.desc()).first()
        if not camp:
            return {"status": "error", "reply": "No campaign found to approve."}

        res = approve_entire_campaign(db, camp.id, str(user_id), min_score=min_score)
        return {"status": "success", "reply": res["message"]}

    if text.startswith("/review"):
        parts = text.split()
        camp = None
        min_score = 80
        if len(parts) > 1:
            try:
                camp = db.get(Campaign, uuid.UUID(parts[1].strip()))
            except ValueError:
                camp = None
            if len(parts) > 2:
                try:
                    min_score = int(parts[2].strip())
                except ValueError:
                    min_score = 80
        if not camp:
            camp = db.query(Campaign).order_by(Campaign.created_at.desc()).first()

        camp_id = camp.id if camp else None
        lead, pending_count = get_next_pending_lead(db, campaign_id=camp_id, min_score=min_score)
        if not lead:
            # Check with broader threshold
            lead, pending_count = get_next_pending_lead(db, campaign_id=camp_id, min_score=50)
            if not lead:
                return {
                    "status": "success",
                    "reply": "🎉 *All caught up!* All qualified leads have already been reviewed and approved. Send `/findleads` to run a new search.",
                }

        biz = db.get(Business, lead.business_id)
        draft = db.query(MessageDraft).filter_by(lead_id=lead.id).first()
        evs = db.query(Evidence).filter_by(business_id=lead.business_id, campaign_id=lead.campaign_id).all()

        if settings.USER_LLM_API_KEY and (not draft or not draft.body or "(Draft" in draft.body):
            ai_pitch = generate_gemini_pitch(
                business=biz,
                lead=lead,
                evidence=evs,
                settings=settings,
                agency_name=agency_name,
                sender_name=sender_name,
            )
            if ai_pitch:
                if not draft:
                    draft = MessageDraft(lead_id=lead.id, channel="preview", status="preview", body=ai_pitch, evidence_ids=[])
                    db.add(draft)
                else:
                    draft.body = ai_pitch
                db.flush()

        card_text, buttons = format_approval_card(lead, biz, draft, evs, is_review_mode=True, remaining_count=pending_count)
        return {"status": "success", "reply": card_text, "buttons": buttons}

    if text.startswith("/export_csv"):
        parts = text.split()
        camp: Campaign | None = None
        min_score = 0
        if len(parts) > 1:
            try:
                camp = db.get(Campaign, uuid.UUID(parts[1].strip()))
            except ValueError:
                camp = None
            if len(parts) > 2:
                try:
                    min_score = int(parts[2].strip())
                except ValueError:
                    min_score = 0

        if not camp:
            camp = db.query(Campaign).order_by(Campaign.created_at.desc()).first()

        if not camp:
            return {"status": "error", "reply": "No campaign found to export."}

        csv_str = generate_campaign_csv(db, camp.id, min_score=min_score)
        filename = f"intentlead_{camp.niche.replace(' ', '_').lower()}_{camp.id}.csv"

        if settings.TELEGRAM_BOT_TOKEN and user_id:
            send_telegram_document(
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                chat_id=user_id,
                file_bytes=csv_str.encode("utf-8"),
                filename=filename,
                caption=f"📄 Leads CSV for {camp.niche} in {camp.location} (Min Score: {min_score})",
            )

        reply = f"✅ Exported CSV for *{camp.niche}* ({camp.location}).\nCampaign ID: `{camp.id}`"
        return {
            "status": "success",
            "reply": reply,
            "filename": filename,
            "csv_content": csv_str,
        }

    if text.startswith("/dispatch"):
        parts = text.split()
        camp = None
        if len(parts) > 1:
            try:
                camp = db.get(Campaign, uuid.UUID(parts[1].strip()))
            except ValueError:
                camp = None

        if not camp:
            camp = db.query(Campaign).order_by(Campaign.created_at.desc()).first()

        if not camp:
            return {"status": "error", "reply": "No campaign found to dispatch."}

        summary = dispatch_approved_campaign_leads(
            db=db,
            campaign_id=camp.id,
            settings=settings,
            agency_name=agency_name,
            sender_name=sender_name,
        )
        mode_label = "🟡 DRY-RUN (Simulated)" if settings.OUTREACH_DRY_RUN else "🟢 LIVE"
        reply = (
            f"📨 *Outreach Dispatch Completed!*\n\n"
            f"🏢 Campaign: *{camp.niche}* ({camp.location})\n"
            f"• Safety Mode: *{mode_label}*\n"
            f"• Provider: *{(settings.EMAIL_PROVIDER or 'smtp').upper()}*\n"
            f"• Total Processed: *{summary['total_candidates']}*\n"
            f"• Sent / Simulated: *{summary['sent'] + summary['simulated']}*\n"
            f"• Throttled (Daily Quota): *{summary['throttled']}*\n"
            f"• Bounced (Pre-flight MX): *{summary['bounced']}*\n"
            f"• Suppressed (Unsubscribed): *{summary['suppressed']}*\n"
            f"• Failed: *{summary['failed']}*\n\n"
            f"All outbound messages are tracked in the database."
        )
        return {"status": "success", "reply": reply}

    if text.startswith("/findleads"):
        raw_args = text[len("/findleads"):].strip()

        if not raw_args:
            if not has_operator_profile(db, user_key):
                _USER_ONBOARDING_SESSIONS[user_key] = {"step": "awaiting_sender_name", "trigger_findleads": True}
                return {
                    "status": "onboarding_start",
                    "reply": (
                        "👋 *Quick 1-Time Setup Required*\n\n"
                        "Before launching client discovery, please tell me your identity for the outreach messages.\n"
                        "*This is only asked once on your first chat and saved permanently as default data.*\n\n"
                        "👤 *Step 1/3: What is your Name?* (Sender Name)\n"
                        "_(e.g., Roy | Alex | Sarah)_"
                    ),
                }

            # Start Interactive 6-Step Questionnaire
            _USER_WIZARD_SESSIONS[user_key] = {"step": "awaiting_niche", "data": {}}
            reply = (
                "🎯 *Universal Client Discovery (Step 1/6)*\n\n"
                "Built for any agency or freelancer offering B2B services.\n\n"
                "What is your *target client niche or industry*?\n"
                "_(e.g., Real Estate, Dental Clinics, Law Firms, Roofers, E-commerce, Gyms)_\n\n"
                "💡 _Tip: You can cancel at any time by sending `/cancel`._"
            )
            return {"status": "wizard_step", "reply": reply}

        lines = [line.strip() for line in raw_args.splitlines() if line.strip()]
        kv: dict[str, str] = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                kv[k.strip().lower()] = v.strip()

        bench_score = 0
        services_desc = ""
        use_best_response_template = False

        if "niche" in kv or "location" in kv:
            niche = kv.get("niche") or "Real Estate Agencies"
            location = kv.get("location") or "Dallas, Texas"
            qty_raw = kv.get("quantity") or kv.get("qty") or "25"
            bench_raw = kv.get("benchmark") or kv.get("bench") or kv.get("score") or "0"
            try:
                qty = int(re.sub(r"[^\d]", "", qty_raw) or "25")
            except ValueError:
                qty = 25
            try:
                bench_score = int(re.sub(r"[^\d]", "", bench_raw) or "0")
            except ValueError:
                bench_score = 0
            services_desc = kv.get("services", "")
            target_services = map_service_keywords(services_desc)
            use_best_raw = kv.get("template") or kv.get("best_response") or kv.get("best") or "no"
            use_best_response_template = use_best_raw.lower() in ("yes", "y", "true", "1")
        else:
            match = re.search(r"^(.*?)\s+in\s+(.*?)(?:\s+(\d+))?(?:\s+(\d+))?(?:\s+(yes|no))?$", raw_args, re.IGNORECASE)
            if match:
                niche = match.group(1).strip()
                location = match.group(2).strip()
                qty = int(match.group(3)) if match.group(3) else 25
                bench_score = int(match.group(4)) if match.group(4) else 0
                use_best_response_template = (match.group(5).lower() == "yes") if match.group(5) else False
            else:
                niche = raw_args
                location = "Dallas, Texas"
                qty = 25
            target_services = list(ALL_SERVICES)

        payload = {
            "niche": niche,
            "location": location,
            "requested_quantity": min(max(qty, 1), 100),
            "max_limit": 100,
            "target_services": target_services,
            "filters": {
                "min_score": bench_score,
                "services_desc": services_desc,
                "use_best_response_template": use_best_response_template,
            },
            "provider": settings.DISCOVERY_PROVIDER,
        }

        if settings.TELEGRAM_BOT_TOKEN and user_id:
            send_telegram_text(
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                chat_id=user_id,
                text=(
                    f"⏳ *Campaign Queued & Processing!*\n\n"
                    f"• Target Niche: *{niche}*\n"
                    f"• Location: *{location}*\n"
                    f"• Benchmark Filter: *Score ≥ {bench_score}*\n"
                    f"• Outreach Mode: *{'🟢 LIVE (Real Sending)' if not settings.OUTREACH_DRY_RUN else '🟡 DRY-RUN (Simulated)'}*\n\n"
                    f"🔍 Discovering businesses and auditing websites for {agency_name} now...\n"
                    f"Your scored leads and `.csv` file will be sent here shortly!"
                ),
            )

        try:
            leftovers = check_existing_leftover_leads(db, niche, location, min_score=bench_score)
            leftover_msg = ""
            consumed_count = 0
            scrape_gap = qty

            camp = create_campaign(db, payload, settings)
            camp.target_sent_emails = qty
            camp.total_sent_emails = 0
            camp.sub_campaign_index = 1
            camp.is_auto_mode = False
            db.commit()

            if settings.TELEGRAM_BOT_TOKEN and user_id:
                send_telegram_text(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=user_id,
                    text=(
                        f"🔍 *Initiating Client Discovery...*\n\n"
                        f"• Target Niche: *{niche}*\n"
                        f"• Location: *{location}*\n"
                        f"• Target Sent Emails: *{qty}*\n"
                        f"• Benchmark Filter: *Score ≥ {bench_score}*\n\n"
                        f"⚡ Searching Google Maps & auditing prospect websites in real-time. Please stand by..."
                    ),
                )

            if leftovers:
                consumed_count = consume_leftover_leads(db, camp.id, leftovers[:qty])
                scrape_gap = max(0, qty - consumed_count)
                leftover_msg = (
                    f"\n🎯 *Smart Rollover Activated!*\n"
                    f"Loaded *{consumed_count}* uncontacted qualified leads from your previous {niche} campaign.\n"
                    f"Remaining fresh leads to discover: *{scrape_gap}*.\n"
                )

            if scrape_gap > 0:
                run_campaign(
                    db,
                    camp.id,
                    settings,
                    agency_name=agency_name,
                    sender_name=sender_name,
                    target_count=qty,
                )
        except Exception as exc:
            if settings.TELEGRAM_BOT_TOKEN and user_id:
                send_telegram_text(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=user_id,
                    text=f"⚠️ *Campaign Notice:* {exc}\nPlease check `/status` or send `/findleads` to retry.",
                )
            raise

        total_leads = db.query(Lead).filter_by(campaign_id=camp.id).count()
        matching_leads = (
            db.query(Lead)
            .filter(
                Lead.campaign_id == camp.id,
                Lead.overall_score >= bench_score,
                Lead.outreach_status.in_(["draft", "approved"]),
            )
            .count()
            if bench_score > 0
            else total_leads
        )

        # If search area is exhausted before filling Sub-Campaign 1 with the requested quantity -> ask for expansion
        if matching_leads < qty and camp.is_exhausted:
            if matching_leads == 0 and total_leads == 0:
                buttons = []
                reply = (
                    f"🚀 *Campaign Launched & Scored!*\n\n"
                    f"⚠️ *No Businesses Found for Location: '{location}'*\n\n"
                    f"• Target Niche: *{niche}*\n"
                    f"• Location Searched: *{location}*\n"
                    f"• Businesses Audited: *0*\n\n"
                    f"Google Maps was unable to find any physical business listings for '{location}'.\n\n"
                    f"💡 *Tip:* Google Maps operates on physical cities, towns, or metropolitan areas (e.g., *Delhi, Mumbai, Dallas, London, New York*).\n\n"
                    f"👉 Please retry with `/findleads` and specify a real city or region!"
                )
                return {
                    "status": "exhausted",
                    "reply": reply,
                    "buttons": buttons,
                    "campaign_id": str(camp.id),
                    "matching_leads": 0,
                }

            next_loc = get_next_expansion_location(camp.location, camp.expanded_locations)
            prompt, buttons = build_expansion_prompt(
                camp=camp,
                current_search_loc=location,
                next_loc=next_loc,
                qualified_count=matching_leads,
                target_count=qty,
                bench_score=bench_score,
            )
            return {
                "status": "paused_exhaustion",
                "reply": prompt,
                "buttons": buttons,
                "campaign_id": str(camp.id),
                "matching_leads": matching_leads,
            }

        delivered_count = min(matching_leads, qty) if qty > 0 else matching_leads

        csv_str = generate_campaign_csv(db, camp.id, min_score=bench_score, limit=qty, only_unattempted=True)
        filename = f"Sub_Campaign_1_Preview.csv"

        buttons = None
        if matching_leads > 0:
            if settings.TELEGRAM_BOT_TOKEN and user_id:
                caption = f"📄 Sub-Campaign 1 Preview: {delivered_count} qualified leads ready (Score ≥ {bench_score})"
                send_telegram_document(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=user_id,
                    file_bytes=csv_str.encode("utf-8"),
                    filename=filename,
                    caption=caption,
                )

            use_best_template = camp.filters.get("use_best_response_template", False) if isinstance(camp.filters, dict) else False
            row1 = [{"text": "🚀 Approve Batch 1", "callback_data": f"subcamp_approve:{camp.id}:1"}]
            if not use_best_template:
                row1.append({"text": "🔍 Review 1-by-1", "callback_data": f"start_review:{camp.id}:{bench_score}"})
            buttons = [
                row1,
                [
                    {"text": "🤖 Auto Mode (Run All Next Loops)", "callback_data": f"subcamp_auto:{camp.id}:1"},
                ]
            ]

            review_line = "" if use_best_template else "• *Review 1-by-1*: Inspect each business and pitch card individually\n"
            reply = (
                f"🚀 *Campaign Launched & Scored: Sub-Campaign 1 Ready!*\n\n"
                f"• Target Niche: *{niche}*\n"
                f"• Location: *{location}*\n"
                f"• Target Sent Emails: *{qty}*\n"
                f"• Benchmark Filter: *Score ≥ {bench_score}*\n"
                f"• Batch 1 Qualified Leads: *{delivered_count}* (out of {total_leads} audited across discovery batches){leftover_msg}\n"
                f"• Campaign ID: `{camp.id}`\n\n"
                f"📄 *Attached:* `{filename}`\n"
                f"Top *{delivered_count}* leads ordered by intent score have been sent above!\n\n"
                f"👇 *Choose Outreach Mode:*\n"
                f"• *Approve Batch 1*: Sends current batch, then generates Sub-Campaign 2\n"
                f"{review_line}"
                f"• *Auto Mode*: Autonomous background loop until {qty} emails are delivered!"
            )
        elif total_leads == 0:
            buttons = []
            reply = (
                f"🚀 *Campaign Launched & Scored!*\n\n"
                f"⚠️ *No Businesses Found for Location: '{location}'*\n\n"
                f"• Target Niche: *{niche}*\n"
                f"• Location Searched: *{location}*\n"
                f"• Businesses Audited: *0*\n\n"
                f"Google Maps was unable to find any physical business listings for '{location}'.\n\n"
                f"💡 *Tip:* Google Maps operates on physical cities, towns, or metropolitan areas (e.g., *Delhi, Mumbai, Dallas, London, New York*).\n\n"
                f"👉 Please retry with `/findleads` and specify a real city or region!"
            )
        else:
            max_score = db.query(func.max(Lead.overall_score)).filter(Lead.campaign_id == camp.id).scalar() or 0
            suggested_thresh = 40 if max_score >= 40 else (30 if max_score >= 30 else max_score)
            viable_count = db.query(Lead).filter(Lead.campaign_id == camp.id, Lead.overall_score >= suggested_thresh).count()

            buttons = []
            if viable_count > 0:
                buttons.append([
                    {"text": f"🎯 Qualify Top {viable_count} Leads (Score ≥ {suggested_thresh})", "callback_data": f"adjust_threshold:{camp.id}:{suggested_thresh}"}
                ])
            buttons.append([
                {"text": "🌍 Expand Search Radius to Nearby Areas", "callback_data": f"expand_radius:{camp.id}"}
            ])

            reply = (
                f"🚀 *Campaign Launched & Scored!*\n\n"
                f"⚠️ *No Leads Met Score ≥ {bench_score}*\n\n"
                f"• Target Niche: *{niche}*\n"
                f"• Location Searched: *{location}*\n"
                f"• Businesses Audited: *{total_leads}*\n"
                f"• Highest Score Found: *{max_score}/100*\n\n"
                f"💡 *Why this happened:*\n"
                f"The {total_leads} businesses found in {location} are established with live websites, so their automation & digital gap scores average between 35 and 50. A score of {bench_score}+ is too high for this market.\n\n"
                f"👇 *Choose an option below:*\n"
                f"• Tap below to qualify the top *{viable_count}* leads (Score ≥ {suggested_thresh})\n"
                f"• Or expand search radius to nearby areas"
            )
        return {
            "status": "success",
            "reply": reply,
            "buttons": buttons,
            "filename": filename,
            "csv_content": csv_str,
            "campaign_id": str(camp.id),
            "matching_leads": matching_leads,
        }

    if not has_operator_profile(db, user_key) and user_key not in _USER_WIZARD_SESSIONS:
        _USER_ONBOARDING_SESSIONS[user_key] = {"step": "awaiting_sender_name", "trigger_findleads": True}
        return {
            "status": "onboarding_start",
            "reply": (
                "👋 *Welcome to IntentLead AI!*\n\n"
                "Before we begin, let's configure your outreach settings (asked only once on your first chat):\n\n"
                "👤 *Step 1/3: What is your Name?* (Sender Name)\n"
                "_(e.g., Roy | Alex | Sarah)_"
            ),
        }

    return {"status": "unknown_command", "reply": "Unrecognized command. Type `/help` for options."}
