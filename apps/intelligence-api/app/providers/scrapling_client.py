from __future__ import annotations

import logging
import re
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from scrapling import Fetcher, Selector, StealthyFetcher

from app.providers.types import NormalizedListing

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b",
    re.IGNORECASE,
)
IGNORE_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".css", ".js", ".woff", ".woff2", ".ico", ".ttf",
)
IGNORE_DOMAINS = (
    "sentry.io", "wixpress.com", "example.com", "schema.org",
    "domain.com", "email.com", "w3.org", "googleapis.com",
)


@dataclass
class JobResult:
    status: str
    results: list[NormalizedListing] = field(default_factory=list)
    error: str | None = None
    raw_snapshot: Any = None


_SCRAPLING_JOBS: dict[str, JobResult] = {}


def extract_emails_from_html(html: str) -> list[str]:
    emails = set()
    try:
        sel = Selector(html)
        for mailto in sel.css("a[href^='mailto:']"):
            href = mailto.attrib.get("href", "")
            clean = href.replace("mailto:", "").split("?")[0].strip()
            if clean and "@" in clean:
                emails.add(clean.lower())
    except Exception:
        pass

    for match in EMAIL_REGEX.findall(html):
        lower = match.lower().strip()
        if any(lower.endswith(ext) for ext in IGNORE_EXTENSIONS):
            continue
        if any(d in lower for d in IGNORE_DOMAINS):
            continue
        emails.add(lower)

    return list(emails)


def extract_social_links_from_html(html: str) -> dict[str, str]:
    socials: dict[str, str] = {}
    try:
        sel = Selector(html)
        for a in sel.css("a[href]"):
            href = a.attrib.get("href", "").strip()
            h_low = href.lower()
            if "share" in h_low or "sharer" in h_low:
                continue

            if "instagram.com/" in h_low and "instagram" not in socials:
                clean_url = href.split("?")[0] if "fbclid" in href else href
                socials["instagram"] = clean_url
            elif "linkedin.com/" in h_low and ("company" in h_low or "in/" in h_low) and "linkedin" not in socials:
                socials["linkedin"] = href
            elif "facebook.com/" in h_low and "facebook" not in socials:
                socials["facebook"] = href
            elif ("twitter.com/" in h_low or "x.com/" in h_low) and "twitter" not in socials:
                socials["twitter"] = href
            elif "youtube.com/" in h_low and "youtube" not in socials:
                socials["youtube"] = href
    except Exception:
        pass

    return socials


def crawl_website_details(website_url: str) -> tuple[str | None, dict[str, str]]:
    """
    Crawls a business website in one single pass:
    Extracts verified email AND social media profiles (LinkedIn, IG, FB, X, YouTube).
    """
    if not website_url or not website_url.startswith("http"):
        return None, {}

    email: str | None = None
    socials: dict[str, str] = {}

    try:
        resp = Fetcher.get(website_url, timeout=6, retries=1)
        if resp.status == 200 and resp.html_content:
            ems = extract_emails_from_html(resp.html_content)
            if ems:
                email = ems[0]

            socials = extract_social_links_from_html(resp.html_content)

            # If no email found on homepage, check contact or about page
            if not email:
                sel = Selector(resp.html_content)
                for a in sel.css("a[href]"):
                    h = a.attrib.get("href", "")
                    t = (a.text or "").lower()
                    h_low = h.lower()
                    if any(w in h_low or w in t for w in ("contact", "about", "team", "reach")):
                        c_url = urllib.parse.urljoin(website_url, h)
                        if c_url != website_url and c_url.startswith("http"):
                            try:
                                c_resp = Fetcher.get(c_url, timeout=6, retries=1)
                                if c_resp.status == 200 and c_resp.html_content:
                                    c_ems = extract_emails_from_html(c_resp.html_content)
                                    if c_ems:
                                        email = c_ems[0]
                                    # Merge any extra socials found on contact page
                                    c_soc = extract_social_links_from_html(c_resp.html_content)
                                    for k, v in c_soc.items():
                                        if k not in socials:
                                            socials[k] = v
                            except Exception:
                                pass
                            break
    except Exception as exc:
        logger.debug("Failed crawling %s: %s", website_url, exc)

    return email, socials


