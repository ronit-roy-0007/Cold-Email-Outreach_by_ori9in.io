from __future__ import annotations

import collections
from dataclasses import dataclass
import json
import logging
import re
import threading
import time
from typing import Any
import urllib.request
import urllib.error
import uuid

from app.config import Settings
from app.models import Business, Evidence, Lead
from app.services.drafts import SERVICE_DISPLAY_NAMES, generate_hook_subject

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


class GeminiError(Exception):
    """Base exception for Gemini personalization failures."""
    pass


class GeminiConfigError(GeminiError):
    """Raised when Gemini credentials or mandatory settings are absent."""
    pass


class GeminiRateLimitError(GeminiError):
    """Raised when Gemini rate limit (15 RPM free tier) is encountered."""
    pass


class GeminiAPIError(GeminiError):
    """Raised when the Gemini API returns an error or malformed payload."""
    pass


@dataclass
class GeminiPersonalizationResult:
    subject: str
    body: str
    generation_id: str
    model: str


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


def generate_gemini_personalized_draft(
    *,
    business: Business,
    lead: Lead,
    evidence: list[Evidence],
    settings: Settings,
    custom_instruction: str | None = None,
    agency_name: str | None = None,
    sender_name: str | None = None,
) -> GeminiPersonalizationResult:
    """
    Invokes Google Gemini to generate a structured, hyper-personalized B2B cold outreach
    email draft consisting of a curiosity-driven Subject Line and a concise 3-sentence Email Body.
    
    Raises:
        GeminiConfigError: If USER_LLM_API_KEY is not configured.
        GeminiRateLimitError: If HTTP 429 quota exhaustion is received.
        GeminiAPIError: If the remote API fails or returns invalid/empty content.
    """
    api_key = (settings.USER_LLM_API_KEY or "").strip()
    if not api_key:
        raise GeminiConfigError("Google Gemini API key (USER_LLM_API_KEY) is not configured in settings or environment.")

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

    # Extract reviews / customer feedback
    source_fields = business.source_fields if isinstance(business.source_fields, dict) else {}
    reviews = source_fields.get("reviews") or []
    reviews_text = "; ".join(str(r) for r in reviews[:3]) if reviews else "None recorded"

    rating_str = f"{business.rating:.1f}★" if business.rating is not None else "N/A"
    review_count_str = f"{business.review_count} reviews" if business.review_count is not None else "few reviews"

    prompt = f"""You are {sender_name}, founder at {agency_name}.
Write an ultra-personalized, high-converting B2B cold email outreach message to the owner of {business.name} in {business.locality or 'their local area'}.

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

STRICT COPYWRITING RULES:
1. Subject Line:
   - Must be a punchy, curiosity-inducing question or observation directly relevant to {business.name} and their specific gap ({target_gap}).
   - Keep it short (4 to 8 words), natural, and lowercase or sentence case (e.g. "quick question about [gap topic] at {business.name}?" or "{business.name} online inquiries?").
   - NEVER use generic spam triggers like "Synergy", "Collaboration", "Boost your revenue", or "Special offer".
2. Email Body:
   - Greeting: Start strictly with "Hi {business.name}," on the very first line. NEVER write "Hi team", "Hi team at", "Hi there", or "Dear".
   - Sentence 1 (The Gap Hook): Directly point out their specific gap: "{target_gap}". Sound like a helpful peer who just audited their website or presence.
   - Sentence 2 (The Solution & Benefit): Briefly explain how our custom automated system ({svc_display}) solves that exact problem for {business.name} so they never lose qualified inquiries or high-intent clients to competitors.
   - Sentence 3 (The Exact Call-To-Action): Must conclude strictly with this exact question:
     "Should I show you the demo how it works? Then we can talk further if you are interested."
   - Tone: Conversational, human, peer-to-peer. NEVER sound like pushy cold email spam.
   - Length: 45 to 70 words max.
   - Sign off strictly as:
     Best,
     {sender_name}
     {agency_name}

OUTPUT FORMAT:
You MUST respond strictly with valid JSON with no preamble or commentary:
{{
  "subject": "The generated email subject line",
  "body": "The complete generated email body"
}}
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
            raw_body = resp.read().decode("utf-8")
            data = json.loads(raw_body)
    except urllib.error.HTTPError as err:
        if err.code == 429:
            logger.warning("Gemini Free API 429 Rate Limit ceiling reached.")
            raise GeminiRateLimitError("Google Gemini rate limit ceiling (15 RPM) reached. Please wait a moment and retry.")
        logger.warning("Gemini API HTTP %s: %s", err.code, err.reason)
        raise GeminiAPIError(f"Google Gemini API error HTTP {err.code}: {err.reason}")
    except (urllib.error.URLError, TimeoutError) as err:
        logger.warning("Gemini API connection error: %s", err)
        raise GeminiAPIError(f"Network error connecting to Google Gemini: {err}")
    except Exception as exc:
        logger.warning("Unexpected Gemini personalizer error: %s", exc)
        raise GeminiAPIError(f"Unexpected error communicating with Google Gemini: {exc}")

    candidates = data.get("candidates", [])
    if not candidates:
        raise GeminiAPIError("Google Gemini returned empty candidate list.")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise GeminiAPIError("Google Gemini returned empty candidate content.")

    raw_text = parts[0].get("text", "").strip()
    if not raw_text:
        raise GeminiAPIError("Google Gemini returned empty text content.")

    # 1. Clean markdown code fences if present
    cleaned = raw_text
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    subject: str = ""
    body: str = ""

    # 2. Attempt JSON parsing
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            subject = str(parsed.get("subject", "")).strip()
            body = str(parsed.get("body", "")).strip()
    except json.JSONDecodeError:
        # Fallback parsing for non-JSON or plain text output
        logger.debug("Gemini output was not valid JSON, applying heuristic extraction: %s", cleaned[:100])
        lines = cleaned.splitlines()
        for i, line in enumerate(lines):
            if line.lower().startswith("subject:"):
                subject = line.split(":", 1)[1].strip()
                body = "\n".join(lines[i + 1:]).strip()
                break
        if not body:
            body = cleaned

    # 3. Post-process and sanitize body
    if body.lower().startswith("subject:"):
        parts_s = body.split("\n", 1)
        if not subject and len(parts_s) > 1:
            subject = parts_s[0].split(":", 1)[1].strip()
        body = parts_s[1].strip() if len(parts_s) > 1 else body

    # Fix greeting anomalies
    body = re.sub(r"^Hi\s+team\s+at\s+", "Hi ", body, flags=re.IGNORECASE)
    body = re.sub(r"^Hi\s+team,?\s*", f"Hi {business.name},\n\n", body, flags=re.IGNORECASE)

    # 4. Fallback subject generation if model omitted subject
    if not subject:
        subject = generate_hook_subject(business.name, lead.recommended_service)

    if len(body) < 15:
        raise GeminiAPIError("Gemini generated draft body is too short or incomplete.")

    return GeminiPersonalizationResult(
        subject=subject,
        body=body,
        generation_id=str(uuid.uuid4()),
        model=model,
    )


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
    Backward-compatible wrapper returning only the personalized email body string.
    Preserves exact contract for existing unit tests and background campaign runners.
    """
    try:
        res = generate_gemini_personalized_draft(
            business=business,
            lead=lead,
            evidence=evidence,
            settings=settings,
            custom_instruction=custom_instruction,
            agency_name=agency_name,
            sender_name=sender_name,
        )
        return res.body if res else None
    except Exception as exc:
        logger.warning("Gemini personalizer error in generate_gemini_pitch: %s", exc)
        return None
