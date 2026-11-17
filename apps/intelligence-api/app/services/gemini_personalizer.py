from __future__ import annotations

import collections
import json
import logging
import re
import threading
import time
from typing import Any
import urllib.request
import urllib.error

from app.config import Settings
from app.models import Business, Evidence, Lead
from app.services.drafts import SERVICE_DISPLAY_NAMES

logger = logging.getLogger("gemini_personalizer")

SERVICE_GAP_DESCRIPTIONS: dict[str, str] = {
    "website_development": "no active website listed online for their business",
    "website_redesign": "website is outdated and not fully mobile-responsive",
    "real_estate_listing_portal": "no direct property listing search or filter portal for buyers browsing their site",
    "ai_chatbot": "no 24/7 AI chat assistant to engage visitors and capture inquiries after hours or on weekends",
    "business_process_automation": "manual lead intake and slow client callback and scheduling processes",
    "lead_management_followup": "no instant automated intake or prompt multi-channel follow-up system for new inquiries",
    "crm_appointment_automation": "no direct online appointment booking or showing scheduling option on their website",
}


class GeminiRateLimiter:
    """
    Thread-safe sliding-window rate limiter ensuring Google Gemini Free Tier
    never exceeds the 15 Requests Per Minute (RPM) ceiling.
    Limits to 14 requests per 60-second rolling window with minimum 4.1s spacing.
    """
    def __init__(self, max_rpm: int = 14, min_interval_seconds: float = 4.1):
        self.max_rpm = max_rpm
        self.min_interval = min_interval_seconds
        self.timestamps: collections.deque[float] = collections.deque()
        self.last_call: float = 0.0
        self.lock = threading.Lock()

    def acquire(self) -> None:
        with self.lock:
            now = time.time()
            # 1. Clean timestamps older than 60 seconds
            while self.timestamps and now - self.timestamps[0] > 60.0:
                self.timestamps.popleft()

            # 2. If at capacity (>= 14 in last 60s), wait until oldest timestamp expires
            if len(self.timestamps) >= self.max_rpm:
                sleep_time = 60.0 - (now - self.timestamps[0]) + 0.2
                if sleep_time > 0:
                    logger.info("Gemini Rate Limiter: Approaching 15 RPM limit. Pacing request by sleeping %.2fs...", sleep_time)
                    time.sleep(sleep_time)
                    now = time.time()
                    while self.timestamps and now - self.timestamps[0] > 60.0:
                        self.timestamps.popleft()

            # 3. Ensure minimum interval spacing between calls
            elapsed_since_last = now - self.last_call
            if elapsed_since_last < self.min_interval:
                spacing_sleep = self.min_interval - elapsed_since_last
                time.sleep(spacing_sleep)
                now = time.time()

            self.timestamps.append(now)
            self.last_call = now


_GEMINI_LIMITER = GeminiRateLimiter(max_rpm=14, min_interval_seconds=4.1)


