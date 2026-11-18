from __future__ import annotations

import csv
from datetime import datetime, timezone
import hmac
import io
import logging
from pathlib import Path
import secrets
from typing import Any
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import (
    Approval,
    AuditLog,
    Business,
    Campaign,
    Conversation,
    ConversationMessage,
    DailyDispatchQuota,
    DimensionScore,
    Evidence,
    FollowUpExecution,
    Lead,
    MailboxAccount,
    MessageDraft,
    OperatorProfile,
    OperatorUser,
    OutboundMessage,
    ScrapeJob,
    ServiceScore,
    SuppressionEntry,
    utc_now,
)
from app.security import extract_client_ip, get_current_operator, require_csrf, require_operator
from app.services.auth import (
    create_operator_session,
    destroy_operator_session,
    generate_csrf_token,
    is_ip_rate_limited,
    record_login_failure,
    record_login_success,
    verify_password,
)
from app.services.campaigns import create_campaign, delete_campaign, get_campaign, list_campaigns
from app.services.crypto import encrypt_credential
from app.services.followup_engine import pause_followups, resume_followups
from app.services.operator_reply import send_operator_reply
from app.services.pipeline import run_campaign
from app.services.social import get_business_social_links, get_lead_messages, sanitize_website
from app.services.telegram_bot import record_approval

logger = logging.getLogger("intentlead.web")

templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))
templates.env.globals.update({"min": min, "max": max})

auth_router = APIRouter(tags=["auth"])
web_router = APIRouter(tags=["web"], dependencies=[Depends(require_operator), Depends(require_csrf)])


def _sanitize_next_url(next_url: str | None) -> str:
    if not next_url:
        return "/"
    clean = next_url.strip()
    if not clean.startswith("/") or clean.startswith("//") or "\\" in clean:
        return "/"
    return clean


# ==============================================================================
# AUTHENTICATION ROUTES (PUBLIC)
# ==============================================================================

@auth_router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next: str | None = None,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    user = get_current_operator(request, db, settings)
    if user:
        return RedirectResponse(url=_sanitize_next_url(next), status_code=status.HTTP_303_SEE_OTHER)

    login_csrf = request.cookies.get("intentlead_login_csrf")
    if not login_csrf:
        login_csrf = secrets.token_urlsafe(32)

    response = templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": None,
            "next_url": _sanitize_next_url(next),
            "username": "",
            "csrf_token": login_csrf,
        },
    )
    response.set_cookie(
        key="intentlead_login_csrf",
        value=login_csrf,
        httponly=True,
        samesite="lax",
        secure=settings.APP_ENV == "production",
        path="/",
    )
    return response


@auth_router.post("/login")
def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    csrf_token: str | None = Form(None),
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    client_ip = extract_client_ip(request, settings.TRUSTED_PROXIES)

    # Mandatory login CSRF validation
    login_csrf_cookie = request.cookies.get("intentlead_login_csrf")
    provided_csrf = request.headers.get("x-csrf-token") or csrf_token

    if not login_csrf_cookie or not str(login_csrf_cookie).strip():
        logger.warning("Login CSRF check failed: missing pre-session cookie from IP %s", client_ip)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Security validation failed. Please refresh the page and try again.",
                "next_url": _sanitize_next_url(next),
                "username": username,
                "csrf_token": "",
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if not provided_csrf or not str(provided_csrf).strip():
        logger.warning("Login CSRF check failed: missing submitted token from IP %s", client_ip)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Security validation failed. Please refresh the page and try again.",
                "next_url": _sanitize_next_url(next),
                "username": username,
                "csrf_token": login_csrf_cookie,
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if not hmac.compare_digest(login_csrf_cookie.strip(), str(provided_csrf).strip()):
        logger.warning("Login CSRF check failed: token mismatch from IP %s", client_ip)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Security validation failed. Please refresh the page and try again.",
                "next_url": _sanitize_next_url(next),
                "username": username,
                "csrf_token": login_csrf_cookie,
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if is_ip_rate_limited(
        client_ip,
        settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    ):
        logger.warning("Login rate limit exceeded for IP %s", client_ip)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Too many failed login attempts. Please wait 15 minutes before trying again.",
                "next_url": _sanitize_next_url(next),
                "username": username,
                "csrf_token": login_csrf_cookie,
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    clean_user = username.strip()
    operator = db.query(OperatorUser).filter_by(username=clean_user, is_active=True).first()

    if not operator or not verify_password(password, operator.password_hash):
        record_login_failure(client_ip)
        logger.warning("Failed login attempt for operator user '%s' from %s", clean_user, client_ip)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Invalid username or password.",
                "next_url": _sanitize_next_url(next),
                "username": username,
                "csrf_token": login_csrf_cookie,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    record_login_success(client_ip)
    session_rec, raw_token = create_operator_session(
        db=db,
        user=operator,
        request=request,
        max_age_seconds=settings.SESSION_MAX_AGE_SECONDS,
    )
    csrf_token = generate_csrf_token(raw_token, settings.SESSION_SECRET_KEY)

    redirect_target = _sanitize_next_url(next)
    response = RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)

    is_prod = settings.APP_ENV == "production"
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=settings.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        path="/",
    )
    response.set_cookie(
        key="intentlead_csrf",
        value=csrf_token,
        max_age=settings.SESSION_MAX_AGE_SECONDS,
        httponly=False,
        samesite="lax",
        secure=is_prod,
        path="/",
    )
    response.delete_cookie("intentlead_login_csrf", path="/")
    logger.info("Operator '%s' logged in successfully from %s", clean_user, client_ip)
    return response


