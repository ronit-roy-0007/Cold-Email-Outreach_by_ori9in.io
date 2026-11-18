from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any
import urllib.parse
import uuid

import httpx
from sqlalchemy.orm import Session

from app.models import Business, Evidence
from app.services.robots import robots_allows
from app.services.ssrf import UnsafeURL, validate_public_url


@dataclass
class FetchResult:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body_bytes: bytes = b""
    final_url: str = ""
    error: str | None = None


def _get_fixtures_dir() -> Path:
    current = Path(__file__).resolve()
    for p in current.parents:
        cand = p / "tests" / "fixtures" / "sites"
        if cand.is_dir():
            return cand
    for p in (Path.cwd(), Path.cwd().parent, Path.cwd().parent.parent):
        cand = p / "tests" / "fixtures" / "sites"
        if cand.is_dir():
            return cand
    return current.parent


def make_fixture_fetcher(scenario: str = "brochure") -> Any:
    def _fetcher(url: str) -> FetchResult:
        parsed = urllib.parse.urlparse(url)
        fixtures_dir = _get_fixtures_dir()

        if parsed.path == "/robots.txt":
            robots_file = fixtures_dir / "robots.txt"
            if robots_file.is_file():
                return FetchResult(
                    status=200,
                    headers={"content-type": "text/plain"},
                    body_bytes=robots_file.read_bytes(),
                    final_url=url,
                )
            return FetchResult(status=404, final_url=url)

        slug = parsed.path.strip("/")
        if not slug or slug not in ("explicit_intent", "listing_form", "widgets", "whatsapp", "brochure", "unreachable"):
            slug = scenario

        if slug == "unreachable" or "unreachable" in parsed.path:
            return FetchResult(status=0, final_url=url, error="website_unreachable")

        target_file = fixtures_dir / f"{slug}.html"
        if target_file.is_file():
            return FetchResult(
                status=200,
                headers={"content-type": "text/html; charset=utf-8"},
                body_bytes=target_file.read_bytes(),
                final_url=url,
            )

        return FetchResult(status=404, final_url=url, error="Not found")
    return _fetcher


fixture_fetcher = make_fixture_fetcher("brochure")


def production_fetcher(url: str) -> FetchResult:
    current_url = url
    max_redirects = 3
    redirect_count = 0

    while redirect_count <= max_redirects:
        try:
            validate_public_url(current_url)
        except UnsafeURL as exc:
            return FetchResult(status=0, final_url=current_url, error=f"SSRF blocked: {exc}")

        try:
            with httpx.Client(
                timeout=httpx.Timeout(connect=10.0, read=10.0, write=5.0, pool=5.0),
                follow_redirects=False,
                headers={"User-Agent": "IntentLeadBot/1.0 (+https://intentlead.agency)"},
            ) as client:
                resp = client.get(current_url)
                if resp.is_redirect:
                    redirect_count += 1
                    loc = resp.headers.get("location")
                    if not loc:
                        return FetchResult(
                            status=resp.status_code,
                            headers=dict(resp.headers),
                            final_url=current_url,
                        )
                    current_url = urllib.parse.urljoin(current_url, loc)
                    continue

                content = resp.content
                if len(content) > 1_048_576:
                    content = content[:1_048_576]

                return FetchResult(
                    status=resp.status_code,
                    headers=dict(resp.headers),
                    body_bytes=content,
                    final_url=current_url,
                )
        except Exception as exc:
            return FetchResult(status=0, final_url=current_url, error=str(exc))

    return FetchResult(status=0, final_url=current_url, error="Too many redirects")


