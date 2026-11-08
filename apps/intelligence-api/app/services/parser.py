from __future__ import annotations

from typing import Any

from app.schemas import CampaignInput, ParseError

SERVICES = (
    "website_development",
    "website_redesign",
    "real_estate_listing_portal",
    "ai_chatbot",
    "business_process_automation",
    "lead_management_followup",
    "crm_appointment_automation",
)

_SERVICE_SET = frozenset(SERVICES)


def parse_campaign(payload: dict) -> CampaignInput | ParseError:
    fields: list[str] = []

    niche = payload.get("niche")
    if not isinstance(niche, str) or niche.strip() == "":
        fields.append("niche")

    location = payload.get("location")
    if not isinstance(location, str) or location.strip() == "":
        fields.append("location")

    quantity = payload.get("requested_quantity")
    max_qty = payload.get("max_limit", 25)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1 or quantity > max_qty:
        fields.append("requested_quantity")

    target_services = payload.get("target_services")
    if not _valid_target_services(target_services):
        fields.append("target_services")

    filters = payload.get("filters", {})
    if not isinstance(filters, dict):
        fields.append("filters")

    if fields:
        return ParseError(fields=fields)

    return CampaignInput(
        niche=niche,
        location=location,
        requested_quantity=quantity,
        target_services=list(target_services),
        filters=filters,
        dry_run=True,
    )


def _valid_target_services(value: Any) -> bool:
    if not isinstance(value, list) or len(value) == 0:
        return False
    for item in value:
        if not isinstance(item, str) or item not in _SERVICE_SET:
            return False
    return True