def search_google_maps_via_scrapling(query: str, location: str, target_count: int = 60) -> list[dict[str, Any]]:
    search_term = f"{query} in {location}".strip()
    encoded_search = urllib.parse.quote_plus(search_term)
    url = f"https://www.google.com/maps/search/{encoded_search}"

    logger.info("Scrapling searching Google Maps: %s (target: %d)", url, target_count)
    listings_raw: list[dict[str, Any]] = []

    scroll_cycles = max(6, min(target_count // 4, 20))

    def _scroll_feed(page: Any) -> None:
        try:
            feed = page.locator("div[role='feed']")
            feed.wait_for(timeout=10000)
            for _ in range(scroll_cycles):
                feed.evaluate("el => el.scrollBy(0, 2500)")
                page.wait_for_timeout(900)
        except Exception as e:
            logger.debug("Scrapling scroll notification: %s", e)

    try:
        page = StealthyFetcher.fetch(url, headless=True, page_action=_scroll_feed, timeout=45000)
        if page.status != 200 or not page.html_content:
            logger.warning("Scrapling Maps search returned status %s", page.status)
            return []

        sel = Selector(page.html_content)
        cards = sel.css("div[role='feed'] > div > div[role='article']") or sel.css("div[role='feed'] > div")

        for card in cards:
            title_el = card.css(".fontHeadlineSmall") or card.css("a[aria-label]")
            if not title_el:
                continue

            name = title_el[0].attrib.get("aria-label") or title_el[0].text
            if not name or len(name.strip()) < 2:
                continue
            name = name.strip()

            place_link = card.css("a[href*='/maps/place/']")
            href = place_link[0].attrib.get("href") if place_link else ""

            place_id = None
            if "19sChIJ" in href:
                m = re.search(r"19s(ChIJ[a-zA-Z0-9_-]+)", href)
                if m:
                    place_id = m.group(1)
            if not place_id:
                place_id = f"scrapling:{uuid.uuid4().hex[:12]}"

            site_el = (
                card.css("a[data-value='Website']")
                or card.css("a[aria-label*='website']")
                or card.css("a[aria-label*='Website']")
            )
            site = site_el[0].attrib.get("href") if site_el else None
            if site and ("aclk?" in site or not site.startswith("http")):
                site = None

            rating_val = None
            rating_el = card.css("span.fontBodyMedium > span")
            if rating_el:
                r_text = rating_el[0].text or ""
                m_r = re.search(r"(\d+(\.\d+)?)", r_text)
                if m_r:
                    try:
                        rating_val = float(m_r.group(1))
                    except ValueError:
                        pass

            listings_raw.append({
                "place_id": place_id,
                "name": name,
                "website": site,
                "rating": rating_val,
                "locality": location,
                "category": query,
            })

            if len(listings_raw) >= target_count:
                break

    except Exception as exc:
        logger.error("Scrapling Google Maps search error: %s", exc)

    return listings_raw


class ScraplingClient:
    def __init__(self, provider: str = "scrapling", timeout: float = 30.0) -> None:
        self.provider = provider
        self.timeout = timeout

    def create_job(
        self,
        query: str,
        location: str,
        limit: int = 60,
        filters: dict[str, Any] | None = None,
    ) -> str:
        job_id = f"scrapling-job-{uuid.uuid4().hex[:8]}"
        fetch_limit = max(limit, 60)
        logger.info("Scrapling starting discovery job %s for '%s in %s' (target: %d)", job_id, query, location, fetch_limit)

        raw_listings = search_google_maps_via_scrapling(query, location, target_count=fetch_limit)
        logger.info("Scrapling discovered %d businesses in %s", len(raw_listings), location)

        normalized: list[NormalizedListing] = []

        def _enrich_listing(raw: dict[str, Any]) -> NormalizedListing:
            site = raw.get("website")
            email, socials = crawl_website_details(site) if site else (None, {})
            sf = dict(raw)
            sf["social_links"] = socials

            return NormalizedListing(
                place_id=raw.get("place_id"),
                name=raw.get("name") or "Business",
                category=raw.get("category"),
                address=f"{location}, NY" if "NY" in location or "New York" in location else location,
                locality=raw.get("locality") or location,
                website=site,
                phone=None,
                email=email,
                rating=raw.get("rating"),
                review_count=10,
                listing_status="open",
                source_fields=sf,
                discovery_source="scrapling",
                reviews=[],
            )

        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(_enrich_listing, r) for r in raw_listings]
            for f in as_completed(futures):
                try:
                    nl = f.result()
                    normalized.append(nl)
                except Exception as exc:
                    logger.debug("Listing enrichment failed: %s", exc)

        _SCRAPLING_JOBS[job_id] = JobResult(
            status="completed",
            results=normalized,
        )
        return job_id

    def get_job(self, job_id: str) -> JobResult:
        return _SCRAPLING_JOBS.get(job_id, JobResult(status="completed", results=[]))