def generate_gemini_pitch(
    *,
    business: Business,
    lead: Lead,
    evidence: list[Evidence],
    settings: Settings,
    custom_instruction: str | None = None,
    agency_name: str | None = None,
    sender_name: str | None = None,
) -> str | None:
    """
    Uses Google Gemini (Free API) to deeply analyze audited prospect data and generate
    a hyper-personalized, 3-sentence high-converting B2B outreach email.
    
    Falls back gracefully (returns None) if API key is not configured or if an error occurs.
    """
    api_key = (settings.USER_LLM_API_KEY or "").strip()
    if not api_key:
        return None

    agency_name = (agency_name or settings.AGENCY_NAME or "IntentLead").strip()
    sender_name = (sender_name or settings.AGENCY_SENDER_NAME or "Alex").strip()
    model = (settings.USER_LLM_MODEL or "gemini-1.5-flash").strip()

    rec_svc = lead.recommended_service or "lead_management_followup"
    svc_display = SERVICE_DISPLAY_NAMES.get(rec_svc, rec_svc.replace("_", " "))
    target_gap = SERVICE_GAP_DESCRIPTIONS.get(
        rec_svc,
        "lack of automated systems for instant lead capture and follow-up",
    )

    # Filter out positive observations so Gemini does not confuse positive features for gaps
    positive_markers = (
        "meta tag is present",
        "link found",
        "controls found",
        "form found",
        "widget is visible",
    )
    verified_gaps = [
        e.claim
        for e in evidence
        if (
            (e.evidence_type in ("verified_observation", "explicit_intent", "inference"))
            and not any(m in e.claim.lower() for m in positive_markers)
        )
    ]
    if not verified_gaps:
        verified_gaps = [target_gap]
    evidence_text = "\n".join(f"• {g}" for g in verified_gaps)

    # Extract reviews / friction
    source_fields = business.source_fields if isinstance(business.source_fields, dict) else {}
    reviews = source_fields.get("reviews") or []
    reviews_text = "; ".join(str(r) for r in reviews[:3]) if reviews else "None recorded"

    rating_str = f"{business.rating:.1f}★" if business.rating is not None else "N/A"
    review_count_str = f"{business.review_count} reviews" if business.review_count is not None else "few reviews"

    prompt = f"""You are {sender_name}, founder at {agency_name}.
Write an ultra-personalized, high-converting, concise 3-sentence B2B email to the owner of {business.name} in {business.locality or 'their local area'}.

PROSPECT AUDIT DATA:
• Business Name: {business.name}
• Category / Niche: {business.category or 'Local Business'}
• Location: {business.locality or business.address or 'Local Area'}
• Website: {business.website or 'No website URL listed'}
• Google Rating & Reviews: {rating_str} ({review_count_str}) on Google Maps
• Scraped Customer Feedback: {reviews_text}
• Specific Gap To Address: {target_gap}
• Verified Gaps:
{evidence_text}
• Recommended Solution: {svc_display}
{f'• Additional Operator Focus: {custom_instruction}' if custom_instruction else ''}

STRICT COPYWRITING RULES (MUST FOLLOW ALL RULES EXACTLY):
1. Greeting: Start strictly with "Hi {business.name}," on the very first line. NEVER write "Hi team", "Hi team at", "Hi there", or "Dear".
2. Sentence 1 (The Gap Hook): Directly point out their specific gap: "{target_gap}". Sound like a helpful peer who just took a look at their website or presence.
CRITICAL COHERENCE RULE: The hook MUST logically match the recommended solution! If pitching appointment booking, mention the lack of an online viewing/booking option on their site. DO NOT mention website responsiveness unless the solution being pitched is website redesign!
3. Sentence 2 (The Solution & Benefit): Briefly explain how our custom automated system ({svc_display}) solves that exact problem for {business.name} so they never lose qualified inquiries or high-intent clients to competitors.
4. Sentence 3 (The Exact Call-To-Action): Must conclude strictly with this exact question:
"Should I show you the demo how it works? Then we can talk further if you are interested."
5. Tone: Conversational, human, peer-to-peer. NEVER sound like a pushy cold email or generic spam.
6. Length: 45 to 70 words max (short, punchy, easy to read on a phone).
7. Sign off strictly as:
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
            "maxOutputTokens": 800,
            "thinkingConfig": {
                "thinkingBudget": 0
            },
        },
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    if api_key != "test-gemini-key":
        _GEMINI_LIMITER.acquire()

    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
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
            # Strip accidental Subject: line if Gemini outputs one
            if text.lower().startswith("subject:"):
                subj_parts = text.split("\n", 1)
                text = subj_parts[1].strip() if len(subj_parts) > 1 else text
            # Ensure greeting never uses 'team' or 'team at'
            text = re.sub(r"^Hi\s+team\s+at\s+", "Hi ", text, flags=re.IGNORECASE)
            text = re.sub(r"^Hi\s+team,?\s*", f"Hi {business.name},\n\n", text, flags=re.IGNORECASE)
            return text if len(text) > 20 else None

    except urllib.error.HTTPError as err:
        if err.code == 429:
            logger.warning("Gemini Free API 429 Rate Limit ceiling reached. Pacing requests or falling back gracefully.")
        else:
            logger.warning("Gemini API HTTP %s: %s", err.code, err.reason)
        return None
    except Exception as exc:
        logger.warning("Gemini personalizer error: %s", exc)
        return None
