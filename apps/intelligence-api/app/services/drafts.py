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


SERVICE_DISPLAY_NAMES = {
    "website_development": "modern website development",
    "website_redesign": "website redesign and mobile responsiveness",
    "real_estate_listing_portal": "custom property listing search and filter portal",
    "ai_chatbot": "conversational AI assistant for visitor inquiries",
    "business_process_automation": "automated workflow operations",
    "lead_management_followup": "automated lead capture and prompt follow-up systems",
    "crm_appointment_automation": "online appointment and showing booking automation",
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

    if matched_ev:
        observation = f"that {matched_ev.claim.lower().rstrip('.')}"
    elif recommended_service == "website_development":
        observation = "that there is currently no website listed for your business"
    else:
        observation = "an opportunity to enhance your digital presence"

    svc_display = SERVICE_DISPLAY_NAMES.get(recommended_service, recommended_service.replace("_", " "))

    reputation_note = ""
    if rating is not None and rating < 4.4:
        reputation_note = (
            f" We also noticed {business_name} currently has a {rating:.1f}★ rating "
            f"({review_count or 0} reviews) on Google Maps — our automated post-service review system "
            f"helps turn satisfied customers into 5-star reviews on autopilot, boosting your online presence and inbound sales."
        )
    elif review_count is not None and review_count < 25:
        reputation_note = (
            f" We also noticed you currently have {review_count} Google reviews — "
            f"our automated follow-up system helps rapidly build authentic 5-star reviews to elevate your search ranking and convert more visitors."
        )

    if reputation_note:
        body = (
            f"Hi {business_name},\n\n"
            f"I am {sender} with {agency}. I reviewed your public business presence and noticed "
            f"{observation}.{reputation_note} If helpful, we can discuss {svc_display}. "
            f"Happy to share a brief outline — no need to reply if this is not relevant.\n\n"
            f"Best,\n"
            f"{sender}\n"
            f"{agency}"
        )
    else:
        body = (
            f"Hi {business_name},\n\n"
            f"I am {sender} with {agency}. I reviewed your public business presence and noticed "
            f"{observation}. If helpful, we can discuss {svc_display}. "
            f"Happy to share a brief outline — no need to reply if this is not relevant.\n\n"
            f"Best,\n"
            f"{sender}\n"
            f"{agency}"
        )

    return DraftResult(
        status="preview",
        body=body,
        reason=None,
        evidence_ids=evidence_ids,
    )
