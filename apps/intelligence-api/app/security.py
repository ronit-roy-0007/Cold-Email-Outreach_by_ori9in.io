from __future__ import annotations

import hmac
import time
from collections import defaultdict
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings


# ==========================================
# 1. API Key Authentication Dependency
# ==========================================

def verify_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None),
    settings: Settings = Depends(get_settings),
) -> str:
    """
    Validates API key from X-API-Key header or Bearer token.
    If settings.API_KEY is not configured, allows requests for local development.
    If configured, strictly requires a matching key.
    """
    configured_key = (settings.API_KEY or "").strip()
    if not configured_key:
        return "development_anonymous"

    provided_key = x_api_key
    if not provided_key and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided_key = parts[1]

    if not provided_key or not hmac.compare_digest(provided_key.strip(), configured_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide a valid 'X-API-Key' header or 'Bearer' token.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return provided_key


# ==========================================
# 2. In-Memory Sliding-Window Rate Limiter
# ==========================================

class InMemoryRateLimiter:
    def __init__(self):
        self._requests: dict[str, list[float]] = defaultdict(list)

    def reset(self) -> None:
        self._requests.clear()

    def is_allowed(self, client_ip: str, max_requests: int, window_seconds: int = 60) -> bool:
        if max_requests <= 0:
            return True

        now = time.time()
        cutoff = now - window_seconds
        timestamps = self._requests[client_ip]

        # Prune old timestamps
        self._requests[client_ip] = [t for t in timestamps if t > cutoff]

        if len(self._requests[client_ip]) >= max_requests:
            return False

        self._requests[client_ip].append(now)
        return True


rate_limiter = InMemoryRateLimiter()


async def check_rate_limit(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    client_ip = request.client.host if request.client else "127.0.0.1"
    limit = settings.RATE_LIMIT_PER_MINUTE

    if not rate_limiter.is_allowed(client_ip, max_requests=limit, window_seconds=60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded ({limit} requests/minute). Please slow down.",
        )


# ==========================================
# 3. Typed Pydantic Request Validation Models
# ==========================================

class CampaignCreateSchema(BaseModel):
    niche: str = Field(..., min_length=2, max_length=120, description="Target client industry or niche")
    location: str = Field(..., min_length=2, max_length=150, description="Target city, state or region")
    requested_quantity: int = Field(default=50, ge=1, le=500, description="Target number of qualified leads")
    target_services: list[str] = Field(default_factory=list, description="Target services offered by agency")
    filters: dict[str, Any] = Field(default_factory=dict, description="Scoring benchmark filters and settings")
    provider: str | None = Field(default=None, description="Discovery provider: scrapling, live, or mock")
    dry_run: bool | None = Field(default=None, description="Safety mode toggle")


class ApprovalActionSchema(BaseModel):
    action: str = Field(..., pattern="^(approve|reject|skip)$", description="Approval action")
    user_id: str | None = Field(default="api_operator", max_length=64, description="Operator user identifier")


class WebhookComplaintSchema(BaseModel):
    email: str = Field(..., description="Recipient email address reporting complaint")
    reason: str = Field(default="complaint", description="Complaint reason")
