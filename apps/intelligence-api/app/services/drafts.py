from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models import Evidence
from app.scoring.engine import ServiceScoreResult


@dataclass
class DraftResult:
    status: str  # "preview" or "draft_not_recommended"
    body: str | None = None
    reason: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    subject: str | None = None


def clean_business_name(name: str | None) -> str:
    """
    Cleans Google Maps / business titles by stripping SEO subtitles, slogans, and geo suffixes.
    e.g. 'Shabir Ahmad - Licensed Real Estate Agent in Brooklyn, NY' -> 'Shabir Ahmad'
         'Apex Roofing | Commercial & Residential Specialists' -> 'Apex Roofing'
    """
    if not name:
        return "there"
    cleaned = name.strip()
    for sep in (" - ", " | ", " — ", " – ", " : ", " • "):
        if sep in cleaned:
            cleaned = cleaned.split(sep)[0].strip()
    return cleaned or "there"


def generate_hook_subject(business_name: str, recommended_service: str | None = None) -> str:
    """
    Generates a personalized, high-converting hook question subject line that
    piques curiosity and drives high open rates without looking like cold outreach.
    """
    biz_name = clean_business_name(business_name)
    if not biz_name or biz_name == "there":
        return "Quick question?"

    if recommended_service == "real_estate_listing_portal":
        return f"Quick question about {biz_name} property listings?"
    elif recommended_service == "ai_chatbot":
        return f"Quick question about after-hours inquiries at {biz_name}?"
    elif recommended_service == "crm_appointment_automation":
        return f"Quick question about appointment scheduling for {biz_name}?"
    elif recommended_service in ("website_development", "website_redesign"):
        return f"Quick question about your website, {biz_name}?"
    elif recommended_service == "lead_management_followup":
        return f"Quick question about incoming leads at {biz_name}?"
    else:
        return f"Quick question regarding {biz_name}?"


SERVICE_DISPLAY_NAMES = {
    "website_development": "modern, mobile-responsive website development with built-in lead capture",
    "website_redesign": "website redesign and user-friendly mobile optimization",
    "real_estate_listing_portal": "custom property listing search and filter portal",
    "ai_chatbot": "deploying a 24/7 AI chat assistant to capture inquiries and assist customers",
    "business_process_automation": "automated business systems (leads handling, follow-ups, and calendar scheduling)",
    "lead_management_followup": "automated lead intake, instant outreach, and multi-touch follow-up systems",
    "crm_appointment_automation": "automated appointment booking and showing scheduling",
}


