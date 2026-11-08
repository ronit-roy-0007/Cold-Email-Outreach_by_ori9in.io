from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import httpx

from app.providers.mock_scraper import create_mock_job, get_mock_job
from app.providers.types import NormalizedListing


class ScraperError(Exception):
    pass


@dataclass
class JobResult:
    status: str
    results: list[NormalizedListing] = field(default_factory=list)
    error: str | None = None
    raw_snapshot: Any = None


def map_gosom_listing(raw: dict[str, Any], discovery_source: str) -> NormalizedListing:
    place_id = raw.get("placeId") or raw.get("place_id") or raw.get("data_id") or raw.get("cid") or raw.get("link")
    name = raw.get("title") or raw.get("name") or ""
    category = raw.get("category")
    address = raw.get("address") or raw.get("complete_address")
    locality = raw.get("locality") or raw.get("city")

    website = raw.get("website") or raw.get("WebSite")
    if website is not None:
        website_str = str(website).strip()
        website = website_str if website_str else None
    else:
        website = None

    phone = raw.get("phone")

    emails = raw.get("emails")
    email: str | None = None
    if isinstance(emails, list) and len(emails) > 0 and emails[0]:
        email = str(emails[0]).strip()
    elif isinstance(emails, str) and emails.strip():
        clean_emails = [e.strip(" '\"[]") for e in emails.split(",") if e.strip(" '\"[]")]
        email = clean_emails[0] if clean_emails else None
    elif raw.get("email"):
        email = str(raw.get("email")).strip()

    rating_raw = raw.get("rating") if "rating" in raw else raw.get("review_rating")
    rating: float | None = None
    if rating_raw is not None:
        try:
            rating = float(rating_raw)
        except (ValueError, TypeError):
            rating = None

    review_count_raw = raw.get("reviewCount") if "reviewCount" in raw else raw.get("review_count")
    review_count: int | None = None
    if review_count_raw is not None:
        try:
            review_count = int(review_count_raw)
        except (ValueError, TypeError):
            review_count = None

    listing_status = raw.get("listingStatus") or raw.get("listing_status") or raw.get("status")
    reviews = list(raw.get("reviews") or [])

    return NormalizedListing(
        place_id=place_id,
        name=name,
        category=category,
        address=address,
        locality=locality,
        website=website,
        phone=phone,
        email=email,
        rating=rating,
        review_count=review_count,
        listing_status=listing_status,
        source_fields=raw,
        discovery_source=discovery_source,
        reviews=reviews,
    )


