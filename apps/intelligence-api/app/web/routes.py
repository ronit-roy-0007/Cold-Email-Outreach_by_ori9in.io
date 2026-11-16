from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
from pathlib import Path
from typing import Any
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import (
    Approval,
    AuditLog,
    Business,
    Campaign,
    DailyDispatchQuota,
    DimensionScore,
    Evidence,
    Lead,
    MailboxAccount,
    MessageDraft,
    OperatorProfile,
    OutboundMessage,
    ScrapeJob,
    ServiceScore,
    SuppressionEntry,
)
from app.services.campaigns import create_campaign, get_campaign, list_campaigns
from app.services.crypto import encrypt_credential
from app.services.pipeline import run_campaign
from app.services.social import get_business_social_links, get_lead_messages, sanitize_website
from app.services.telegram_bot import record_approval

templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))
templates.env.globals.update({"min": min, "max": max})

web_router = APIRouter(tags=["web"])


def get_common_context(db: Session, active_nav: str, settings: Settings) -> dict[str, Any]:
    pending_count = db.query(Lead).filter_by(outreach_status="draft").count()
    return {
        "active_nav": active_nav,
        "pending_count": pending_count,
        "dry_run": settings.OUTREACH_DRY_RUN,
        "app_env": settings.APP_ENV,
        "agency_name": settings.AGENCY_NAME,
        "sender_name": settings.AGENCY_SENDER_NAME,
    }


# ==============================================================================
# 1. OVERVIEW DASHBOARD
# ==============================================================================

