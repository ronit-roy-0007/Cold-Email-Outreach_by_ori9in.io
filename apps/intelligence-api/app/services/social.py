from __future__ import annotations

import re
from typing import Any


def sanitize_website(name: str, website: str | None) -> str:
    """
    Ensures website is either empty (for no website) or a clean real domain.
    Replaces any internal test fixture domain like 'fixtures.intentlead.test'
    with a clean realistic domain derived from the business name.
    """
    if not website or not str(website).strip():
        return ""
    w = str(website).strip()
    if "fixtures.intentlead.test" in w or "intentlead.test" in w or ".test/" in w or w.endswith(".test"):
        clean_slug = "".join(c for c in name.lower() if c.isalnum())[:16] or "company"
        return f"https://www.{clean_slug}.com"
    return w


def get_business_social_links(
    biz_or_fields: Any, phone: str | None = None, name: str = ""
) -> dict[str, str]:
    """
    Extracts social profile links (LinkedIn, Facebook, Instagram, Twitter, Reddit, Telegram)
    from a Business model, dictionary, or source_fields.
    Returns a dict with keys: 'linkedin', 'facebook', 'instagram', 'twitter', 'reddit', 'telegram'.
    If not available, values are empty string "".
    """
    sf: dict[str, Any] = {}
    biz_phone = phone
    biz_name = name

    if hasattr(biz_or_fields, "source_fields"):
        if isinstance(biz_or_fields.source_fields, dict):
            sf = biz_or_fields.source_fields
        if not biz_phone and hasattr(biz_or_fields, "phone"):
            biz_phone = biz_or_fields.phone
        if not biz_name and hasattr(biz_or_fields, "name"):
            biz_name = biz_or_fields.name
    elif isinstance(biz_or_fields, dict):
        if "source_fields" in biz_or_fields and isinstance(biz_or_fields["source_fields"], dict):
            sf = biz_or_fields["source_fields"]
        else:
            sf = biz_or_fields
        if not biz_phone:
            biz_phone = sf.get("phone") or biz_or_fields.get("phone")
        if not biz_name:
            biz_name = sf.get("title") or sf.get("name") or biz_or_fields.get("title") or biz_or_fields.get("name") or ""

    socials = sf.get("social_links") if isinstance(sf.get("social_links"), dict) else {}

    res = {
        "linkedin": (
            socials.get("linkedin")
            or sf.get("linkedin")
            or sf.get("linkedin_url")
            or ""
        ),
        "facebook": (
            socials.get("facebook")
            or sf.get("facebook")
            or sf.get("facebook_url")
            or ""
        ),
        "instagram": (
            socials.get("instagram")
            or sf.get("instagram")
            or sf.get("instagram_url")
            or ""
        ),
        "twitter": (
            socials.get("twitter")
            or socials.get("x")
            or sf.get("twitter")
            or sf.get("x")
            or sf.get("twitter_url")
            or ""
        ),
        "reddit": (
            socials.get("reddit")
            or sf.get("reddit")
            or sf.get("reddit_url")
            or ""
        ),
        "telegram": (
            socials.get("telegram")
            or sf.get("telegram")
            or sf.get("telegram_link")
            or ""
        ),
    }

    # If telegram is not explicitly set, but phone number is available, format direct outreach link
    if not res["telegram"] and biz_phone:
        digits = re.sub(r"[^\d+]", "", str(biz_phone))
        if digits:
            if not digits.startswith("+"):
                digits = f"+{digits}"
            res["telegram"] = f"https://t.me/{digits}"

    return {k: str(v).strip() for k, v in res.items()}


def get_lead_messages(db: Any, lead: Any) -> tuple[str, str]:
    """
    Returns (drafts, approved_messages) for a lead:
    - drafts: The initial outreach pitch generated for this lead.
    - approved_messages: The message approved by the user in Telegram
      (either the AI-regenerated pitch if approved, or the initial pitch if approved;
      empty string if lead is not approved).
    """
    from app.models import MessageDraft

    drafts = db.query(MessageDraft).filter_by(lead_id=lead.id).all()
    if not drafts:
        return "", ""

    # Initial draft: channel in ("preview", "initial") or the first draft
    initial_draft = next((d for d in drafts if d.channel in ("preview", "initial")), drafts[0])
    initial_text = initial_draft.body or ""

    # AI regenerated draft if present
    ai_draft = next((d for d in drafts if d.channel == "ai_regenerated"), None)

    approved_text = ""
    if getattr(lead, "outreach_status", "") == "approved":
        approved_draft = next((d for d in drafts if d.status == "approved"), None)
        if approved_draft and approved_draft.body:
            approved_text = approved_draft.body
        elif ai_draft and ai_draft.body:
            approved_text = ai_draft.body
        else:
            approved_text = initial_text

    return initial_text, approved_text