class ScraperClient:
    def __init__(
        self,
        base_url: str = "",
        token: str = "",
        provider: str = "mock",
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.strip() if base_url else ""
        self.token = token.strip() if token else ""
        self.provider = provider
        self.timeout = int(timeout) if timeout == 10.0 else timeout
        self.transport = transport

    def _get_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request_with_retry(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        max_retries = 2
        attempt = 0
        last_response: httpx.Response | None = None

        while attempt <= max_retries:
            attempt += 1
            try:
                with httpx.Client(
                    transport=self.transport,
                    timeout=float(self.timeout),
                    headers=self._get_headers(),
                ) as client:
                    resp = client.request(method, url, **kwargs)
                    last_response = resp

                if resp.status_code in (429, 502, 503):
                    if attempt <= max_retries:
                        continue
                    raise ScraperError(
                        f"Scraper temporary failure (status {resp.status_code}): {resp.text}"
                    )

                if resp.status_code >= 400:
                    raise ScraperError(
                        f"Scraper request failed (status {resp.status_code}): {resp.text}"
                    )

                return resp

            except httpx.RequestError as exc:
                if attempt <= max_retries and isinstance(
                    exc, (httpx.ConnectError, httpx.TimeoutException)
                ):
                    continue
                raise ScraperError(f"Scraper network error: {exc}") from exc

        if last_response is not None:
            raise ScraperError(
                f"Scraper request failed after retries (status {last_response.status_code})"
            )
        raise ScraperError("Scraper request failed after retries")

    def create_job(
        self,
        query: str,
        location: str,
        limit: int = 25,
        filters: dict[str, Any] | None = None,
    ) -> str:
        if self.provider == "mock":
            job_id, _ = create_mock_job(
                query=query, location=location, limit=limit, filters=filters
            )
            return job_id

        if self.provider == "live":
            if not self.base_url:
                raise ScraperError("GOOGLE_MAPS_SCRAPER_BASE_URL missing")
            clean_base = self.base_url.rstrip("/")
            endpoint = f"{clean_base}/jobs"
            kw = f"{query} in {location}".strip() if location else query
            payload = {
                "name": f"{query} - {location}".strip(" -") or "Search",
                "keywords": [kw],
                "lang": "en",
                "depth": max(1, min(limit // 10, 10)) if limit else 5,
                "max_time": 300,
                "email": True,
                "fast_mode": False,
                "query": query,
                "location": location,
                "limit": limit,
                "filters": filters or {},
            }
            try:
                resp = self._request_with_retry("POST", endpoint, json=payload)
            except ScraperError as exc:
                if "/api/v1" not in endpoint and ("404" in str(exc) or "not found" in str(exc).lower()):
                    endpoint = f"{clean_base}/api/v1/jobs"
                    resp = self._request_with_retry("POST", endpoint, json=payload)
                else:
                    raise
            data = resp.json()
            job_id = data.get("job_id") or data.get("id") or data.get("ID")
            if not job_id:
                raise ScraperError("Missing job_id in scraper response")
            return str(job_id)

        raise ScraperError(f"Unsupported discovery provider: {self.provider}")

    def get_job(self, job_id: str) -> JobResult:
        if self.provider == "mock":
            job = get_mock_job(job_id)
            if not job:
                raise ScraperError(f"Mock job not found: {job_id}")
            results = [map_gosom_listing(r, "mock") for r in job.get("results", [])]
            return JobResult(
                status=job.get("status", "completed"),
                results=results,
                error=job.get("error"),
                raw_snapshot=job.get("results"),
            )

        if self.provider == "live":
            if not self.base_url:
                raise ScraperError("GOOGLE_MAPS_SCRAPER_BASE_URL missing")
            clean_base = self.base_url.rstrip("/")
            endpoint = f"{clean_base}/jobs/{job_id}"
            try:
                resp = self._request_with_retry("GET", endpoint)
            except ScraperError as exc:
                if "/api/v1" not in endpoint and ("404" in str(exc) or "not found" in str(exc).lower()):
                    endpoint = f"{clean_base}/api/v1/jobs/{job_id}"
                    resp = self._request_with_retry("GET", endpoint)
                else:
                    raise
            data = resp.json()
            raw_status = str(data.get("status") or data.get("Status") or "unknown")
            norm_status = raw_status.lower()
            if norm_status in ("ok", "completed", "success"):
                status_str = "completed"
            elif norm_status in ("failed", "error"):
                status_str = "failed"
            elif norm_status in ("pending", "working", "running"):
                status_str = "pending"
            else:
                status_str = norm_status

            raw_results = data.get("results") or []
            if status_str == "completed" and not raw_results:
                dl_endpoint = endpoint.replace(f"/{job_id}", f"/{job_id}/download")
                try:
                    dl_resp = self._request_with_retry("GET", dl_endpoint)
                    if dl_resp.status_code == 200 and dl_resp.text.strip():
                        import csv
                        import io
                        reader = csv.DictReader(io.StringIO(dl_resp.text))
                        raw_results = list(reader)
                except Exception:
                    pass

            results = [map_gosom_listing(r, "live") for r in raw_results]
            return JobResult(
                status=status_str,
                results=results,
                error=data.get("error") or data.get("Error"),
                raw_snapshot=data,
            )

        raise ScraperError(f"Unsupported discovery provider: {self.provider}")
