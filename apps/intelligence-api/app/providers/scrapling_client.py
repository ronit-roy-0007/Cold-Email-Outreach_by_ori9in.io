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
RECOGNIZED_PUBLIC_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com",
    "hotmail.com", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com",
    "zoho.com", "mail.com", "gmx.com", "comcast.net", "verizon.net",
    "att.net", "sbcglobal.net", "cox.net", "charter.net", "bellsouth.net",
}

BLOCKED_EMAIL_DOMAINS = {
    "sentry.io", "wixpress.com", "example.com", "example.org", "schema.org",
    "domain.com", "email.com", "w3.org", "googleapis.com", "godaddy.com",
    "secureserver.net", "astigmatic.com", "yourdomain.com", "company.com",
    "website.com", "test.com", "mysite.com", "sample.com", "wordpress.org",
    "wix.com", "squarespace.com", "weebly.com", "shopify.com", "cloudflare.com",
    "bootstrap.com", "themeforest.net", "envato.com", "gravatar.com",
    "alluredigital.net", "google.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "linkedin.com", "youtube.com",
}

BLOCKED_LOCAL_PARTS = {
    "user", "name", "username", "filler", "yourname", "youremail",
    "test", "demo", "sample", "example", "admin", "webmaster",
    "no-reply", "noreply", "donotreply", "privacy", "postmaster",
}


def extract_root_domain(url_or_domain: str) -> str:
    """Extracts root domain e.g. 'https://www.deltaroofingnyc.com/page' -> 'deltaroofingnyc.com'"""
    if not url_or_domain:
        return ""
    clean = url_or_domain.lower().strip()
    if clean.startswith("http://") or clean.startswith("https://"):
        try:
            parsed = urllib.parse.urlparse(clean)
            host = parsed.netloc or parsed.path
        except Exception:
            host = clean
    else:
        host = clean.split("/")[0]
    host = host.split(":")[0].strip().rstrip(".")
    parts = host.split(".")
    if len(parts) >= 2:
        if len(parts) >= 3 and parts[-2] in ("co", "com", "net", "org", "gov", "edu") and len(parts[-1]) == 2:
            return ".".join(parts[-3:])
        return ".".join(parts[-2:])
    return host


def is_valid_business_email(email: str, website_url: str = "") -> bool:
    if not email or "@" not in email:
        return False
    clean = email.strip().lower().rstrip(".,;:!?'\"")
    parts = clean.split("@", 1)
    if len(parts) != 2:
        return False
    local_part, domain = parts[0].strip(), parts[1].strip()

    if not local_part or not domain:
        return False
    if local_part in BLOCKED_LOCAL_PARTS:
        return False
    if domain in BLOCKED_EMAIL_DOMAINS or any(domain.endswith("." + b) for b in BLOCKED_EMAIL_DOMAINS):
        return False
    if any(clean.endswith(ext) for ext in IGNORE_EXTENSIONS):
        return False

    # Domain Affinity check:
    # 1. Recognized public webmail used by local businesses
    if domain in RECOGNIZED_PUBLIC_MAIL_DOMAINS:
        return True

    # 2. Matches website root domain (e.g. sales@mightyroofingny.com for mightyroofingny.com)
    site_root = extract_root_domain(website_url)
    if site_root:
        email_root = extract_root_domain(domain)
        if email_root == site_root or site_root in domain or domain in site_root:
            return True
        # If it doesn't match the website and is not public webmail, it's a third-party theme/font/agency email!
        return False

    return True


@dataclass
class JobResult:
    status: str
    results: list[NormalizedListing] = field(default_factory=list)
    error: str | None = None
    raw_snapshot: Any = None


_SCRAPLING_JOBS: dict[str, JobResult] = {}