def build_draft(
    *,
    agency_name: str,
    sender_name: str,
    business_name: str,
    recommended_service: str | None,
    evidence: list[Evidence],
    service_scores: list[ServiceScoreResult | dict[str, Any]],
    rating: float | None = None,
    review_count: int | None = None,
    services_desc: str | None = None,
) -> DraftResult:
    agency = agency_name.strip() if agency_name else ""
    sender = sender_name.strip() if sender_name else ""

    if not agency or not sender:
        return DraftResult(
            status="draft_not_recommended",
            body=None,
            reason="agency_identity_not_configured",
        )

    if not recommended_service:
        return DraftResult(
            status="draft_not_recommended",
            body=None,
            reason="no_service_recommended",
        )

    # Check for residual tool without gap
    score_map: dict[str, Any] = {}
    for s in service_scores:
        if isinstance(s, dict):
            score_map[s.get("service", "")] = s
        else:
            score_map[s.service] = s

    svc_score = score_map.get(recommended_service)
    svc_reason = getattr(svc_score, "reason_code", None) or (
        svc_score.get("reason_code") if isinstance(svc_score, dict) else None
    )

    if svc_reason == "residual_existing_tool":
        return DraftResult(
            status="draft_not_recommended",
            body=None,
            reason="residual_existing_tool_no_gap",
        )

    # Find supporting evidence
    relevant_ev = [
        e
        for e in evidence
        if e.evidence_type in ("verified_observation", "explicit_intent")
    ]

    matched_ev: Evidence | None = None
    if recommended_service == "real_estate_listing_portal":
        matched_ev = next(
            (e for e in relevant_ev if "listing" in e.claim.lower() or "search" in e.claim.lower()),
            None,
        )
    elif recommended_service in ("website_development", "website_redesign"):
        matched_ev = next(
            (e for e in relevant_ev if "viewport" in e.claim.lower() or "unreachable" in e.claim.lower()),
            None,
        )
    elif recommended_service == "ai_chatbot":
        matched_ev = next(
            (e for e in relevant_ev if "chat" in e.claim.lower()),
            None,
        )
    elif recommended_service == "crm_appointment_automation":
        matched_ev = next(
            (e for e in relevant_ev if "booking" in e.claim.lower()),
            None,
        )

    if not matched_ev and relevant_ev:
        matched_ev = relevant_ev[0]

    evidence_ids: list[str] = []
    if matched_ev and getattr(matched_ev, "id", None) is not None:
        evidence_ids.append(str(matched_ev.id))

    clean_name = clean_business_name(business_name)
    hook_subject = generate_hook_subject(clean_name, recommended_service)

    svc_display = SERVICE_DISPLAY_NAMES.get(recommended_service, recommended_service.replace("_", " "))

    # 1. 100% Coherent Gap Hook + Solution Pair directly matched to recommended_service
    if recommended_service == "real_estate_listing_portal":
        gap_intro = f"I was looking at your website and noticed there's no direct property listing search or filter for buyers browsing your site."
        solution_note = f"We build custom property listing search portals for {clean_name} so buyers can browse and inquire directly without bouncing."
    elif recommended_service == "crm_appointment_automation":
        gap_intro = f"I checked your website and noticed clients can't directly book an appointment or viewing with your team online."
        solution_note = f"We set up automated appointment and showing scheduling for {clean_name} so you never lose high-intent clients to manual phone tag."
    elif recommended_service == "ai_chatbot":
        gap_intro = f"I was browsing your website and noticed you don't have a 24/7 AI chat assistant to capture inquiries after hours or on weekends."
        solution_note = f"We deploy 24/7 AI chat assistants for {clean_name} that automatically answer questions and capture lead details around the clock."
    elif recommended_service == "website_redesign":
        gap_intro = f"I checked your website on my phone and noticed it isn't fully responsive for mobile screens, making it tough for mobile visitors to reach out."
        solution_note = f"We build modern, fast, and mobile-friendly websites for {clean_name} with built-in inquiry capture to increase client conversions."
    elif recommended_service == "website_development":
        gap_intro = f"I noticed {clean_name} doesn't have an active website listed yet, which means potential clients might be going straight to competitors."
        solution_note = f"We build high-converting, modern websites for {clean_name} with built-in lead capture to establish a strong online presence."
    elif recommended_service == "lead_management_followup":
        gap_intro = f"I was reviewing your online presence and noticed there's no instant follow-up system when a new inquiry reaches out."
        solution_note = f"We set up automated lead capture and prompt follow-up systems for {clean_name} to ensure every inquiry is engaged immediately."
    elif recommended_service == "business_process_automation":
        gap_intro = f"I was reviewing your customer feedback and noticed opportunities to eliminate delays in client callbacks and scheduling."
        solution_note = f"We set up automated workflow systems for {clean_name} that handle inquiries, client reminders, and scheduling on autopilot."
    else:
        gap_intro = f"I was reviewing your online presence and noticed an opportunity to improve how you capture and convert inbound inquiries."
        solution_note = f"We set up automated systems for {clean_name} ({svc_display}) so you never lose qualified inquiries to competitors."

    # 2. Short reputation / social proof note
    reputation_note = ""
    if rating is not None and rating < 4.4:
        reputation_note = f" Also, with your {rating:.1f}★ rating ({review_count or 0} reviews), our system helps turn that into an active 5-star presence to increase monthly sales and total revenue."
    elif review_count is not None and review_count < 25:
        reputation_note = f" Also, with {review_count} Google reviews, our system helps build an active 5-star presence to convert more leads into monthly sales and total revenue."

    middle_pitch = f"{solution_note}{reputation_note}".strip()

    # 3. Punchy, exact CTA requested by the user
    cta = "Should I show you the demo how it works? Then we can talk further if you are interested."

    body = (
        f"Hi {clean_name},\n\n"
        f"{gap_intro} {middle_pitch}\n\n"
        f"{cta}\n\n"
        f"Best,\n"
        f"{sender}\n"
        f"{agency}"
    )

    return DraftResult(
        status="preview",
        body=body,
        reason=None,
        evidence_ids=evidence_ids,
        subject=hook_subject,
    )
