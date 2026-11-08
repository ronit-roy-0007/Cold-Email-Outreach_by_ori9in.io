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


def generate_campaign_csv(
    db: Session,
    campaign_id: uuid.UUID,
    min_score: int = 0,
    limit: int = 0,
) -> str:
    query = (
        db.query(Lead, Business)
        .join(Business, Lead.business_id == Business.id)
        .filter(Lead.campaign_id == campaign_id)
    )
    if min_score > 0:
        query = query.filter(Lead.overall_score >= min_score)

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
        "benchmark_met",
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

    for rank, (lead, biz) in enumerate(leads, start=1):
        dims = db.query(DimensionScore).filter_by(lead_id=lead.id).all()
        reason_codes = "; ".join(f"{d.dimension}:{d.reason_code}" for d in dims)
        writer.writerow([
            rank,
            biz.name,
            biz.locality or biz.address or "",
            lead.overall_score,
            f"Yes (>={min_score})" if min_score > 0 else "All",
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
    user_key = str(user_id)

    if not text:
        return {"status": "empty", "message": "No text in message"}

    if text in ("/cancel", "/reset"):
        if user_key in _USER_WIZARD_SESSIONS:
            _USER_WIZARD_SESSIONS.pop(user_key, None)
            return {
                "status": "cancelled",
                "reply": "❌ Campaign setup cancelled. Send `/findleads` whenever you are ready!",
            }
        return {"status": "cancelled", "reply": "No active campaign setup in progress."}

    # Handle Active Multi-Step Wizard Session
    if user_key in _USER_WIZARD_SESSIONS and not text.startswith("/"):
        session_data = _USER_WIZARD_SESSIONS[user_key]
        step = session_data.get("step")

        if step == "awaiting_niche":
            session_data["niche"] = text.strip()
            session_data["step"] = "awaiting_location"
            reply = (
                f"✅ Target Niche: *{session_data['niche']}*\n\n"
                f"📍 *Step 2/5: Target Location*\n"
                f"Which city, region, or country do you want to prospect?\n"
                f"_(e.g., Dallas, Texas | London, UK | Miami, FL | Nationwide)_"
            )
            return {"status": "in_progress", "reply": reply}

        elif step == "awaiting_location":
            session_data["location"] = text.strip()
            session_data["step"] = "awaiting_services"
            reply = (
                f"✅ Location: *{session_data['location']}*\n\n"
                f"💼 *Step 3/5: Services You Offer*\n"
                f"What services or solutions do you offer as a business/freelancer?\n"
                f"_(e.g., automation system for business: ad managing, leads handling and follow ups, website providing)_"
            )
            return {"status": "in_progress", "reply": reply}

        elif step == "awaiting_services":
            session_data["services"] = text.strip()
            session_data["step"] = "awaiting_quantity"
            reply = (
                f"✅ Services recorded!\n\n"
                f"📊 *Step 4/5: Quantity of Leads*\n"
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
                f"⭐ *Step 5/5: Benchmark Qualification Score (0–100)*\n"
                f"What is your minimum qualification score? Only leads scoring at or above this threshold will be exported in your CSV!\n"
                f"_(e.g., 80 for high-intent priority only, 70 for good fit, 50 for broad net)_"
            )
            return {"status": "in_progress", "reply": reply}

        elif step == "awaiting_benchmark":
            try:
                score_val = int(re.sub(r"[^\d]", "", text) or "80")
            except ValueError:
                score_val = 80
            bench_score = max(0, min(score_val, 100))

            niche = session_data.get("niche", "Real Estate")
            location = session_data.get("location", "Dallas, Texas")
            services_desc = session_data.get("services", "")
            qty = session_data.get("quantity", 50)

            _USER_WIZARD_SESSIONS.pop(user_key, None)
            target_services = map_service_keywords(services_desc)

            payload = {
                "niche": niche,
                "location": location,
                "requested_quantity": qty,
                "max_limit": 100,
                "target_services": target_services,
                "filters": {"min_score": bench_score, "services_desc": services_desc},
                "provider": settings.DISCOVERY_PROVIDER,
            }

            # Send immediate acknowledgement to user
            if settings.TELEGRAM_BOT_TOKEN and user_id:
                send_telegram_text(
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    chat_id=user_id,
                    text=(
                        f"⏳ *Campaign Queued & Processing!*\n\n"
                        f"• Target Niche: *{niche}*\n"
                        f"• Location: *{location}*\n"
                        f"• Benchmark Filter: *Score ≥ {bench_score}*\n\n"
                        f"🔍 Discovering businesses and auditing websites for {settings.AGENCY_NAME} now...\n"
                        f"Your scored leads and `.csv` file will be sent here shortly!"
                    ),
                )

            try:
                camp = create_campaign(db, payload, settings)
                run_campaign(db, camp.id, settings)
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
            filename = f"intentlead_{niche.replace(' ', '_').lower()}_bench{bench_score}_{camp.id}.csv"

            if matching_leads > 0:
                if settings.TELEGRAM_BOT_TOKEN and user_id:
                    caption = f"📄 Leads CSV: {min(matching_leads, qty)} qualified leads matching Benchmark Score ≥ {bench_score} (Ranked #1 to #{min(matching_leads, qty)})"
                    send_telegram_document(
                        bot_token=settings.TELEGRAM_BOT_TOKEN,
                        chat_id=user_id,
                        file_bytes=csv_str.encode("utf-8"),
                        filename=filename,
                        caption=caption,
                    )

                reply = (
                    f"🚀 *Campaign Completed & Scored!*\n\n"
                    f"• Target Niche: *{niche}*\n"
                    f"• Location: *{location}*\n"
                    f"• Services Offered: *{services_desc or 'Full Automation Suite'}*\n"
                    f"• Benchmark Threshold: *Score ≥ {bench_score}*\n"
                    f"• Qualified Leads Matching Benchmark: *{matching_leads}* (out of {total_leads} audited across discovery batches)\n"
                    f"• Campaign ID: `{camp.id}`\n\n"
                    f"📄 *Delivered CSV:* `{filename}`\n"
                    f"Top *{min(matching_leads, qty)}* leads strictly ordered in descending intent score with rankings 1–{min(matching_leads, qty)} have been sent above!\n\n"
                    f"Use `/showpriority A` or `/export_csv` to inspect anytime."
                )
            else:
                reply = (
                    f"⚠️ *No Leads Met Score Threshold*\n\n"
                    f"• Target Niche: *{niche}*\n"
                    f"• Location: *{location}*\n"
                    f"• Benchmark Threshold: *Score ≥ {bench_score}*\n"
                    f"• Businesses Audited: *{total_leads}*\n\n"
                    f"None of the audited candidates reached Score ≥ {bench_score}.\n"
                    f"💡 *Recommendation:* Send `/findleads` and set a broader benchmark score (e.g., 70 or 75)."
                )

            return {
                "status": "success",
                "reply": reply,
                "filename": filename,
                "csv_content": csv_str,
                "campaign_id": str(camp.id),
                "matching_leads": matching_leads,
            }

    if text in ("/start", "/help"):
        help_text = (
            "🤖 *IntentLead AI Universal Operator Bot*\n\n"
            "Commands:\n"
            "• `/findleads` — Start interactive 5-step campaign wizard\n"
            "• `/findleads <niche> in <location> [qty] [bench_score]` — Quick discovery command\n"
            "• `/cancel` — Cancel active campaign questionnaire\n"
            "• `/status` — View recent campaigns status\n"
            "• `/showpriority <A|B|C|D>` — List leads by priority band\n"
            "• `/card <lead_id>` — Show interactive approval card\n"
            "• `/export_csv [campaign_id] [bench_score]` — Export leads CSV directly to chat\n"
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

    if text.startswith("/findleads"):
        raw_args = text[len("/findleads"):].strip()

        if not raw_args:
            # Start Interactive 5-Step Questionnaire
            _USER_WIZARD_SESSIONS[user_key] = {"step": "awaiting_niche", "data": {}}
            reply = (
                "🎯 *Universal Client Discovery (Step 1/5)*\n\n"
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
        else:
            match = re.search(r"^(.*?)\s+in\s+(.*?)(?:\s+(\d+))?(?:\s+(\d+))?$", raw_args, re.IGNORECASE)
            if match:
                niche = match.group(1).strip()
                location = match.group(2).strip()
                qty = int(match.group(3)) if match.group(3) else 25
                bench_score = int(match.group(4)) if match.group(4) else 0
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
            "filters": {"min_score": bench_score, "services_desc": services_desc},
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
                    f"• Benchmark Filter: *Score ≥ {bench_score}*\n\n"
                    f"🔍 Discovering businesses and auditing websites for {settings.AGENCY_NAME} now...\n"
                    f"Your scored leads and `.csv` file will be sent here shortly!"
                ),
            )

        try:
            camp = create_campaign(db, payload, settings)
            run_campaign(db, camp.id, settings)
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
            if bench_score > 0
            else total_leads
        )

        csv_str = generate_campaign_csv(db, camp.id, min_score=bench_score, limit=qty)
        filename = f"intentlead_{niche.replace(' ', '_').lower()}_bench{bench_score}_{camp.id}.csv"

        if settings.TELEGRAM_BOT_TOKEN and user_id:
            caption = f"📄 Leads CSV: {matching_leads} prospects scored for {niche} (Score ≥ {bench_score})"
            send_telegram_document(
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                chat_id=user_id,
                file_bytes=csv_str.encode("utf-8"),
                filename=filename,
                caption=caption,
            )

        reply = (
            f"🚀 *Campaign Launched & Scored!*\n\n"
            f"• Target: *{niche}* in *{location}*\n"
            f"• Benchmark Filter: *Score ≥ {bench_score}*\n"
            f"• Scored Leads Meeting Benchmark: *{matching_leads}* (out of {total_leads} audited)\n"
            f"• Campaign ID: `{camp.id}`\n\n"
            f"📄 CSV generated: `{filename}`\n"
            f"Use `/showpriority A` or `/card <lead_id>` to inspect."
        )
        return {
            "status": "success",
            "reply": reply,
            "filename": filename,
            "csv_content": csv_str,
            "campaign_id": str(camp.id),
            "matching_leads": matching_leads,
        }

    return {"status": "unknown_command", "reply": "Unrecognized command. Type `/help` for options."}