@auth_router.post("/logout")
def logout_action(
    request: Request,
    csrf_token: str | None = Form(None),
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if raw_token:
        from app.services.auth import validate_csrf_token
        provided_csrf = request.headers.get("x-csrf-token") or request.headers.get("x-xsrf-token") or csrf_token
        if not provided_csrf or not validate_csrf_token(raw_token, settings.SESSION_SECRET_KEY, provided_csrf):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token missing or invalid for logout.",
            )
        destroy_operator_session(db, raw_token)

    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    response.delete_cookie("intentlead_csrf", path="/")
    response.delete_cookie("intentlead_login_csrf", path="/")
    return response


@auth_router.get("/logout")
def logout_get_rejected():
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="GET /logout is not supported for security reasons. Submit a POST request with valid CSRF token.",
    )


def get_common_context(
    db: Session,
    active_nav: str,
    settings: Settings,
    request: Request | None = None,
) -> dict[str, Any]:
    pending_count = db.query(Lead).filter_by(outreach_status="draft").count()
    unread_inbox_count = db.query(func.coalesce(func.sum(Conversation.unread_count), 0)).scalar()
    operator = getattr(request.state, "operator_user", None) if (request and hasattr(request, "state")) else None
    raw_token = getattr(request.state, "raw_token", None) if (request and hasattr(request, "state")) else None
    csrf_token = ""
    if raw_token:
        csrf_token = generate_csrf_token(raw_token, settings.SESSION_SECRET_KEY)

    return {
        "active_nav": active_nav,
        "pending_count": pending_count,
        "unread_inbox_count": int(unread_inbox_count or 0),
        "dry_run": settings.OUTREACH_DRY_RUN,
        "app_env": settings.APP_ENV,
        "agency_name": settings.AGENCY_NAME,
        "sender_name": settings.AGENCY_SENDER_NAME,
        "operator_user": operator,
        "csrf_token": csrf_token,
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
    ctx = get_common_context(db, "overview", settings, request=request)

    # Core Metrics (Targets in active campaigns)
    total_businesses = db.query(Business.id).join(Lead, Business.id == Lead.business_id).distinct().count()
    total_leads = db.query(Lead).count()
    pending_approvals = ctx["pending_count"]
    approved_leads = db.query(Lead).filter_by(outreach_status="approved").count()
    total_dispatched = db.query(OutboundMessage).count()
    simulated_dispatched = db.query(OutboundMessage).filter_by(status="simulated").count()
    total_campaigns = db.query(Campaign).count()
    total_suppressed = db.query(SuppressionEntry).count()

    # Conversation & Follow-up Telemetry
    total_conversations = db.query(Conversation).count()
    total_replies = db.query(Conversation).filter(Conversation.status == "replied").count()
    reply_rate = round((total_replies / total_conversations * 100), 1) if total_conversations > 0 else 0.0
    active_followups = db.query(FollowUpExecution).filter(FollowUpExecution.status == "scheduled").count()

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
        "total_conversations": total_conversations,
        "total_replies": total_replies,
        "reply_rate": reply_rate,
        "active_followups": active_followups,
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
    ctx = get_common_context(db, "leads", settings, request=request)

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

    ctx = get_common_context(db, "leads", settings, request=request)
    biz = db.get(Business, lead.business_id)
    campaign = db.get(Campaign, lead.campaign_id)
    dims = db.query(DimensionScore).filter_by(lead_id=lead_id).all()

    # Filter service scores to only the services offered in this campaign
    target_svcs = campaign.target_services if campaign and campaign.target_services else []
    svcs_query = db.query(ServiceScore).filter_by(lead_id=lead_id)
    if target_svcs:
        svcs_query = svcs_query.filter(ServiceScore.service.in_(target_svcs))
    svcs = svcs_query.order_by(desc(ServiceScore.points)).all()

    draft = db.query(MessageDraft).filter_by(lead_id=lead_id).first()

    evs_query = db.query(Evidence).filter_by(business_id=lead.business_id, campaign_id=lead.campaign_id)
    is_real_estate = any(
        k in (((biz.category or "") if biz else "") + " " + ((campaign.niche if campaign else "") or "")).lower()
        for k in ("real estate", "property", "realtor", "broker", "housing")
    )
    if not is_real_estate:
        evs_query = evs_query.filter(Evidence.supporting_excerpt != "missing_listing_search")
    evs = evs_query.all()
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
    ctx = get_common_context(db, "approvals", settings, request=request)

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
    ctx = get_common_context(db, "campaigns", settings, request=request)
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
    ctx = get_common_context(db, "campaigns", settings, request=request)
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

    ctx = get_common_context(db, "campaigns", settings, request=request)
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
        "approved_count": sum(1 for lead, _ in leads if lead.outreach_status == "approved"),
        "draft_count": sum(1 for lead, _ in leads if lead.outreach_status == "draft"),
        "sent_count": sum(1 for lead, _ in leads if lead.outreach_status in ("sent", "simulated")),
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


@web_router.post("/api/web/campaigns/{campaign_id}/delete")
def api_web_delete_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_session),
):
    deleted = delete_campaign(db, campaign_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {
        "status": "success",
        "message": "Campaign and all related data deleted successfully",
        "campaign_id": str(campaign_id),
    }


@web_router.post("/campaigns/{campaign_id}/delete")
def web_delete_campaign_form(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_session),
):
    delete_campaign(db, campaign_id)
    return RedirectResponse(url="/campaigns", status_code=303)


