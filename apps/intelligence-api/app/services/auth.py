from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
from pathlib import Path
import secrets
import threading
import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import OperatorSession, OperatorUser, utc_now

logger = logging.getLogger("intentlead.auth")

# In-memory IP-based rate limiter for login attempts
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_LOCK = threading.Lock()


# ==============================================================================
# 1. Cryptographic Password Hashing (PBKDF2-HMAC-SHA256, 600,000 iterations)
# ==============================================================================

def hash_password(plain_password: str) -> str:
    """
    Hashes a plaintext password using PBKDF2-HMAC-SHA256 with 600,000 iterations
    and a cryptographically random 16-byte salt (OWASP 2024 compliance).
    Zero external C-dependencies; universally portable across Windows, Linux & macOS.
    """
    if not plain_password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_bytes(16)
    iterations = 600000
    derived = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plaintext password against a stored PBKDF2 hash using constant-time comparison.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        parts = hashed_password.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected_derived = bytes.fromhex(parts[3])
        derived = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(derived, expected_derived)
    except Exception:
        return False


# ==============================================================================
# 2. Session Token Generation & Verification
# ==============================================================================

def create_operator_session(
    db: Session,
    user: OperatorUser,
    request: Request | None = None,
    max_age_seconds: int = 86400,
) -> tuple[OperatorSession, str]:
    """
    Generates a secure 256-bit URL-safe session token, computes its SHA-256 hash,
    and stores the session record in PostgreSQL/SQLite. Returns (session_obj, raw_token).
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max_age_seconds)

    ip_address = None
    user_agent = None
    if request:
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")[:255]

    session_rec = OperatorSession(
        user_id=user.id,
        session_token_hash=token_hash,
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session_rec)
    user.last_login_at = utc_now()
    db.commit()
    db.refresh(session_rec)
    return session_rec, raw_token


def validate_session_token(db: Session, raw_token: str | None) -> OperatorUser | None:
    """
    Validates a raw session token against the database.
    Checks expiration and active user status.
    """
    if not raw_token or not raw_token.strip():
        return None
    token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
    session_rec = (
        db.query(OperatorSession)
        .filter(OperatorSession.session_token_hash == token_hash)
        .first()
    )
    if not session_rec:
        return None

    now = datetime.now(timezone.utc)
    # Handle both timezone-aware and naive SQLite dates safely
    exp = session_rec.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)

    if exp <= now:
        # Expired: clean up
        try:
            db.delete(session_rec)
            db.commit()
        except Exception:
            db.rollback()
        return None

    user = db.get(OperatorUser, session_rec.user_id)
    if not user or not user.is_active:
        return None

    return user


def destroy_operator_session(db: Session, raw_token: str | None) -> bool:
    """
    Invalidates an operator session upon logout.
    """
    if not raw_token or not raw_token.strip():
        return False
    token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
    deleted = (
        db.query(OperatorSession)
        .filter(OperatorSession.session_token_hash == token_hash)
        .delete()
    )
    db.commit()
    return deleted > 0


def cleanup_expired_sessions(db: Session) -> int:
    """
    Prunes expired sessions from the database.
    """
    now = datetime.now(timezone.utc)
    deleted = (
        db.query(OperatorSession)
        .filter(OperatorSession.expires_at <= now)
        .delete()
    )
    db.commit()
    return deleted


# ==============================================================================
# 3. Login Rate Limiting (5 attempts / 15 minutes per IP)
# ==============================================================================

def is_ip_rate_limited(ip: str, max_attempts: int = 5, window_seconds: int = 900) -> bool:
    """
    Checks if the given IP has exceeded failed login attempts within the sliding window.
    """
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - window_seconds
    with _LOGIN_LOCK:
        attempts = _LOGIN_ATTEMPTS.get(ip, [])
        valid_attempts = [t for t in attempts if t > cutoff]
        _LOGIN_ATTEMPTS[ip] = valid_attempts
        return len(valid_attempts) >= max_attempts


def record_login_failure(ip: str) -> None:
    now = datetime.now(timezone.utc).timestamp()
    with _LOGIN_LOCK:
        if ip not in _LOGIN_ATTEMPTS:
            _LOGIN_ATTEMPTS[ip] = []
        _LOGIN_ATTEMPTS[ip].append(now)


def record_login_success(ip: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.pop(ip, None)


# ==============================================================================
# 4. Operator Bootstrap Lifecycle
# ==============================================================================

def ensure_bootstrap_operator(db: Session, settings: Settings) -> OperatorUser:
    """
    Idempotent bootstrap: Ensures at least one active OperatorUser exists.
    If no operator exists:
      - Uses BOOTSTRAP_OPERATOR_USERNAME / BOOTSTRAP_OPERATOR_PASSWORD if configured.
      - In development, defaults to username 'admin' and password 'IntentLeadAdmin2026!'.
      - In production without explicit password, generates a cryptographically secure random password
        and outputs instructions to the system log.
    """
    existing = db.query(OperatorUser).filter_by(is_active=True).first()
    if existing:
        return existing

    username = (settings.BOOTSTRAP_OPERATOR_USERNAME or "admin").strip()
    configured_pwd = (settings.BOOTSTRAP_OPERATOR_PASSWORD or "").strip()

    if configured_pwd:
        password = configured_pwd
        logger.info(f"Bootstrapping operator account '{username}' using environment password.")
    elif settings.APP_ENV == "development":
        password = "IntentLeadAdmin2026!"
        logger.info(f"Development mode: Bootstrapping default operator '{username}' with default password.")
    else:
        # Production random generation
        password = secrets.token_urlsafe(18)
        logger.warning(
            f"SECURITY: Generated initial operator credentials for '{username}': Password: {password} "
            f"Change this password immediately in production settings!"
        )

    pwd_hash = hash_password(password)
    user = OperatorUser(
        username=username,
        password_hash=pwd_hash,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ==============================================================================
# 5. CSRF Protection (HMAC-SHA256 Session-Bound Tokens)
# ==============================================================================

def generate_csrf_token(raw_session_token: str, secret_key: str) -> str:
    """
    Generates a CSRF token bound to the operator's active session token using HMAC-SHA256.
    """
    return hmac.new(
        secret_key.encode("utf-8"),
        raw_session_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def validate_csrf_token(raw_session_token: str, secret_key: str, provided_csrf: str | None) -> bool:
    """
    Validates a submitted CSRF token against the active session token in constant time.
    """
    if not provided_csrf or not raw_session_token:
        return False
    expected = generate_csrf_token(raw_session_token, secret_key)
    return hmac.compare_digest(provided_csrf.strip(), expected)
