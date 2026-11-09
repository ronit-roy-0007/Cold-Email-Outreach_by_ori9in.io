from __future__ import annotations

import json
import logging
from typing import Any
import urllib.request
import urllib.error

from app.config import Settings
from app.models import Business, Evidence, Lead
from app.services.drafts import SERVICE_DISPLAY_NAMES

logger = logging.getLogger("gemini_personalizer")


def generate_gemini_pitch(
    *,
    business: Business,
    lead: Lead,
    evidence: list[Evidence],
    settings: Settings,
    custom_instruction: str | None = None,
) -> str | None:
    """
    Uses Google Gemini (Free API) to deeply analyze audited prospect data and generate
    a hyper-personalized, 3-sentence high-converting B2B outreach email.
    
    Falls back gracefully (returns None) if API key is not configured or if an error occurs.
    """
    api_key = (settings.USER_LLM_API_KEY or "").strip()
    if not api_key:
        return None

    agency_name = (settings.AGENCY_NAME or "ori9in.io").strip()
    sender_name = (settings.AGENCY_SENDER_NAME or "Roy").strip()
    model = (settings.USER_LLM_MODEL or "gemini-1.5-flash").strip()

    # Extract verified gaps
    verified_gaps = [
        e.claim
        for e in evidence
        if e.evidence_type in ("verified_observation", "explicit_intent")
    ]
    evidence_text = "\n".join(f"• {g}" for g in verified_gaps) if verified_gaps else "• No visible digital contact form or live booking widget found"

    # Extract reviews / friction
    source_fields = business.source_fields if isinstance(business.source_fields, dict) else {}
    reviews = source_fields.get("reviews") or []
    reviews_text = "; ".join(str(r) for r in reviews[:3]) if reviews else "None recorded"

    rec_svc = lead.recommended_service or "lead_management_followup"
    svc_display = SERVICE_DISPLAY_NAMES.get(rec_svc, rec_svc.replace("_", " "))

    rating_str = f"{business.rating:.1f}★" if business.rating is not None else "N/A"
    review_count_str = f"{business.review_count} reviews" if business.review_count is not None else "few reviews"

    prompt = f"""You are {sender_name}, founder at {agency_name}.
Write an ultra-personalized, high-converting 3-sentence B2B cold email to the owner of {business.name} in {business.locality or 'their local area'}.

PROSPECT AUDIT DATA:
• Business Name: {business.name}
• Category / Niche: {business.category or 'Local Business'}
• Location: {business.locality or business.address or 'Local Area'}
• Website: {business.website or 'No website URL listed'}
• Google Rating & Reviews: {rating_str} ({review_count_str}) on Google Maps
• Scraped Customer Feedback: {reviews_text}
• Verified Technical Gaps:
{evidence_text}
• Recommended Solution: {svc_display}
{f'• Additional Operator Focus: {custom_instruction}' if custom_instruction else ''}

AGENCY SERVICES & VALUE PROPOSITION (USE WHICHEVER SUITS STRICT LEAD ANALYSIS):
1. Website Gaps: If their website is missing, not responsive, or not user-friendly, pitch modern responsive website development with built-in lead capture that increases client conversion.
2. Reputation & Rating Gaps: If their Google rating is below 5 stars ({rating_str}) or has low reviews ({review_count_str}), pitch how our personalized automated system converts this gap into a dominant 5-star presence, significantly boosting monthly sales and total revenue.
3. Full Automation Suite: We provide complete business automation: taking leads, handling leads, multi-channel outreach, prompt follow-ups, 24/7 AI chatbot customer assistant, meeting scheduling, and ad management.

STRICT COPYWRITING RULES:
1. Sentence 1 (The Hook): Acknowledge their business and point out their specific verified situation (e.g. mention their {rating_str} rating ({review_count_str}) on Google Maps, or that their website is missing/not mobile-optimized).
2. Sentence 2 (The Solution & Revenue Impact): Explain how our personalized automation system bridges this exact gap to convert it into a 5-star presence and increase monthly sales and total revenue by a substantial margin through automated review generation, 24/7 AI chat assistance, and instant lead handling.
3. Sentence 3 (Low-Friction Call-to-Action): Ask a low-friction question (e.g. "Open to a quick 2-minute walkthrough outline of how this works for {business.locality or 'local'} teams?").
4. Tone: Confident, consultative, direct founder-to-founder. NEVER use generic clichés like "Hope this finds you well".
5. Word Count: 55-80 words.
6. Sign off strictly as:
Best,
{sender_name}
{agency_name}

Return ONLY the plain text of the email message. Do not include markdown code fences or subject line labels.
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 250,
        },
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=12.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if not candidates:
                return None
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return None
            text = parts[0].get("text", "").strip()
            # Clean markdown code blocks if present
            if text.startswith("```"):
                lines = text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
            return text if len(text) > 20 else None

    except urllib.error.HTTPError as err:
        logger.warning("Gemini API HTTP %s: %s", err.code, err.reason)
        return None
    except Exception as exc:
        logger.warning("Gemini personalizer error: %s", exc)
        return None