def audit_business(
    session: Session | None,
    campaign_id: uuid.UUID,
    business: Business,
    *,
    fetcher: Any = None,
) -> list[Evidence]:
    if not business.website or not business.website.strip():
        return []

    url = business.website.strip()
    parsed = urllib.parse.urlparse(url)

    if fetcher is None:
        if business.discovery_source == "mock" or "fixtures.intentlead.test" in (
            parsed.hostname or ""
        ):
            scenario = "brochure"
            if isinstance(business.source_fields, dict):
                scenario = business.source_fields.get("scenario", "brochure")
            fetcher = make_fixture_fetcher(scenario)
        else:
            fetcher = production_fetcher

    now = datetime.now(timezone.utc)

    # 1. SSRF check
    is_fixture_domain = (business.discovery_source == "mock") or (parsed.hostname == "fixtures.intentlead.test")
    resolver = (lambda h: ["93.184.216.34"]) if is_fixture_domain else None

    try:
        validate_public_url(url, resolver=resolver)
    except UnsafeURL as exc:
        ev = Evidence(
            business_id=business.id,
            campaign_id=campaign_id,
            claim="SSRF check blocked website URL",
            evidence_type="verified_observation",
            source_url=url,
            checked_at=now,
            inspected_scope="url validation",
            confidence="high",
            supporting_excerpt="ssrf_blocked",
            caveat=f"Target address is blocked by SSRF policy: {exc}; page not fetched",
        )
        if session:
            session.add(ev)
            session.flush()
        return [ev]

    # 2. robots.txt
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    robots_res = fetcher(robots_url)
    robots_txt = (
        robots_res.body_bytes.decode("utf-8", errors="replace")
        if robots_res.status == 200
        else None
    )

    if not robots_allows(robots_txt, url):
        ev = Evidence(
            business_id=business.id,
            campaign_id=campaign_id,
            claim="robots.txt disallows auditing",
            evidence_type="verified_observation",
            source_url=robots_url,
            checked_at=now,
            inspected_scope="robots.txt",
            confidence="high",
            supporting_excerpt="robots_disallow",
            caveat="Site disallowed crawler access; page content not inspected",
        )
        if session:
            session.add(ev)
            session.flush()
        return [ev]

    # 3. Homepage fetch
    hp_res: FetchResult = fetcher(url)

    if (
        hp_res.status == 0
        or hp_res.error
        or (hp_res.status >= 400 and hp_res.status not in (401, 403, 407))
    ):
        ev = Evidence(
            business_id=business.id,
            campaign_id=campaign_id,
            claim=f"Website unreachable ({hp_res.error or hp_res.status})",
            evidence_type="verified_observation",
            source_url=url,
            checked_at=now,
            inspected_scope="homepage fetch",
            confidence="high",
            supporting_excerpt="website_unreachable",
            caveat="Site returned an error or was unreachable; content not inspected",
        )
        if session:
            session.add(ev)
            session.flush()
        return [ev]

    if hp_res.status in (401, 403, 407):
        ev = Evidence(
            business_id=business.id,
            campaign_id=campaign_id,
            claim=f"Access restricted (HTTP {hp_res.status})",
            evidence_type="verified_observation",
            source_url=url,
            checked_at=now,
            inspected_scope="homepage fetch",
            confidence="high",
            supporting_excerpt="access_restricted",
            caveat="Access was restricted; page content not inspected",
        )
        if session:
            session.add(ev)
            session.flush()
        return [ev]

    # 4. CAPTCHA / paywall
    body_text_lower = hp_res.body_bytes.decode("utf-8", errors="replace").lower()
    is_challenge_gate = (
        hp_res.status == 402
        or "cf-chl-bypass" in body_text_lower
        or "<title>just a moment...</title>" in body_text_lower
        or "<title>attention required! | cloudflare</title>" in body_text_lower
        or "id=\"challenge-running\"" in body_text_lower
        or "id=\"challenge-stage\"" in body_text_lower
        or "class=\"cf-browser-verification\"" in body_text_lower
        or (hp_res.status in (403, 429) and any(term in body_text_lower for term in ("recaptcha", "hcaptcha", "captcha", "security check", "verify you are human")))
    )
    if is_challenge_gate:
        ev = Evidence(
            business_id=business.id,
            campaign_id=campaign_id,
            claim="Page presents CAPTCHA or paywall challenge",
            evidence_type="verified_observation",
            source_url=url,
            checked_at=now,
            inspected_scope="homepage fetch",
            confidence="high",
            supporting_excerpt="challenge_or_paywall",
            caveat="Encountered challenge or paywall; stopped without bypassing",
        )
        if session:
            session.add(ev)
            session.flush()
        return [ev]

    # 5. Content-type check
    ct = hp_res.headers.get("content-type", "text/html").lower()
    if "text/html" not in ct and "application/xhtml+xml" not in ct:
        ev = Evidence(
            business_id=business.id,
            campaign_id=campaign_id,
            claim="Non-HTML content type skipped",
            evidence_type="verified_observation",
            source_url=url,
            checked_at=now,
            inspected_scope="homepage headers",
            confidence="high",
            supporting_excerpt="content_type_skipped",
            caveat="Only HTML content is inspected",
        )
        if session:
            session.add(ev)
            session.flush()
        return [ev]

    # Fast lightweight audit: Homepage-first with optional single contact page fallback
    visited = {url}
    pages = [(url, hp_res.body_bytes.decode("utf-8", errors="replace"))]
    origin = f"{parsed.scheme}://{parsed.netloc}"

    hp_html = pages[0][1]
    hp_lower = hp_html.lower()

    # If contact form, appointment, or social links are not obvious on homepage, check at most 1 contact page
    has_obvious_contact = any(k in hp_lower for k in ("<form", "whatsapp", "wa.me", "contact us", "get in touch", "book online", "appointment", "toiawase", "mailform"))
    if not has_obvious_contact:
        link_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
        for link in link_pattern.findall(hp_html):
            clean_link = link.strip().lower()
            if any(term in clean_link for term in ("contact", "get-in-touch", "reach-us", "inquiry", "mail", "form", "toiawase")) and not any(ext in clean_link for ext in (".css", ".js", ".png", ".jpg", ".jpeg", ".pdf", ".xml", ".svg")):
                joined = urllib.parse.urljoin(url, link).split("#")[0]
                if joined.startswith(origin) and joined not in visited:
                    visited.add(joined)
                    p_res = fetcher(joined)
                    if p_res.status == 200 and "text/html" in p_res.headers.get("content-type", "text/html").lower():
                        pages.append((joined, p_res.body_bytes.decode("utf-8", errors="replace")))
                    break

    evidence_list: list[Evidence] = []
    all_pages_html = " ".join(p[1] for p in pages)
    all_pages_lower = all_pages_html.lower()

    # Fallback email extraction if not present from Google Maps
    if not getattr(business, "email", None) or not str(business.email).strip():
        mailto_match = re.search(r'mailto:([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', all_pages_html, re.IGNORECASE)
        if mailto_match:
            business.email = mailto_match.group(1).strip()
        else:
            email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', all_pages_html)
            if email_match:
                candidate = email_match.group(0).strip()
                if not any(candidate.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".js", ".css")):
                    business.email = candidate

    # Viewport
    has_viewport = any(
        re.search(r'<meta[^>]+name=["\']viewport["\']', p[1], re.IGNORECASE) for p in pages
    )
    if has_viewport:
        evidence_list.append(
            Evidence(
                business_id=business.id,
                campaign_id=campaign_id,
                claim="Mobile viewport meta tag is present",
                evidence_type="verified_observation",
                source_url=url,
                checked_at=now,
                inspected_scope="inspected pages",
                confidence="high",
                supporting_excerpt="has_viewport",
            )
        )
    else:
        evidence_list.append(
            Evidence(
                business_id=business.id,
                campaign_id=campaign_id,
                claim="No mobile viewport meta tag was found on the inspected pages",
                evidence_type="verified_observation",
                source_url=url,
                checked_at=now,
                inspected_scope="inspected pages",
                confidence="high",
                supporting_excerpt="no_viewport",
                caveat="Absence on inspected pages is not proof the feature does not exist elsewhere",
            )
        )

    # Form
    has_form = any(re.search(r'<form[^>]*>', p[1], re.IGNORECASE) for p in pages)
    if has_form:
        evidence_list.append(
            Evidence(
                business_id=business.id,
                campaign_id=campaign_id,
                claim="Inquiry or contact form found",
                evidence_type="verified_observation",
                source_url=url,
                checked_at=now,
                inspected_scope="inspected pages",
                confidence="high",
                supporting_excerpt="has_form",
            )
        )

    # Listing search (strictly for real estate & property niches)
    cat_lower = (business.category or "").lower()
    is_real_estate = any(k in cat_lower for k in ("real estate", "property", "realtor", "broker", "housing", "apartment", "estate agency"))
    if is_real_estate:
        has_listing_search = any(
            ("#search" in p[1].lower())
            or ("property_search" in p[1].lower())
            or ("search listings" in p[1].lower())
            or (re.search(r'(listing|property)\s*(search|filter)', p[1], re.IGNORECASE) is not None)
            for p in pages
        )
        if has_listing_search:
            evidence_list.append(
                Evidence(
                    business_id=business.id,
                    campaign_id=campaign_id,
                    claim="Property listing search or filter controls found",
                    evidence_type="verified_observation",
                    source_url=url,
                    checked_at=now,
                    inspected_scope="inspected pages",
                    confidence="high",
                    supporting_excerpt="has_listing_search",
                )
            )
        else:
            evidence_list.append(
                Evidence(
                    business_id=business.id,
                    campaign_id=campaign_id,
                    claim="No property search was visible on the inspected website pages",
                    evidence_type="verified_observation",
                    source_url=url,
                    checked_at=now,
                    inspected_scope="inspected pages",
                    confidence="medium",
                    supporting_excerpt="missing_listing_search",
                    caveat="Absence on inspected pages is not proof the feature does not exist elsewhere",
                )
            )

    # WhatsApp
    has_whatsapp = "wa.me" in all_pages_lower or "whatsapp" in all_pages_lower
    if has_whatsapp:
        evidence_list.append(
            Evidence(
                business_id=business.id,
                campaign_id=campaign_id,
                claim="Visible WhatsApp contact link found",
                evidence_type="verified_observation",
                source_url=url,
                checked_at=now,
                inspected_scope="inspected pages",
                confidence="high",
                supporting_excerpt="has_whatsapp",
            )
        )

    # Chatbot
    has_chatbot = any(k in all_pages_lower for k in ("chatbot", "tidio", "intercom", "drift"))
    if has_chatbot:
        evidence_list.append(
            Evidence(
                business_id=business.id,
                campaign_id=campaign_id,
                claim="Chatbot widget is visible",
                evidence_type="verified_observation",
                source_url=url,
                checked_at=now,
                inspected_scope="inspected pages",
                confidence="high",
                supporting_excerpt="has_chatbot",
            )
        )

    # Booking
    has_booking = any(k in all_pages_lower for k in ("book-now", "calendly", "booking widget"))
    if has_booking:
        evidence_list.append(
            Evidence(
                business_id=business.id,
                campaign_id=campaign_id,
                claim="Booking widget is visible",
                evidence_type="verified_observation",
                source_url=url,
                checked_at=now,
                inspected_scope="inspected pages",
                confidence="high",
                supporting_excerpt="has_booking",
            )
        )

    if not has_chatbot and not has_booking:
        evidence_list.append(
            Evidence(
                business_id=business.id,
                campaign_id=campaign_id,
                claim="No chatbot or booking widget found on inspected pages",
                evidence_type="inference",
                source_url=url,
                checked_at=now,
                inspected_scope="inspected pages",
                confidence="medium",
                supporting_excerpt="no_visible_chat_or_booking",
                caveat="Absence on inspected pages is not proof the business lacks internal automation",
            )
        )

    # Explicit intent
    intent_match = re.search(
        r"(looking for a vendor|we need a website|hire.*web)", all_pages_html, re.IGNORECASE
    )
    if intent_match:
        evidence_list.append(
            Evidence(
                business_id=business.id,
                campaign_id=campaign_id,
                claim="Page contains explicit intent: requesting website vendor",
                evidence_type="explicit_intent",
                source_url=url,
                checked_at=now,
                inspected_scope="inspected pages",
                confidence="high",
                supporting_excerpt=intent_match.group(0),
            )
        )

    # Discover social media handles from audited pages
    social_patterns = {
        "linkedin": r'https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_\-]+',
        "facebook": r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9_\.\-]+',
        "instagram": r'https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_\.\-]+',
        "twitter": r'https?://(?:www\.)?(?:twitter|x)\.com/[a-zA-Z0-9_\-]+',
        "reddit": r'https?://(?:www\.)?reddit\.com/(?:r|user)/[a-zA-Z0-9_\-]+',
        "telegram": r'https?://(?:www\.)?t\.me/[a-zA-Z0-9_\+]+',
    }
    if isinstance(business.source_fields, dict):
        sf_socials = business.source_fields.setdefault("social_links", {})
        for platform, pattern in social_patterns.items():
            if not sf_socials.get(platform):
                m = re.search(pattern, all_pages_html, re.IGNORECASE)
                if m:
                    sf_socials[platform] = m.group(0)
                    business.source_fields[platform] = m.group(0)

    if session:
        for ev in evidence_list:
            session.add(ev)
        session.flush()

    return evidence_list


def record_audit_log(
    db: Session,
    action: str,
    details: Any = None,
    entity_type: str = "system",
    entity_id: uuid.UUID | None = None,
    operator_id: str | None = None,
    actor: str | None = None,
    **kwargs: Any,
) -> Any:
    """
    Convenience helper to record an immutable audit trail entry.
    """
    from app.models import AuditLog

    eff_operator = operator_id or actor or "system"
    payload_data = details if isinstance(details, dict) else {"details": str(details or "")}
    if eff_operator:
        payload_data.setdefault("actor", eff_operator)

    log = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload_data,
    )
    db.add(log)
    db.flush()
    return log

