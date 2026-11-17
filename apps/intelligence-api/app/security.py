from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings

logger = logging.getLogger("intentlead.security")


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


def verify_api_key_or_operator(
    request: Request,
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None),
    settings: Settings = Depends(get_settings),
) -> str:
    """
    Validates API key for external API clients, or authorizes same-origin operator
    requests originating from the IntentLead AI web dashboard without exposing credentials to JS.
    """
    configured_key = (settings.API_KEY or "").strip()
    if not configured_key:
        return "development_anonymous"

    provided_key = x_api_key
    if not provided_key and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided_key = parts[1]

    if provided_key:
        if hmac.compare_digest(provided_key.strip(), configured_key):
            return provided_key
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide a valid 'X-API-Key' header or 'Bearer' token.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    sec_fetch_site = request.headers.get("sec-fetch-site")
    referer = request.headers.get("referer")
    host = request.headers.get("host")

    if sec_fetch_site in ("same-origin", "same-site") or (referer and host and host in referer):
        return "web_operator"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key. Provide a valid 'X-API-Key' header or 'Bearer' token.",
        headers={"WWW-Authenticate": "ApiKey"},
    )


# ==========================================
# 2. Distributed & In-Memory Rate Limiter
# ==========================================

def extract_client_ip(request: Request, trusted_proxies_str: str = "127.0.0.1,::1") -> str:
    """
    Secure client IP extraction with reverse proxy validation.
    Prevents IP spoofing: X-Forwarded-For is ONLY trusted if the direct connection
    originates from an authorized upstream proxy (e.g. Docker gateway, Nginx, ALB).
    """
    direct_ip = request.client.host if request.client else "127.0.0.1"
    trusted = {p.strip().lower() for p in trusted_proxies_str.split(",") if p.strip()}

    if direct_ip.lower() not in trusted:
        # Untrusted direct connection - ignore any client-supplied X-Forwarded-For
        return direct_ip

    forwarded_for = request.headers.get("x-forwarded-for")
    if not forwarded_for:
        return direct_ip

    # Parse X-Forwarded-For chain from right to left
    parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
    for ip in reversed(parts):
        if ip.lower() not in trusted:
            return ip

    return parts[0] if parts else direct_ip


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


class DistributedRateLimiter:
    """
    Production-grade distributed rate limiter backed by Redis.
    - Uses atomic Redis sorted-set operations for multi-worker synchronization.
    - Degrades safely and transparently to in-memory sliding window during Redis outages.
    - Preserves existing is_allowed() and reset() interfaces.
    """
    def __init__(self, redis_url: str | None = None):
        self._local = InMemoryRateLimiter()
        self._redis = None
        self._redis_url = None
        if redis_url and redis_url.strip():
            self.init_redis(redis_url)

    def init_redis(self, redis_url: str) -> None:
        try:
            import redis
            self._redis_url = redis_url.strip()
            self._redis = redis.Redis.from_url(
                self._redis_url,
                socket_timeout=1.5,
                socket_connect_timeout=1.5,
                decode_responses=True,
            )
        except Exception:
            self._redis = None

    def reset(self, client_ip: str | None = None) -> None:
        self._local.reset()
        if self._redis:
            try:
                if client_ip:
                    self._redis.delete(f"rate_limit:{client_ip}")
                else:
                    keys = self._redis.keys("rate_limit:*")
                    if keys:
                        self._redis.delete(*keys)
            except Exception:
                pass

    def is_allowed(self, client_ip: str, max_requests: int, window_seconds: int = 60) -> bool:
        if max_requests <= 0:
            return True

        if self._redis is not None:
            try:
                key = f"rate_limit:{client_ip}"
                now = time.time()
                cutoff = now - window_seconds
                member = f"{now:.6f}"

                pipe = self._redis.pipeline()
                pipe.zremrangebyscore(key, 0, cutoff)
                pipe.zcard(key)
                pipe.zadd(key, {member: now})
                pipe.expire(key, window_seconds + 5)
                results = pipe.execute()

                current_count = results[1]
                if current_count >= max_requests:
                    # Remove the tentatively added member since over limit
                    try:
                        self._redis.zrem(key, member)
                    except Exception:
                        pass
                    return False
                return True
            except Exception as exc:
                # Redis outage: fail-safe observable fallback to local in-memory sliding window
                logger.warning(
                    "Distributed Redis rate limiter error (%s); falling back to in-memory sliding window for client %s",
                    exc,
                    client_ip,
                )

        return self._local.is_allowed(client_ip, max_requests, window_seconds)


rate_limiter = DistributedRateLimiter()


async def check_rate_limit(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    # Ensure Redis client configured if REDIS_URL provided in settings
    if settings.REDIS_URL and rate_limiter._redis is None:
        rate_limiter.init_redis(settings.REDIS_URL)

    client_ip = extract_client_ip(request, settings.TRUSTED_PROXIES)
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
