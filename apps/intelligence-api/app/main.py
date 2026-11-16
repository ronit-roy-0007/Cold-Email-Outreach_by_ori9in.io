from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.campaigns import router as campaigns_router
from app.api.leads import router as leads_router
from app.api.orchestrator import router as orchestrator_router
from app.api.outreach import router as outreach_router
from app.config import get_settings, resolve_database_url, validate_production_security
from app.db import engine, get_session
from app.models import Base
from app.providers.mock_scraper import mock_scraper_router
from app.web.routes import web_router

logger = logging.getLogger("intentlead.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    resolve_database_url(settings)
    validate_production_security(settings)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="IntentLead AI Intelligence API",
    description="Autonomous Google Maps & Web Scraper, Intent Scoring, and Multi-Mailbox Cold Outreach Engine.",
    version="0.2.0",
    lifespan=lifespan,
)

settings = get_settings()

# 1. CORS Middleware Hardening
cors_origins = [o.strip() for o in (settings.CORS_ORIGINS or "*").split(",") if o.strip()]
is_wildcard = cors_origins == ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins else ["*"],
    allow_credentials=not is_wildcard,  # Spec requirement: never allow credentials with wildcard origin
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# 2. Request Timing & Observability Middleware
@app.middleware("http")
async def request_observability_middleware(request: Request, call_next):
    start_time = time.time()
    try:
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
        if request.url.path not in ("/health", "/health/live"):
            logger.info(
                "%s %s -> status=%d duration=%.2fms",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
        return response
    except Exception as exc:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "Unhandled exception on %s %s (%.2fms): %s",
            request.method,
            request.url.path,
            duration_ms,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred. This event has been logged."},
        )


# 3. Health & Readiness Observability Probes
@app.get("/health", tags=["system"])
@app.get("/health/live", tags=["system"])
def health_live() -> dict[str, str]:
    return {"status": "ok", "version": "0.2.0"}


@app.get("/health/ready", tags=["system"])
def health_ready(db: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "database": "connected",
            "environment": settings.APP_ENV,
            "provider": settings.DISCOVERY_PROVIDER,
            "outreach_mode": "dry-run" if settings.OUTREACH_DRY_RUN else "live",
        }
    except Exception as exc:
        logger.error("Health ready check failed: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "database": "disconnected", "error": str(exc)},
        )


# 4. Register API Routers
app.include_router(mock_scraper_router)
app.include_router(campaigns_router)
app.include_router(leads_router)
app.include_router(orchestrator_router)
app.include_router(outreach_router)
app.include_router(web_router)
