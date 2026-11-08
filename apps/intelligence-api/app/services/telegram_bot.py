from __future__ import annotations

import csv
import io
import re
from typing import Any
import uuid

import httpx
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Approval, AuditLog, Business, Campaign, DimensionScore, Evidence, Lead, MessageDraft
from app.services.campaigns import create_campaign
from app.services.pipeline import run_campaign


def format_approval_card(
    lead: Lead,
    biz: Business,
    draft: MessageDraft | None,
    evidence: list[Evidence],
) -> tuple[str, list[list[dict[str, str]]]]:
    rec_svc = (lead.recommended_service or "None (< 40)").replace("_", " ")

    verified_gaps = [
        e.claim
        for e in evidence
        if e.evidence_type in ("verified_observation", "explicit_intent")
    ]
    gaps_text = "\n".join(f"• {g}" for g in verified_gaps[:3]) if verified_gaps else "• No visible gaps verified"

    draft_text = draft.body if draft and draft.body else "(Draft not recommended: " + (draft.not_recommended_reason or "criteria not met") + ")"

    card_text = (
        f"🎯 *LEAD APPROVAL CARD (DRY-RUN)*\n\n"
        f"🏢 *{biz.name}*\n"
        f"📍 {biz.locality or biz.address or 'Dallas, Texas'}\n"
        f"🌐 Website: {biz.website or 'None'}\n"
        f"📞 Phone: {biz.phone or 'None'}\n\n"
        f"⭐ *Priority {lead.priority}* — Score: *{lead.overall_score}/100* ({lead.confidence} confidence)\n"
        f"💼 *Recommended Service:* {rec_svc}\n\n"
        f"🔍 *Key Verified Evidence:*\n{gaps_text}\n\n"
        f"📝 *Outreach Draft Preview:*\n```\n{draft_text}\n```\n\n"
        f"⚠️ _Outreach is in dry-run mode. Approving marks the lead as approved in CRM without live sending._"
    )

    buttons = [
        [
            {"text": "✅ Approve", "callback_data": f"approve:{lead.id}"},
            {"text": "⏭️ Skip", "callback_data": f"skip:{lead.id}"},
            {"text": "❌ Reject", "callback_data": f"reject:{lead.id}"},
        ]
    ]

    return card_text, buttons


def generate_campaign_csv(db: Session, campaign_id: uuid.UUID) -> str:
    leads = (
        db.query(Lead, Business)
        .join(Business, Lead.business_id == Business.id)
        .filter(Lead.campaign_id == campaign_id)
        .order_by(Lead.overall_score.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "name",
        "location",
        "overall_score",
        "priority",
        "confidence",
        "recommended_service",
        "discovery_source",
        "reason_codes",
        "website",
        "phone",
        "email",
        "outreach_status",
    ])

    for lead, biz in leads:
        dims = db.query(DimensionScore).filter_by(lead_id=lead.id).all()
        reason_codes = "; ".join(f"{d.dimension}:{d.reason_code}" for d in dims)
        writer.writerow([
            biz.name,
            biz.locality or biz.address or "",
            lead.overall_score,
            lead.priority,
            lead.confidence,
            lead.recommended_service or "",
            biz.discovery_source,
            reason_codes,
            biz.website or "",
            biz.phone or "",
            biz.email or "",
            lead.outreach_status,
        ])

    return output.getvalue()


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
        if ":" in cb_data:
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

    if not text:
        return {"status": "empty", "message": "No text in message"}

    if text in ("/start", "/help"):
        help_text = (
            "🤖 *IntentLead AI Operator Bot*\n\n"
            "Commands:\n"
            "• `/findleads <niche> in <location> [qty]` — Start discovery campaign\n"
            "• `/status` — View recent campaigns status\n"
            "• `/showpriority <A|B|C|D>` — List leads by priority band\n"
            "• `/card <lead_id>` — Show interactive approval card\n"
            "• `/export_csv [campaign_id]` — Export leads CSV directly to chat\n"
        )
        return {"status": "success", "reply": help_text}

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

    if text.startswith("/export_csv"):
        parts = text.split(maxsplit=1)
        camp: Campaign | None = None
        if len(parts) > 1:
            try:
                camp = db.get(Campaign, uuid.UUID(parts[1].strip()))
            except ValueError:
                return {"status": "error", "reply": "Invalid campaign UUID format"}
        else:
            camp = db.query(Campaign).order_by(Campaign.created_at.desc()).first()

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
                caption=f"📄 Leads CSV for {camp.niche} in {camp.location}",
            )

        reply = f"✅ Exported CSV for *{camp.niche}* ({camp.location}).\nCampaign ID: `{camp.id}`"
        return {
            "status": "success",
            "reply": reply,
            "filename": filename,
            "csv_content": csv_str,
        }

    if text.startswith("/findleads"):
        # Format: /findleads Real Estate Agencies in Dallas, Texas 10
        raw_args = text[len("/findleads"):].strip()
        match = re.search(r"^(.*?)\s+in\s+(.*?)(?:\s+(\d+))?$", raw_args, re.IGNORECASE)
        if match:
            niche = match.group(1).strip()
            location = match.group(2).strip()
            qty = int(match.group(3)) if match.group(3) else 10
        else:
            niche = raw_args if raw_args else "Real Estate Agencies"
            location = "Dallas, Texas"
            qty = 10

        payload = {
            "niche": niche,
            "location": location,
            "requested_quantity": min(max(qty, 1), 25),
            "target_services": ["website_development", "website_redesign", "real_estate_listing_portal"],
            "filters": {},
            "provider": settings.DISCOVERY_PROVIDER,
        }

        camp = create_campaign(db, payload, settings)
        run_campaign(db, camp.id, settings)
        leads_count = db.query(Lead).filter_by(campaign_id=camp.id).count()

        # Generate CSV export
        csv_str = generate_campaign_csv(db, camp.id)
        filename = f"intentlead_{niche.replace(' ', '_').lower()}_{camp.id}.csv"

        if settings.TELEGRAM_BOT_TOKEN and user_id:
            send_telegram_document(
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                chat_id=user_id,
                file_bytes=csv_str.encode("utf-8"),
                filename=filename,
                caption=f"📄 Leads CSV: {leads_count} prospects scored for {niche}",
            )

        reply = (
            f"🚀 *Campaign Launched & Scored!*\n\n"
            f"• Target: *{niche}* in *{location}*\n"
            f"• Scored Leads: *{leads_count}*\n"
            f"• Campaign ID: `{camp.id}`\n\n"
            f"📄 CSV generated: `{filename}`\n"
            f"Use `/showpriority B` or `/card <lead_id>` to inspect."
        )
        return {
            "status": "success",
            "reply": reply,
            "filename": filename,
            "csv_content": csv_str,
            "campaign_id": str(camp.id),
        }

    return {"status": "unknown_command", "reply": "Unrecognized command. Type `/help` for options."}