# ==============================================================================
# 5. MAILBOX MANAGEMENT
# ==============================================================================

@web_router.get("/mailboxes", response_class=HTMLResponse)
def mailboxes_view(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ctx = get_common_context(db, "mailboxes", settings, request=request)
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
    ctx = get_common_context(db, "analytics", settings, request=request)

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

    # Conversation and follow-up metrics
    total_conversations = db.query(Conversation).count()
    replied_count = db.query(Conversation).filter(Conversation.status == "replied").count()
    reply_rate = round((replied_count / max(1, total_conversations)) * 100, 1)

    followups_scheduled = db.query(FollowUpExecution).filter(FollowUpExecution.status == "scheduled").count()
    followups_executed = db.query(FollowUpExecution).filter(FollowUpExecution.status == "executed").count()
    followups_cancelled = db.query(FollowUpExecution).filter(FollowUpExecution.status == "cancelled").count()

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
        "total_conversations": total_conversations,
        "replied_count": replied_count,
        "reply_rate": reply_rate,
        "followups_scheduled": followups_scheduled,
        "followups_executed": followups_executed,
        "followups_cancelled": followups_cancelled,
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
    ctx = get_common_context(db, "suppression", settings, request=request)
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
        entry = SuppressionEntry(email=clean_email, reason=reason)
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
    ctx = get_common_context(db, "activity", settings, request=request)
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
    ctx = get_common_context(db, "settings", settings, request=request)
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


# ==============================================================================
# 10. UNIFIED INBOX & CONVERSATION MANAGEMENT
# ==============================================================================

@web_router.get("/inbox", response_class=HTMLResponse)
def inbox_view(
    request: Request,
    conversation_id: str | None = None,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ctx = get_common_context(db, "inbox", settings, request=request)
    campaigns = db.query(Campaign).order_by(desc(Campaign.created_at)).all()

    total_convs = db.query(Conversation).count()
    unread_convs = db.query(Conversation).filter(Conversation.unread_count > 0).count()
    replied_convs = db.query(Conversation).filter(Conversation.status == "replied").count()
    active_convs = db.query(Conversation).filter(Conversation.status == "active").count()

    ctx.update({
        "campaigns": campaigns,
        "total_convs": total_convs,
        "unread_convs": unread_convs,
        "replied_convs": replied_convs,
        "active_convs": active_convs,
        "initial_conversation_id": conversation_id or "",
    })
    return templates.TemplateResponse(request=request, name="inbox.html", context=ctx)


@web_router.get("/api/web/inbox/conversations")
def api_list_conversations(
    q: str | None = None,
    status: str | None = None,
    campaign_id: str | None = None,
    unread_only: bool = False,
    db: Session = Depends(get_session),
):
    query = (
        db.query(Conversation, Business, Campaign, Lead)
        .outerjoin(Business, Conversation.business_id == Business.id)
        .outerjoin(Campaign, Conversation.campaign_id == Campaign.id)
        .outerjoin(Lead, Conversation.lead_id == Lead.id)
    )

    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            Conversation.recipient_email.ilike(term)
            | Conversation.subject.ilike(term)
            | Business.name.ilike(term)
        )

    if status and status.strip() and status.strip().lower() != "all":
        query = query.filter(Conversation.status == status.strip().lower())

    if campaign_id and campaign_id.strip() and campaign_id.strip().lower() != "all":
        try:
            cid = uuid.UUID(campaign_id.strip())
            query = query.filter(Conversation.campaign_id == cid)
        except Exception:
            pass

    if unread_only:
        query = query.filter(Conversation.unread_count > 0)

    results = query.order_by(desc(Conversation.last_message_at)).limit(100).all()

    items = []
    for conv, biz, camp, lead in results:
        latest_msg = (
            db.query(ConversationMessage)
            .filter_by(conversation_id=conv.id)
            .order_by(desc(ConversationMessage.created_at))
            .first()
        )
        snippet = latest_msg.body[:120] if latest_msg else ""
        direction = latest_msg.direction if latest_msg else "outbound"

        items.append({
            "id": str(conv.id),
            "recipient_email": conv.recipient_email,
            "subject": conv.subject,
            "status": conv.status,
            "unread_count": conv.unread_count,
            "followup_status": conv.followup_status,
            "followup_step": conv.followup_step,
            "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else "",
            "business_name": biz.name if biz else (conv.recipient_email.split("@")[0].capitalize()),
            "lead_id": str(lead.id) if lead else None,
            "lead_score": lead.overall_score if lead else None,
            "campaign_name": camp.niche if camp else "Direct Outreach",
            "snippet": snippet,
            "direction": direction,
        })

    return {"conversations": items, "count": len(items)}


@web_router.get("/api/web/inbox/conversations/{conversation_id}")
def api_get_conversation_detail(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_session),
):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    biz = db.get(Business, conv.business_id) if conv.business_id else None
    camp = db.get(Campaign, conv.campaign_id) if conv.campaign_id else None
    lead = db.get(Lead, conv.lead_id) if conv.lead_id else None

    # Automatically mark conversation as read upon retrieval
    if conv.unread_count > 0:
        conv.unread_count = 0
        conv.updated_at = utc_now()
        db.commit()

    messages = (
        db.query(ConversationMessage)
        .filter_by(conversation_id=conv.id)
        .order_by(ConversationMessage.created_at.asc())
        .all()
    )

    followups = (
        db.query(FollowUpExecution)
        .filter_by(conversation_id=conv.id)
        .order_by(FollowUpExecution.sequence_step.asc())
        .all()
    )

    lead_gaps = []
    if lead:
        dim_scores = db.query(DimensionScore).filter_by(lead_id=lead.id).all()
        for ds in dim_scores:
            if ds.points < ds.max_points:
                lead_gaps.append({
                    "dimension": ds.dimension,
                    "score": ds.points,
                    "summary": ds.reason_code.replace("_", " ").title(),
                })

    return {
        "conversation": {
            "id": str(conv.id),
            "recipient_email": conv.recipient_email,
            "sender_email": conv.sender_email,
            "subject": conv.subject,
            "status": conv.status,
            "unread_count": conv.unread_count,
            "followup_status": conv.followup_status,
            "followup_step": conv.followup_step,
            "created_at": conv.created_at.isoformat(),
            "last_message_at": conv.last_message_at.isoformat(),
        },
        "business": {
            "id": str(biz.id) if biz else None,
            "name": biz.name if biz else (conv.recipient_email.split("@")[0].capitalize()),
            "website": biz.website if biz else None,
            "phone": biz.phone if biz else None,
            "locality": biz.locality if biz else None,
            "address": biz.address if biz else None,
            "rating": biz.rating if biz else None,
        } if biz else None,
        "lead": {
            "id": str(lead.id) if lead else None,
            "overall_score": lead.overall_score if lead else None,
            "recommended_service": lead.recommended_service if lead else None,
            "audit_notes": getattr(lead, "audit_notes", None) or (f"Priority: {lead.priority}, Confidence: {lead.confidence}." if lead else None),
            "gaps": lead_gaps,
        } if lead else None,
        "campaign": {
            "id": str(camp.id) if camp else None,
            "niche": camp.niche if camp else None,
            "location": camp.location if camp else None,
        } if camp else None,
        "messages": [
            {
                "id": str(m.id),
                "direction": m.direction,
                "message_type": m.message_type,
                "sender": m.sender,
                "recipient": m.recipient,
                "subject": m.subject,
                "body": m.body,
                "delivery_status": m.delivery_status,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
        "followups": [
            {
                "id": str(f.id),
                "sequence_step": f.sequence_step,
                "scheduled_at": f.scheduled_at.isoformat(),
                "executed_at": f.executed_at.isoformat() if f.executed_at else None,
                "status": f.status,
                "stop_reason": f.stop_reason,
            }
            for f in followups
        ],
    }


class OperatorReplyForm(BaseModel):
    body: str
    subject: str | None = None
    pause_followups: bool = True


@web_router.post("/api/web/inbox/conversations/{conversation_id}/reply")
def api_send_operator_reply(
    conversation_id: uuid.UUID,
    payload: OperatorReplyForm,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    if not payload.body or not payload.body.strip():
        raise HTTPException(status_code=400, detail="Reply body cannot be empty")

    result = send_operator_reply(
        db,
        settings,
        conversation_id=conversation_id,
        reply_body=payload.body.strip(),
        subject=payload.subject,
        pause_followups=payload.pause_followups,
    )
    return {"status": "success", "result": result}


class ConversationActionForm(BaseModel):
    action: str  # mark_read, mark_unread, pause_followups, resume_followups, set_status, archive
    value: str | None = None


@web_router.post("/api/web/inbox/conversations/{conversation_id}/actions")
def api_conversation_action(
    conversation_id: uuid.UUID,
    payload: ConversationActionForm,
    db: Session = Depends(get_session),
):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    act = payload.action.lower().strip()
    if act == "mark_read":
        conv.unread_count = 0
    elif act == "mark_unread":
        conv.unread_count = max(1, conv.unread_count + 1)
    elif act == "pause_followups":
        pause_followups(db, conv.id)
    elif act == "resume_followups":
        resume_followups(db, conv.id)
    elif act == "set_status":
        if payload.value:
            conv.status = payload.value.strip().lower()
    elif act == "archive":
        conv.status = "archived"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {payload.action}")

    conv.updated_at = utc_now()
    db.commit()
    return {
        "status": "success",
        "action": act,
        "conversation_status": conv.status,
        "unread_count": conv.unread_count,
        "followup_status": conv.followup_status,
    }

