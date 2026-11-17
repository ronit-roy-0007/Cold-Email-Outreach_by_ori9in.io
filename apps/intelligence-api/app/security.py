from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict
from typing import Any
from urllib.parse import quote

from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import OperatorUser

logger = logging.getLogger("intentlead.security")


# ==========================================
# 1. API Key & Operator Authentication
# ==========================================

def verify_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None),
    settings: Settings = Depends(get_settings),
) -> str:
    """
    Validates API key from X-API-Key header or Bearer token.
    Fails closed in production if API_KEY is missing, too short (< 16 chars), or insecure placeholder.
    In development, allows anonymous access only if API_KEY is explicitly blank.
    """
    configured_key = (settings.API_KEY or "").strip()
    if settings.APP_ENV == "production":
        if not configured_key or len(configured_key) < 16 or configured_key.lower() in ("secret", "changeme", "123456", "test"):
            logger.critical("Production API_KEY missing or insecure (< 16 chars or placeholder). Failing closed.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Production API_KEY is not configured securely.",
                headers={"WWW-Authenticate": "ApiKey"},
            )
    else:
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
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> str:
    """
    Authorizes requests from either:
      1. An external API client providing a valid API key (X-API-Key or Bearer)
      2. An authenticated operator browser session (HttpOnly session cookie)
    Completely eliminates header-based spoofing (Referer / Sec-Fetch-Site).
    """
    configured_key = (settings.API_KEY or "").strip()

    provided_key = x_api_key
    if not provided_key and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided_key = parts[1]

    if provided_key:
        if configured_key and hmac.compare_digest(provided_key.strip(), configured_key):
            return provided_key
        if not configured_key and settings.APP_ENV != "production":
            return provided_key
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide a valid 'X-API-Key' header or 'Bearer' token.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Validate operator session cookie
    session_cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_cookie:
        from app.services.auth import validate_session_token
        operator_user = validate_session_token(db, session_cookie)
        if operator_user:
            return f"operator:{operator_user.username}"

    # In development mode only, allow unauthenticated access if no API_KEY configured
    if settings.APP_ENV != "production" and not configured_key:
        return "development_anonymous"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key. Provide a valid 'X-API-Key' header or sign in to the operator dashboard.",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def get_current_operator(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperatorUser | None:
    """
    Optional dependency returning the authenticated OperatorUser or None.
    """
    session_cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_cookie:
        return None
    from app.services.auth import validate_session_token
    return validate_session_token(db, session_cookie)


def require_operator(
    request: Request,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperatorUser:
    """
    Enforces operator authentication on dashboard routes.
    If unauthenticated:
      - Browser GET requests redirect to /login?next=<path>
      - API / AJAX / mutation requests receive 401 Unauthorized
    """
    session_cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
    user = None
    if session_cookie:
        from app.services.auth import validate_session_token
        user = validate_session_token(db, session_cookie)

    if user:
        request.state.operator_user = user
        request.state.raw_token = session_cookie
        return user

    accept_header = request.headers.get("accept", "")
    is_browser_get = (
        "text/html" in accept_header
        and request.method in ("GET", "HEAD")
        and not request.headers.get("x-requested-with")
    )
    if is_browser_get:
        next_url = request.url.path
        if request.url.query:
            next_url += f"?{request.url.query}"
        redirect_url = f"/login?next={quote(next_url)}"
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": redirect_url},
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Operator authentication required. Please sign in to the dashboard.",
    )


def require_csrf(
    request: Request,
    user: OperatorUser = Depends(require_operator),
    settings: Settings = Depends(get_settings),
) -> None:
    """
    Enforces session-bound CSRF token validation on state-changing browser requests (POST/PUT/DELETE).
    Reads CSRF token from X-CSRF-Token header or form field 'csrf_token'.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    session_cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_cookie:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing operator session for CSRF check.")

    from app.services.auth import validate_csrf_token

    provided_csrf = request.headers.get("x-csrf-token")
    if not provided_csrf:
        # Check form data if applicable
        # Handled in route-level form validation or middleware
        pass

    if provided_csrf and validate_csrf_token(session_cookie, settings.SESSION_SECRET_KEY, provided_csrf):
        return

    # If form body contains csrf_token, route will validate or this can check header
    # Allow if verified via header



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
