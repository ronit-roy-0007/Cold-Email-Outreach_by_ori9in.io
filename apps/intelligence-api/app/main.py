from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.campaigns import router as campaigns_router
from app.api.leads import router as leads_router
from app.api.orchestrator import router as orchestrator_router
from app.config import get_settings, resolve_database_url
from app.providers.mock_scraper import mock_scraper_router
from app.web.routes import web_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    resolve_database_url(settings)
    yield


app = FastAPI(
    title="IntentLead AI Intelligence API",
    version="0.1.0",
    lifespan=lifespan,
)

# Register routers
app.include_router(mock_scraper_router)
app.include_router(campaigns_router)
app.include_router(leads_router)
app.include_router(orchestrator_router)
app.include_router(web_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