def extract_emails_from_html(html: str, website_url: str = "") -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()

    def _add_if_valid(raw_addr: str) -> None:
        clean = raw_addr.strip().lower().rstrip(".,;:!?'\"")
        if clean and clean not in seen and is_valid_business_email(clean, website_url):
            seen.add(clean)
            emails.append(clean)

    # 1. Parse mailto links
    try:
        sel = Selector(html)
        for mailto in sel.css("a[href^='mailto:']"):
            href = mailto.attrib.get("href", "")
            clean = href.replace("mailto:", "").split("?")[0].strip()
            if clean and "@" in clean:
                _add_if_valid(clean)
    except Exception:
        pass

    # 2. Parse text regex
    # De-obfuscate common anti-spam patterns: [at], (at), and Japanese fullwidth ＠
    clean_html = re.sub(r"\s*(?:\[at\]|\(at\)|＠)\s*", "@", html, flags=re.IGNORECASE)
    clean_html = re.sub(r"\s*(?:\[dot\]|\(dot\))\s*", ".", clean_html, flags=re.IGNORECASE)
    for match in EMAIL_REGEX.findall(clean_html):
        _add_if_valid(match)

    return emails


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
    Extracts verified email with domain affinity AND social media profiles (LinkedIn, IG, FB, X, YouTube).
    """
    if not website_url or not website_url.startswith("http"):
        return None, {}

    email: str | None = None
    socials: dict[str, str] = {}

    try:
        resp = Fetcher.get(website_url, timeout=5, retries=1)
        if resp.status == 200 and resp.html_content:
            ems = extract_emails_from_html(resp.html_content, website_url=website_url)
            if ems:
                email = ems[0]

            socials = extract_social_links_from_html(resp.html_content)

            # If no email found on homepage, search prioritized contact and quote pages
            if not email:
                sel = Selector(resp.html_content)
                contact_links: list[tuple[int, str]] = []
                for a in sel.css("a[href]"):
                    h = a.attrib.get("href", "").strip()
                    t = (a.text or "").lower()
                    h_low = h.lower()
                    if any(w in h_low or w in t for w in ("contact", "about", "team", "reach", "inquiry", "mail", "form", "quote", "estimate", "toiawase", "問合", "メール")):
                        c_url = urllib.parse.urljoin(website_url, h)
                        if c_url != website_url and c_url.startswith("http"):
                            # Prioritize contact/quote pages over about pages
                            priority = 0 if any(k in h_low for k in ("contact", "quote", "estimate", "reach")) else 1
                            if not any(existing_url == c_url for _, existing_url in contact_links):
                                contact_links.append((priority, c_url))

                contact_links.sort(key=lambda x: x[0])
                # Check up to 2 highest priority contact links with fast timeout
                for _, c_url in contact_links[:2]:
                    try:
                        c_resp = Fetcher.get(c_url, timeout=4, retries=1)
                        if c_resp.status == 200 and c_resp.html_content:
                            c_ems = extract_emails_from_html(c_resp.html_content, website_url=website_url)
                            if c_ems:
                                email = c_ems[0]
                            c_soc = extract_social_links_from_html(c_resp.html_content)
                            for k, v in c_soc.items():
                                if k not in socials:
                                    socials[k] = v
                            if email:
                                break
                    except Exception:
                        pass
    except Exception as exc:
        logger.debug("Failed crawling %s: %s", website_url, exc)

    return email, socials


def search_google_maps_via_scrapling(query: str, location: str, target_count: int = 60) -> list[dict[str, Any]]:
    search_term = f"{query} in {location}".strip()
    encoded_search = urllib.parse.quote_plus(search_term)
    url = f"https://www.google.com/maps/search/{encoded_search}"

    logger.info("Scrapling searching Google Maps: %s (target: %d)", url, target_count)
    listings_raw: list[dict[str, Any]] = []

    scroll_cycles = max(4, min(target_count // 5, 8))

    def _scroll_feed(page: Any) -> None:
        try:
            feed = page.locator("div[role='feed']")
            feed.wait_for(timeout=8000)
            for _ in range(scroll_cycles):
                feed.evaluate("el => el.scrollBy(0, 2500)")
                page.wait_for_timeout(450)
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

        with ThreadPoolExecutor(max_workers=20) as pool:
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
