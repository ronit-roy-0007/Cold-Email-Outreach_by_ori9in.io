from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.providers.prospect_generator import generate_candidate_businesses

# Enable sync httpx.Client usage with ASGITransport in tests
try:
    import httpx
    import anyio.from_thread
    from starlette.testclient import _TestClientTransport

    if not hasattr(httpx.ASGITransport, "__enter__"):
        _orig_asgi_init = httpx.ASGITransport.__init__

        def _compat_asgi_init(self, app, **kwargs):
            _orig_asgi_init(self, app=app, **kwargs)
            self._sync_transport = _TestClientTransport(
                app, anyio.from_thread.start_blocking_portal, app_state={}
            )

        httpx.ASGITransport.__init__ = _compat_asgi_init
        httpx.ASGITransport.__enter__ = lambda self: self
        httpx.ASGITransport.__exit__ = lambda self, *args: None
        httpx.ASGITransport.handle_request = (
            lambda self, request: self._sync_transport.handle_request(request)
        )
except Exception:
    pass

mock_scraper_router = APIRouter()

_MOCK_JOBS: dict[str, dict[str, Any]] = {}


def _get_fixtures_path() -> Path | None:
    current = Path(__file__).resolve()
    for p in current.parents:
        cand = p / "tests" / "fixtures" / "businesses.json"
        if cand.is_file():
            return cand
    cand = Path.cwd() / "tests" / "fixtures" / "businesses.json"
    if cand.is_file():
        return cand
    return None


def load_fixture_businesses() -> list[dict[str, Any]]:
    path = _get_fixtures_path()
    if path and path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def create_mock_job(
    query: str = "",
    location: str = "",
    limit: int = 25,
    filters: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    fixtures = load_fixture_businesses()
    effective_limit = max(1, limit) if limit is not None else 25

    query_str = (query or "").lower()
    loc_str = (location or "").lower()
    is_real_estate = any(w in query_str for w in ("real estate", "realty", "realtor", "property"))
    is_dallas = any(w in loc_str for w in ("dallas", "texas", "tx"))

    attempt = filters.get("attempt", 1) if (filters and isinstance(filters, dict)) else 1
    depth = filters.get("depth", 0) if (filters and isinstance(filters, dict)) else 0
    has_score_filter = bool(filters and isinstance(filters, dict) and filters.get("min_score", 0) > 0)
    has_dynamic = bool(filters and isinstance(filters, dict) and filters.get("dynamic", False))

    if is_real_estate and is_dallas and effective_limit <= 25 and not has_score_filter and not has_dynamic and attempt <= 1 and fixtures:
        results = fixtures[:effective_limit]
    else:
        seed_offset = (attempt - 1) * effective_limit + (depth * 5)
        results = generate_candidate_businesses(
            niche=query or "Real Estate",
            location=location or "Dallas, Texas",
            count=effective_limit,
            seed_offset=seed_offset,
        )

    job_id = f"mock-{uuid.uuid4()}"
    _MOCK_JOBS[job_id] = {
        "job_id": job_id,
        "status": "completed",
        "results": results,
        "query": query,
        "location": location,
        "limit": len(results),
    }
    return job_id, results


def get_mock_job(job_id: str) -> dict[str, Any] | None:
    return _MOCK_JOBS.get(job_id)


class MockJobCreateRequest(BaseModel):
    query: str = ""
    location: str = ""
    limit: int = 25
    filters: dict[str, Any] = Field(default_factory=dict)


@mock_scraper_router.post("/scraper/jobs")
@mock_scraper_router.post("/jobs")
def create_job_endpoint(payload: MockJobCreateRequest) -> dict[str, Any]:
    job_id, _ = create_mock_job(
        query=payload.query,
        location=payload.location,
        limit=payload.limit,
        filters=payload.filters,
    )
    return {"job_id": job_id, "status": "completed"}


@mock_scraper_router.get("/scraper/jobs/{job_id}")
@mock_scraper_router.get("/jobs/{job_id}")
def get_job_endpoint(job_id: str) -> dict[str, Any]:
    job = get_mock_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": job["status"], "results": job["results"]}