@web_router.get("/", response_class=HTMLResponse)
@web_router.get("/overview", response_class=HTMLResponse)
def overview_dashboard(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ctx = get_common_context(db, "overview", settings)

    # Core Metrics
    total_businesses = db.query(Business).count()
    total_leads = db.query(Lead).count()
    pending_approvals = ctx["pending_count"]
    approved_leads = db.query(Lead).filter_by(outreach_status="approved").count()
    total_dispatched = db.query(OutboundMessage).count()
    simulated_dispatched = db.query(OutboundMessage).filter_by(status="simulated").count()
    total_campaigns = db.query(Campaign).count()
    total_suppressed = db.query(SuppressionEntry).count()

    # Recent Campaigns (up to 5)
    recent_campaigns = db.query(Campaign).order_by(desc(Campaign.created_at)).limit(5).all()

    # Recent Audit & Approval Activity (up to 6)
    recent_audits = db.query(AuditLog).order_by(desc(AuditLog.created_at)).limit(6).all()
    recent_approvals = db.query(Approval, Lead, Business).join(Lead, Approval.lead_id == Lead.id).join(Business, Lead.business_id == Business.id).order_by(desc(Approval.created_at)).limit(4).all()

    # Pipeline status distribution
    status_counts = dict(
        db.query(Lead.outreach_status, func.count(Lead.id))
        .group_by(Lead.outreach_status)
        .all()
    )

    ctx.update({
        "total_businesses": total_businesses,
        "total_leads": total_leads,
        "pending_approvals": pending_approvals,
        "approved_leads": approved_leads,
        "total_dispatched": total_dispatched,
        "simulated_dispatched": simulated_dispatched,
        "total_campaigns": total_campaigns,
        "total_suppressed": total_suppressed,
        "recent_campaigns": recent_campaigns,
        "recent_audits": recent_audits,
        "recent_approvals": recent_approvals,
        "status_counts": status_counts,
    })

    return templates.TemplateResponse(request=request, name="overview.html", context=ctx)


# ==============================================================================
# 2. LEAD INTELLIGENCE DIRECTORY & DEEP DIVE
# ==============================================================================

@web_router.get("/leads", response_class=HTMLResponse)
def leads_directory(
    request: Request,
    q: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    campaign_id: str | None = None,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ctx = get_common_context(db, "leads", settings)

    query = db.query(Lead, Business, Campaign).join(Business, Lead.business_id == Business.id).join(Campaign, Lead.campaign_id == Campaign.id)

    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(Business.name.ilike(term) | Business.locality.ilike(term) | Business.email.ilike(term))

    if status and status != "all":
        query = query.filter(Lead.outreach_status == status)

    if priority and priority != "all":
        query = query.filter(Lead.priority == priority)

    if campaign_id and campaign_id != "all":
        try:
            cid = uuid.UUID(campaign_id)
            query = query.filter(Lead.campaign_id == cid)
        except ValueError:
            pass

    rows = query.order_by(desc(Lead.overall_score)).limit(100).all()
    campaigns = list_campaigns(db)

    ctx.update({
        "leads": rows,
        "campaigns": campaigns,
        "q": q or "",
        "selected_status": status or "all",
        "selected_priority": priority or "all",
        "selected_campaign": campaign_id or "all",
        "total_results": len(rows),
    })

    return templates.TemplateResponse(request=request, name="leads.html", context=ctx)


@web_router.get("/leads/{lead_id}", response_class=HTMLResponse)
def lead_detail_view(
    lead_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    ctx = get_common_context(db, "leads", settings)
    biz = db.get(Business, lead.business_id)
    campaign = db.get(Campaign, lead.campaign_id)
    dims = db.query(DimensionScore).filter_by(lead_id=lead_id).all()
    svcs = db.query(ServiceScore).filter_by(lead_id=lead_id).order_by(desc(ServiceScore.points)).all()
    draft = db.query(MessageDraft).filter_by(lead_id=lead_id).first()
    evs = (
        db.query(Evidence)
        .filter_by(business_id=lead.business_id, campaign_id=lead.campaign_id)
        .all()
    )
    socials = get_business_social_links(biz) if biz else {}
    approval_history = db.query(Approval).filter_by(lead_id=lead_id).order_by(desc(Approval.created_at)).all()

    ctx.update({
        "lead": lead,
        "business": biz,
        "campaign": campaign,
        "dimensions": dims,
        "service_scores": svcs,
        "draft": draft,
        "evidence": evs,
        "socials": socials,
        "approval_history": approval_history,
    })

    return templates.TemplateResponse(request=request, name="lead_detail.html", context=ctx)


# ==============================================================================
# 3. APPROVAL CENTER
# ==============================================================================

@web_router.get("/approvals", response_class=HTMLResponse)
def approval_center(
    request: Request,
    campaign_id: str | None = None,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ctx = get_common_context(db, "approvals", settings)

    query = (
        db.query(Lead, Business, Campaign, MessageDraft)
        .join(Business, Lead.business_id == Business.id)
        .join(Campaign, Lead.campaign_id == Campaign.id)
        .outerjoin(MessageDraft, Lead.id == MessageDraft.lead_id)
        .filter(Lead.outreach_status.in_(["draft", "pending"]))
    )

    if campaign_id and campaign_id != "all":
        try:
            cid = uuid.UUID(campaign_id)
            query = query.filter(Lead.campaign_id == cid)
        except ValueError:
            pass

    pending_leads = query.order_by(desc(Lead.overall_score)).all()
    campaigns = list_campaigns(db)

    ctx.update({
        "pending_leads": pending_leads,
        "campaigns": campaigns,
        "selected_campaign": campaign_id or "all",
        "pending_total": len(pending_leads),
    })

    return templates.TemplateResponse(request=request, name="approvals.html", context=ctx)


@web_router.post("/api/web/approvals/{lead_id}")
def web_process_approval(
    lead_id: uuid.UUID,
    payload: dict[str, Any],
    db: Session = Depends(get_session),
):
    user_id = str(payload.get("user_id") or "web_operator")
    action = str(payload.get("action") or "approve")
    res = record_approval(db, lead_id, user_id, action)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Error"))
    return res


# ==============================================================================
# 4. CAMPAIGN MANAGEMENT
# ==============================================================================

@web_router.get("/campaigns", response_class=HTMLResponse)
def campaigns_list_view(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ctx = get_common_context(db, "campaigns", settings)
    campaigns = db.query(Campaign).order_by(desc(Campaign.created_at)).all()

    # Pre-calculate lead statistics per campaign
    campaign_stats = {}
    for c in campaigns:
        total_leads = db.query(Lead).filter_by(campaign_id=c.id).count()
        approved_leads = db.query(Lead).filter_by(campaign_id=c.id, outreach_status="approved").count()
        dispatched_leads = db.query(OutboundMessage).filter_by(campaign_id=c.id).count()
        campaign_stats[c.id] = {
            "total_leads": total_leads,
            "approved_leads": approved_leads,
            "dispatched_leads": dispatched_leads,
        }

    ctx.update({
        "campaigns": campaigns,
        "stats": campaign_stats,
    })

    return templates.TemplateResponse(request=request, name="campaigns.html", context=ctx)


@web_router.get("/campaigns/new", response_class=HTMLResponse)
def new_campaign_form(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ctx = get_common_context(db, "campaigns", settings)
    return templates.TemplateResponse(request=request, name="campaign_new.html", context=ctx)


@web_router.post("/campaigns/new")
def submit_new_campaign(
    request: Request,
    niche: str = Form(...),
    location: str = Form(...),
    requested_quantity: int = Form(...),
    provider: str = Form("mock"),
    target_services: list[str] = Form(...),
    target_sent_emails: int = Form(50),
    auto_mode: bool = Form(False),
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    payload = {
        "niche": niche,
        "location": location,
        "requested_quantity": requested_quantity,
        "provider": provider,
        "target_services": target_services,
        "target_sent_emails": target_sent_emails,
        "is_auto_mode": auto_mode,
        "filters": {},
    }
    camp = create_campaign(db, payload, settings)
    if camp.provider != "import":
        camp = run_campaign(db, camp.id, settings)

    return RedirectResponse(url=f"/campaigns/{camp.id}", status_code=303)


@web_router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
def campaign_detail_view(
    campaign_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    ctx = get_common_context(db, "campaigns", settings)
    leads = (
        db.query(Lead, Business)
        .join(Business, Lead.business_id == Business.id)
        .filter(Lead.campaign_id == campaign_id)
        .order_by(desc(Lead.overall_score))
        .all()
    )
    scrape_job = db.query(ScrapeJob).filter_by(campaign_id=campaign_id).first()

    ctx.update({
        "campaign": campaign,
        "leads": leads,
        "scrape_job": scrape_job,
        "total_leads": len(leads),
        "approved_count": sum(1 for l, _ in leads if l.outreach_status == "approved"),
        "draft_count": sum(1 for l, _ in leads if l.outreach_status == "draft"),
        "sent_count": sum(1 for l, _ in leads if l.outreach_status in ("sent", "simulated")),
    })

    return templates.TemplateResponse(request=request, name="campaign_detail.html", context=ctx)


@web_router.get("/campaigns/{campaign_id}/export.csv")
def export_campaign_csv(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_session),
):
    campaign = get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    leads = (
        db.query(Lead, Business)
        .join(Business, Lead.business_id == Business.id)
        .filter(Lead.campaign_id == campaign_id)
        .order_by(desc(Lead.overall_score))
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "name", "location", "overall_score", "priority", "confidence",
        "recommended_service", "discovery_source", "reason_codes", "website",
        "phone", "email", "address", "linkedin", "facebook", "instagram",
        "twitter", "reddit", "telegram", "drafts", "approved_messages", "outreach_status"
    ])

    for lead, biz in leads:
        dims = db.query(DimensionScore).filter_by(lead_id=lead.id).all()
        reason_codes = "; ".join(f"{d.dimension}:{d.reason_code}" for d in dims)
        clean_site = sanitize_website(biz.name, biz.website)
        socials = get_business_social_links(biz)
        draft_msg, approved_msg = get_lead_messages(db, lead)

        writer.writerow([
            biz.name,
            biz.locality or biz.address or "",
            lead.overall_score,
            lead.priority,
            lead.confidence,
            lead.recommended_service or "",
            biz.discovery_source,
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

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=campaign_{campaign_id}.csv"},
    )


# ==============================================================================
# 5. MAILBOX MANAGEMENT
# ==============================================================================

@web_router.get("/mailboxes", response_class=HTMLResponse)
def mailboxes_view(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ctx = get_common_context(db, "mailboxes", settings)
    mailboxes = db.query(MailboxAccount).order_by(MailboxAccount.created_at).all()
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get quota usage
    mailbox_data = []
    for mb in mailboxes:
        quota = db.query(DailyDispatchQuota).filter_by(sender_mailbox=mb.email, dispatch_date=today_date).first()
        sent_today = quota.count if quota else 0
        remaining = max(0, mb.daily_limit - sent_today)
        mailbox_data.append({
            "account": mb,
            "sent_today": sent_today,
            "remaining": remaining,
            "percent_used": min(100, int((sent_today / max(1, mb.daily_limit)) * 100)),
        })

    ctx.update({
        "mailboxes": mailbox_data,
        "total_active": sum(1 for m in mailboxes if m.is_active),
        "total_capacity": sum(m.daily_limit for m in mailboxes if m.is_active),
    })

    return templates.TemplateResponse(request=request, name="mailboxes.html", context=ctx)


@web_router.post("/mailboxes/new")
def add_mailbox_account(
    email: str = Form(...),
    password: str = Form(...),
    sender_name: str = Form(...),
    daily_limit: int = Form(50),
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    enc_pass = encrypt_credential(password, settings.FIELD_ENCRYPTION_KEY)
    mb = MailboxAccount(
        email=email.strip().lower(),
        password=enc_pass,
        sender_name=sender_name.strip(),
        daily_limit=daily_limit,
        is_active=True,
    )
    db.add(mb)
    db.commit()
    return RedirectResponse(url="/mailboxes", status_code=303)


# ==============================================================================
# 6. ANALYTICS & REPORTING
# ==============================================================================

@web_router.get("/analytics", response_class=HTMLResponse)
def analytics_view(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ctx = get_common_context(db, "analytics", settings)

    total_businesses = db.query(Business).count()
    total_leads = db.query(Lead).count()
    qualification_rate = int((total_leads / max(1, total_businesses)) * 100)

    # Score grade buckets
    grade_a = db.query(Lead).filter(Lead.overall_score >= 80).count()
    grade_b = db.query(Lead).filter(Lead.overall_score >= 65, Lead.overall_score < 80).count()
    grade_c = db.query(Lead).filter(Lead.overall_score < 65).count()

    # Recommended Services distribution
    svc_counts = (
        db.query(Lead.recommended_service, func.count(Lead.id))
        .group_by(Lead.recommended_service)
        .order_by(desc(func.count(Lead.id)))
        .all()
    )

    # Outreach simulation and dispatch outcomes
    dispatches = db.query(OutboundMessage).all()
    simulated = sum(1 for m in dispatches if m.status == "simulated")
    sent = sum(1 for m in dispatches if m.status == "sent")
    failed = sum(1 for m in dispatches if m.status == "failed")
    bounced = sum(1 for m in dispatches if m.status == "bounced")

    ctx.update({
        "total_businesses": total_businesses,
        "total_leads": total_leads,
        "qualification_rate": qualification_rate,
        "grade_a": grade_a,
        "grade_b": grade_b,
        "grade_c": grade_c,
        "service_distribution": svc_counts,
        "simulated_count": simulated,
        "sent_count": sent,
        "failed_count": failed,
        "bounced_count": bounced,
    })

    return templates.TemplateResponse(request=request, name="analytics.html", context=ctx)


# ==============================================================================
# 7. SUPPRESSION LIST MANAGEMENT
# ==============================================================================

@web_router.get("/suppression", response_class=HTMLResponse)
def suppression_view(
    request: Request,
    q: str | None = None,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ctx = get_common_context(db, "suppression", settings)
    query = db.query(SuppressionEntry)

    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(SuppressionEntry.email.ilike(term) | SuppressionEntry.reason.ilike(term))

    entries = query.order_by(desc(SuppressionEntry.created_at)).all()

    ctx.update({
        "entries": entries,
        "q": q or "",
        "total_suppressed": len(entries),
    })

    return templates.TemplateResponse(request=request, name="suppression.html", context=ctx)


@web_router.post("/suppression/add")
def add_manual_suppression(
    email: str = Form(...),
    reason: str = Form("manual"),
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    clean_email = email.strip().lower()
    existing = db.query(SuppressionEntry).filter_by(email=clean_email).first()
    if not existing:
        entry = SuppressionEntry(email=clean_email, reason=reason, source="operator_web_ui")
        db.add(entry)
        db.commit()
    return RedirectResponse(url="/suppression", status_code=303)


# ==============================================================================
# 8. ACTIVITY & AUDIT LOGS
# ==============================================================================

@web_router.get("/activity", response_class=HTMLResponse)
def activity_view(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ctx = get_common_context(db, "activity", settings)
    logs = db.query(AuditLog).order_by(desc(AuditLog.created_at)).limit(100).all()
    approvals = (
        db.query(Approval, Lead, Business)
        .join(Lead, Approval.lead_id == Lead.id)
        .join(Business, Lead.business_id == Business.id)
        .order_by(desc(Approval.created_at))
        .limit(50)
        .all()
    )

    ctx.update({
        "logs": logs,
        "approvals": approvals,
    })

    return templates.TemplateResponse(request=request, name="activity.html", context=ctx)


# ==============================================================================
# 9. SETTINGS & INTEGRATIONS
# ==============================================================================

@web_router.get("/settings", response_class=HTMLResponse)
def settings_view(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ctx = get_common_context(db, "settings", settings)
    profile = db.query(OperatorProfile).first()

    ctx.update({
        "settings": settings,
        "profile": profile,
        "has_encryption_key": bool(settings.FIELD_ENCRYPTION_KEY and settings.FIELD_ENCRYPTION_KEY.strip()),
        "has_telegram_token": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_BOT_TOKEN.strip()),
        "has_telegram_secret": bool(settings.TELEGRAM_WEBHOOK_SECRET and settings.TELEGRAM_WEBHOOK_SECRET.strip()),
        "has_gemini_key": bool(settings.USER_LLM_API_KEY and settings.USER_LLM_API_KEY.strip()),
        "has_webhook_secret": bool(settings.OUTREACH_WEBHOOK_SECRET and settings.OUTREACH_WEBHOOK_SECRET.strip()),
    })

    return templates.TemplateResponse(request=request, name="settings.html", context=ctx)
