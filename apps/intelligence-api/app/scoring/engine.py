from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import uuid

from app.models import Business, Evidence
from app.scoring import reasons
from app.services.parser import SERVICES


@dataclass
class DimensionScoreResult:
    dimension: str
    points: int
    max_points: int
    evidence_ids: list[str] = field(default_factory=list)
    reason_code: str = ""


@dataclass
class ServiceScoreResult:
    service: str
    points: int
    evidence_ids: list[str] = field(default_factory=list)
    reason_code: str = ""


@dataclass
class ScoreResult:
    overall_score: int
    priority: str
    confidence: str
    dimensions: list[DimensionScoreResult] = field(default_factory=list)
    service_scores: list[ServiceScoreResult] = field(default_factory=list)
    recommended_service: str | None = None


def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _ev_ids(*evs: Evidence | None) -> list[str]:
    return [str(e.id) for e in evs if e is not None and getattr(e, "id", None) is not None]


def score_lead(
    listing_facts: dict[str, Any] | Business,
    evidence: list[Evidence],
    target_services: list[str] | None = None,
) -> ScoreResult:
    if target_services is None:
        target_services = list(SERVICES)

    website = _get_attr(listing_facts, "website")
    category = _get_attr(listing_facts, "category") or ""
    listing_status = _get_attr(listing_facts, "listing_status") or "open"
    phone = _get_attr(listing_facts, "phone")
    email = _get_attr(listing_facts, "email")
    source_fields = _get_attr(listing_facts, "source_fields") or {}
    reviews = _get_attr(listing_facts, "reviews") or source_fields.get("reviews") or []

    # Map evidence helpers
    unreachable_ev = next(
        (e for e in evidence if "unreachable" in (e.supporting_excerpt or "").lower() or "unreachable" in e.claim.lower()),
        None,
    )
    restricted_ev = next(
        (
            e
            for e in evidence
            if any(
                k in (e.supporting_excerpt or "").lower()
                for k in ("restricted", "disallow", "challenge", "paywall", "ssrf")
            )
        ),
        None,
    )
    no_viewport_ev = next((e for e in evidence if e.supporting_excerpt == "no_viewport"), None)
    has_viewport_ev = next((e for e in evidence if e.supporting_excerpt == "has_viewport"), None)
    missing_search_ev = next((e for e in evidence if e.supporting_excerpt == "missing_listing_search"), None)
    has_search_ev = next((e for e in evidence if e.supporting_excerpt == "has_listing_search"), None)
    has_form_ev = next((e for e in evidence if e.supporting_excerpt == "has_form"), None)
    has_whatsapp_ev = next((e for e in evidence if e.supporting_excerpt == "has_whatsapp"), None)
    has_chatbot_ev = next((e for e in evidence if e.supporting_excerpt == "has_chatbot"), None)
    has_booking_ev = next((e for e in evidence if e.supporting_excerpt == "has_booking"), None)
    no_chat_booking_ev = next((e for e in evidence if e.supporting_excerpt == "no_visible_chat_or_booking"), None)
    explicit_intent_ev = next((e for e in evidence if e.evidence_type == "explicit_intent"), None)

    site_inspected = bool(website and not unreachable_ev and not restricted_ev and evidence)

    # 1. website_opportunity (max 25)
    w_points = 0
    w_reason = reasons.UNKNOWN_NOT_INSPECTED
    w_ev_ids: list[str] = []

    if not website or not str(website).strip():
        w_points = 25
        w_reason = reasons.NO_WEBSITE_URL
    elif unreachable_ev:
        w_points = 22
        w_reason = reasons.WEBSITE_UNREACHABLE
        w_ev_ids = _ev_ids(unreachable_ev)
    elif restricted_ev:
        w_points = 0
        w_reason = reasons.UNKNOWN_NOT_INSPECTED
        w_ev_ids = _ev_ids(restricted_ev)
    elif site_inspected:
        if no_viewport_ev and not has_search_ev:
            w_points = 18
            w_reason = reasons.THIN_UNRESPONSIVE_SITE
            w_ev_ids = _ev_ids(no_viewport_ev, missing_search_ev)
        elif missing_search_ev and "real estate" in category.lower():
            w_points = 12
            w_reason = reasons.MISSING_LISTING_SEARCH
            w_ev_ids = _ev_ids(missing_search_ev)
        elif has_search_ev:
            w_points = 4
            w_reason = reasons.LISTING_CAPABLE_SITE
            w_ev_ids = _ev_ids(has_search_ev)
        else:
            w_points = 8
            w_reason = reasons.REACHABLE_OTHER
    else:
        w_points = 0
        w_reason = reasons.UNKNOWN_NOT_INSPECTED

    dim_website = DimensionScoreResult(
        dimension="website_opportunity",
        points=w_points,
        max_points=25,
        evidence_ids=w_ev_ids,
        reason_code=w_reason,
    )

    # 2. lead_capture_opportunity (max 20)
    lc_points = 0
    lc_reason = reasons.UNKNOWN_NOT_INSPECTED
    lc_ev_ids: list[str] = []

    if not website or not str(website).strip():
        lc_points = 18
        lc_reason = reasons.NO_WEBSITE_URL
    elif unreachable_ev:
        lc_points = 18
        lc_reason = reasons.WEBSITE_UNREACHABLE
        lc_ev_ids = _ev_ids(unreachable_ev)
    elif restricted_ev:
        lc_points = 0
        lc_reason = reasons.UNKNOWN_NOT_INSPECTED
        lc_ev_ids = _ev_ids(restricted_ev)
    elif site_inspected:
        if not has_form_ev and not has_booking_ev and not has_whatsapp_ev and not phone and not email:
            lc_points = 20
            lc_reason = reasons.NO_INQUIRY_PATH
        elif not has_form_ev and not has_booking_ev and (has_whatsapp_ev or phone or email):
            lc_points = 14
            lc_reason = reasons.CONTACT_ONLY
            lc_ev_ids = _ev_ids(has_whatsapp_ev)
        elif has_form_ev or has_booking_ev:
            lc_points = 4
            lc_reason = reasons.WORKING_CAPTURE
            lc_ev_ids = _ev_ids(has_form_ev, has_booking_ev)
        else:
            lc_points = 0
            lc_reason = reasons.UNKNOWN_NOT_INSPECTED
    else:
        lc_points = 0
        lc_reason = reasons.UNKNOWN_NOT_INSPECTED

    dim_lead_capture = DimensionScoreResult(
        dimension="lead_capture_opportunity",
        points=lc_points,
        max_points=20,
        evidence_ids=lc_ev_ids,
        reason_code=lc_reason,
    )

    # 3. automation_opportunity (max 20)
    auto_points = 0
    auto_reason = reasons.UNKNOWN_NOT_INSPECTED
    auto_ev_ids: list[str] = []

    # Check reviews friction
    friction_keywords = ("slow", "call back", "closed early", "outdated", "friction", "hard to reach", "late")
    friction_count = 0
    if isinstance(reviews, list):
        for r_text in reviews:
            r_str = str(r_text).lower()
            if any(k in r_str for k in friction_keywords):
                friction_count += 1

    if friction_count >= 2:
        auto_points = 16
        auto_reason = reasons.PUBLIC_PROCESS_FRICTION
    elif not site_inspected:
        auto_points = 0
        auto_reason = reasons.UNKNOWN_NOT_INSPECTED
        if restricted_ev:
            auto_ev_ids = _ev_ids(restricted_ev)
        elif unreachable_ev:
            auto_ev_ids = _ev_ids(unreachable_ev)
    else:
        if not has_chatbot_ev and not has_booking_ev:
            auto_points = 8
            auto_reason = reasons.NO_VISIBLE_CHAT_OR_BOOKING
            auto_ev_ids = _ev_ids(no_chat_booking_ev)
        elif bool(has_chatbot_ev) ^ bool(has_booking_ev):
            auto_points = 2
            auto_reason = reasons.PARTIAL_AUTOMATION_VISIBLE
            auto_ev_ids = _ev_ids(has_chatbot_ev or has_booking_ev)
        elif has_chatbot_ev and has_booking_ev:
            auto_points = 0
            auto_reason = reasons.AUTOMATION_ALREADY_VISIBLE
            auto_ev_ids = _ev_ids(has_chatbot_ev, has_booking_ev)
        else:
            auto_points = 0
            auto_reason = reasons.UNKNOWN_NOT_INSPECTED

    dim_auto = DimensionScoreResult(
        dimension="automation_opportunity",
        points=auto_points,
        max_points=20,
        evidence_ids=auto_ev_ids,
        reason_code=auto_reason,
    )

    # 4. business_suitability (max 15)
    bs_points = 0
    bs_reason = reasons.INSUFFICIENT_LISTING_FIELDS
    if "real estate" in category.lower():
        if str(listing_status).lower() in ("open", "active", "operating"):
            bs_points = 15
            bs_reason = reasons.NICHE_ACTIVE
        else:
            bs_points = 3
            bs_reason = reasons.NICHE_CLOSED
    elif category:
        bs_points = 0
        bs_reason = reasons.UNRELATED_CATEGORY
    else:
        bs_points = 6
        bs_reason = reasons.INSUFFICIENT_LISTING_FIELDS

    dim_suitability = DimensionScoreResult(
        dimension="business_suitability",
        points=bs_points,
        max_points=15,
        evidence_ids=[],
        reason_code=bs_reason,
    )

    # 5. buying_intent_evidence (max 15)
    bi_points = 0
    bi_reason = reasons.NO_EXPLICIT_INTENT
    bi_ev_ids: list[str] = []
    if explicit_intent_ev and explicit_intent_ev.source_url:
        bi_points = 15
        bi_reason = reasons.EXPLICIT_INTENT_PRESENT
        bi_ev_ids = _ev_ids(explicit_intent_ev)

    dim_buying_intent = DimensionScoreResult(
        dimension="buying_intent_evidence",
        points=bi_points,
        max_points=15,
        evidence_ids=bi_ev_ids,
        reason_code=bi_reason,
    )

    # 6. contactability (max 5)
    c_points = 0
    c_reason = reasons.NO_PUBLIC_CONTACT
    if email:
        c_points = 5
        c_reason = reasons.PUBLIC_EMAIL
    elif phone:
        c_points = 4
        c_reason = reasons.PUBLIC_PHONE
    elif has_form_ev or has_whatsapp_ev:
        c_points = 3
        c_reason = reasons.WEBSITE_CONTACT_PATH
    else:
        c_points = 0
        c_reason = reasons.NO_PUBLIC_CONTACT

    dim_contact = DimensionScoreResult(
        dimension="contactability",
        points=c_points,
        max_points=5,
        evidence_ids=[],
        reason_code=c_reason,
    )

    dimensions = [
        dim_website,
        dim_lead_capture,
        dim_auto,
        dim_suitability,
        dim_buying_intent,
        dim_contact,
    ]

    overall_score = sum(d.points for d in dimensions)
    if overall_score >= 80:
        priority = "A"
    elif overall_score >= 65:
        priority = "B"
    elif overall_score >= 45:
        priority = "C"
    else:
        priority = "D"

    # Confidence calculation
    verified_obs = [
        e
        for e in evidence
        if e.evidence_type == "verified_observation" and e.source_url
    ]
    if len(verified_obs) >= 2:
        confidence = "high"
    elif len(verified_obs) == 1:
        confidence = "medium"
    else:
        confidence = "low"

    # Service-fit scores
    service_scores: list[ServiceScoreResult] = []

    # 1. website_development
    wd_points = 0
    wd_ev_ids: list[str] = []
    wd_reason = reasons.UNKNOWN_NOT_INSPECTED
    if not website or not str(website).strip():
        wd_points = 70
        wd_reason = reasons.NO_WEBSITE_URL
    elif unreachable_ev:
        wd_points = 50
        wd_reason = reasons.WEBSITE_UNREACHABLE
        wd_ev_ids = _ev_ids(unreachable_ev)
    else:
        wd_points = 0
        wd_reason = reasons.SERVICE_GAP_IDENTIFIED if site_inspected else reasons.UNKNOWN_NOT_INSPECTED

    service_scores.append(
        ServiceScoreResult(
            service="website_development",
            points=min(wd_points, 100),
            evidence_ids=wd_ev_ids,
            reason_code=wd_reason,
        )
    )

    # 2. website_redesign
    wr_points = 0
    wr_ev_ids: list[str] = []
    wr_reason = reasons.UNKNOWN_NOT_INSPECTED
    if site_inspected:
        if no_viewport_ev:
            wr_points += 40
            wr_ev_ids.extend(_ev_ids(no_viewport_ev))
        if missing_search_ev and "real estate" in category.lower():
            wr_points += 20
            wr_ev_ids.extend(_ev_ids(missing_search_ev))
        if no_viewport_ev and not has_search_ev:
            wr_points += 30  # thin service content
        wr_reason = reasons.SERVICE_GAP_IDENTIFIED if wr_points > 0 else reasons.LISTING_CAPABLE_SITE

    service_scores.append(
        ServiceScoreResult(
            service="website_redesign",
            points=min(wr_points, 100),
            evidence_ids=wr_ev_ids,
            reason_code=wr_reason,
        )
    )

    # 3. real_estate_listing_portal
    lp_points = 0
    lp_ev_ids: list[str] = []
    lp_reason = reasons.UNKNOWN_NOT_INSPECTED
    if site_inspected and "real estate" in category.lower():
        if missing_search_ev:
            lp_points = 80
            lp_reason = reasons.MISSING_LISTING_SEARCH
            lp_ev_ids = _ev_ids(missing_search_ev)
        elif has_search_ev:
            lp_points = 20
            lp_reason = reasons.LISTING_CAPABLE_SITE
            lp_ev_ids = _ev_ids(has_search_ev)

    service_scores.append(
        ServiceScoreResult(
            service="real_estate_listing_portal",
            points=min(lp_points, 100),
            evidence_ids=lp_ev_ids,
            reason_code=lp_reason,
        )
    )

    # 4. ai_chatbot
    cb_points = 0
    cb_ev_ids: list[str] = []
    cb_reason = reasons.UNKNOWN_NOT_INSPECTED
    if site_inspected:
        if not has_chatbot_ev:
            cb_points = 55
            cb_reason = reasons.SERVICE_GAP_IDENTIFIED
            if no_chat_booking_ev:
                cb_ev_ids = _ev_ids(no_chat_booking_ev)
        else:
            cb_points = 10
            cb_reason = reasons.RESIDUAL_EXISTING_TOOL
            cb_ev_ids = _ev_ids(has_chatbot_ev)

    service_scores.append(
        ServiceScoreResult(
            service="ai_chatbot",
            points=min(cb_points, 100),
            evidence_ids=cb_ev_ids,
            reason_code=cb_reason,
        )
    )

    # 5. business_process_automation
    bpa_points = 0
    bpa_ev_ids: list[str] = []
    bpa_reason = reasons.UNKNOWN_NOT_INSPECTED
    if auto_reason == reasons.PUBLIC_PROCESS_FRICTION:
        bpa_points = 40
        bpa_reason = reasons.PUBLIC_PROCESS_FRICTION
    elif auto_reason == reasons.NO_VISIBLE_CHAT_OR_BOOKING:
        bpa_points = 20
        bpa_reason = reasons.NO_VISIBLE_CHAT_OR_BOOKING
        if no_chat_booking_ev:
            bpa_ev_ids = _ev_ids(no_chat_booking_ev)

    service_scores.append(
        ServiceScoreResult(
            service="business_process_automation",
            points=min(bpa_points, 100),
            evidence_ids=bpa_ev_ids,
            reason_code=bpa_reason,
        )
    )

    # 6. lead_management_followup
    lmf_points = 0
    lmf_ev_ids: list[str] = []
    lmf_reason = reasons.UNKNOWN_NOT_INSPECTED
    if site_inspected:
        if not has_form_ev and not has_booking_ev:
            lmf_points = 50
            lmf_reason = reasons.NO_INQUIRY_PATH
        elif has_form_ev and not has_chatbot_ev and not has_booking_ev:
            lmf_points = 25
            lmf_reason = reasons.SERVICE_GAP_IDENTIFIED
            lmf_ev_ids = _ev_ids(has_form_ev, no_chat_booking_ev)

    service_scores.append(
        ServiceScoreResult(
            service="lead_management_followup",
            points=min(lmf_points, 100),
            evidence_ids=lmf_ev_ids,
            reason_code=lmf_reason,
        )
    )

    # 7. crm_appointment_automation
    crm_points = 0
    crm_ev_ids: list[str] = []
    crm_reason = reasons.UNKNOWN_NOT_INSPECTED
    if site_inspected:
        if not has_booking_ev:
            crm_points = 60
            crm_reason = reasons.SERVICE_GAP_IDENTIFIED
            if no_chat_booking_ev:
                crm_ev_ids = _ev_ids(no_chat_booking_ev)
        else:
            crm_points = 15
            crm_reason = reasons.RESIDUAL_EXISTING_TOOL
            crm_ev_ids = _ev_ids(has_booking_ev)

    service_scores.append(
        ServiceScoreResult(
            service="crm_appointment_automation",
            points=min(crm_points, 100),
            evidence_ids=crm_ev_ids,
            reason_code=crm_reason,
        )
    )

    # Recommended service: highest among target_services, min 40
    service_map = {s.service: s for s in service_scores}
    eligible_services = [s for s in SERVICES if s in target_services]

    best_service: str | None = None
    best_points = 39  # must be >= 40

    for s_name in eligible_services:
        s_obj = service_map.get(s_name)
        if s_obj and s_obj.points > best_points:
            best_points = s_obj.points
            best_service = s_name

    return ScoreResult(
        overall_score=overall_score,
        priority=priority,
        confidence=confidence,
        dimensions=dimensions,
        service_scores=service_scores,
        recommended_service=best_service,
    )
