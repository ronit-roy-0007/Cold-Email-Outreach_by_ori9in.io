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
    candidates = [
        Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "sites",
        Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sites",
        Path.cwd() / "tests" / "fixtures" / "sites",
        Path.cwd().parent / "tests" / "fixtures" / "sites",
        Path.cwd().parent.parent / "tests" / "fixtures" / "sites",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    return candidates[0]


def fixture_fetcher(url: str) -> FetchResult:
    parsed = urllib.parse.urlparse(url)
    if "unreachable" in parsed.path:
        return FetchResult(status=0, final_url=url, error="website_unreachable")

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
    if not slug:
        slug = "brochure"

    target_file = fixtures_dir / f"{slug}.html"
    if target_file.is_file():
        return FetchResult(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body_bytes=target_file.read_bytes(),
            final_url=url,
        )

    return FetchResult(status=404, final_url=url, error="Not found")


def production_fetcher(url: str) -> FetchResult:
    current_url = url
    max_redirects = 3
    redirect_count = 0

    while redirect_count <= max_redirects:
        try:
            target = validate_public_url(current_url)
        except UnsafeURL as exc:
            return FetchResult(status=0, final_url=current_url, error=f"SSRF blocked: {exc}")

        try:
            with httpx.Client(
                timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
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
            fetcher = fixture_fetcher
        else:
            fetcher = production_fetcher

    now = datetime.now(timezone.utc)

    # 1. SSRF check
    is_fixture_domain = parsed.hostname == "fixtures.intentlead.test"
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
    if (
        "recaptcha" in body_text_lower
        or "hcaptcha" in body_text_lower
        or "cf-chl-bypass" in body_text_lower
        or hp_res.status == 402
    ):
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

    # Up to 5 pages crawl
    visited = {url}
    pages = [(url, hp_res.body_bytes.decode("utf-8", errors="replace"))]
    origin = f"{parsed.scheme}://{parsed.netloc}"

    link_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
    for link in link_pattern.findall(pages[0][1]):
        if len(visited) >= 5:
            break
        joined = urllib.parse.urljoin(url, link)
        clean_joined = joined.split("#")[0]
        if clean_joined.startswith(origin) and clean_joined not in visited:
            visited.add(clean_joined)
            p_res = fetcher(clean_joined)
            if p_res.status == 200 and "text/html" in p_res.headers.get("content-type", "text/html").lower():
                pages.append((clean_joined, p_res.body_bytes.decode("utf-8", errors="replace")))

    evidence_list: list[Evidence] = []
    all_pages_html = " ".join(p[1] for p in pages)
    all_pages_lower = all_pages_html.lower()

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

    # Listing search
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

    if session:
        for ev in evidence_list:
            session.add(ev)
        session.flush()

    return evidence_list
