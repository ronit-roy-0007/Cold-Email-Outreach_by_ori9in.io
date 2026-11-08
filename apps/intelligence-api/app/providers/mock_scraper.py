from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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


def _get_fixtures_path() -> Path:
    candidates = [
        Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "businesses.json",
        Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "businesses.json",
        Path.cwd() / "tests" / "fixtures" / "businesses.json",
        Path.cwd().parent / "tests" / "fixtures" / "businesses.json",
        Path.cwd().parent.parent / "tests" / "fixtures" / "businesses.json",
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError("Could not find tests/fixtures/businesses.json fixture file")


def load_fixture_businesses() -> list[dict[str, Any]]:
    path = _get_fixtures_path()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def create_mock_job(
    query: str = "",
    location: str = "",
    limit: int = 25,
    filters: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    fixtures = load_fixture_businesses()
    effective_limit = max(1, limit) if limit is not None else 25
    results = fixtures[:effective_limit]
    job_id = f"mock-{uuid.uuid4()}"
    _MOCK_JOBS[job_id] = {
        "job_id": job_id,
        "status": "completed",
        "results": results,
        "query": query,
        "location": location,
        "limit": effective_limit,
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
