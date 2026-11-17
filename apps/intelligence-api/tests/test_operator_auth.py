from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import OperatorSession, OperatorUser
from app.services.auth import (
    _LOGIN_ATTEMPTS,
    cleanup_expired_sessions,
    create_operator_session,
    destroy_operator_session,
    ensure_bootstrap_operator,
    generate_csrf_token,
    hash_password,
    is_ip_rate_limited,
    record_login_failure,
    record_login_success,
    validate_csrf_token,
    validate_session_token,
    verify_password,
)


@pytest.fixture
def auth_settings():
    return Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        BOOTSTRAP_OPERATOR_USERNAME="test_admin",
        BOOTSTRAP_OPERATOR_PASSWORD="SuperSecretPassword2026!",
        SESSION_SECRET_KEY="test-session-secret-key-32-chars",
        SESSION_COOKIE_NAME="intentlead_session",
        SESSION_MAX_AGE_SECONDS=3600,
        LOGIN_RATE_LIMIT_MAX_ATTEMPTS=5,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS=900,
    )


@pytest.fixture
def clean_client(db_session, auth_settings):
    """Raw test client with NO pre-existing cookies or sessions."""
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: auth_settings
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ==============================================================================
# 1. Cryptographic Password Hashing & Verification Tests
# ==============================================================================

def test_password_hashing_and_verification():
    pwd = "MySecretSecurePassword123!"
    hashed = hash_password(pwd)

    assert hashed.startswith("pbkdf2_sha256$600000$")
    assert verify_password(pwd, hashed) is True
    assert verify_password("WrongPassword", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(pwd, "") is False
    assert verify_password(pwd, "invalid$format") is False


# ==============================================================================
# 2. Operator Bootstrap Idempotency Tests
# ==============================================================================

def test_operator_bootstrap_idempotency(db_session, auth_settings):
    # First bootstrap creates user
    u1 = ensure_bootstrap_operator(db_session, auth_settings)
    assert u1 is not None
    assert u1.username == "test_admin"
    assert verify_password("SuperSecretPassword2026!", u1.password_hash) is True

    # Second bootstrap returns existing user without duplication
    u2 = ensure_bootstrap_operator(db_session, auth_settings)
    assert u2.id == u1.id
    assert db_session.query(OperatorUser).count() == 1


# ==============================================================================
# 3. Unauthenticated Dashboard Access -> Redirect to /login
# ==============================================================================

def test_unauthenticated_dashboard_redirects_to_login(clean_client):
    # Browser GET request with Accept: text/html
    res = clean_client.get("/", headers={"Accept": "text/html"})
    assert res.status_code == 303
    assert res.headers["location"].startswith("/login?next=")

    res_leads = clean_client.get("/leads", headers={"Accept": "text/html"})
    assert res_leads.status_code == 303
    assert res_leads.headers["location"].startswith("/login?next=")


def test_unauthenticated_api_request_fails_with_401(clean_client):
    # Non-HTML / AJAX request receives 401
    res = clean_client.get("/", headers={"Accept": "application/json"})
    assert res.status_code == 401
    assert "Operator authentication required" in res.json()["detail"]


# ==============================================================================
# 4. Login Lifecycle: Form Render, Authentication, Cookies & Logout
# ==============================================================================

def test_login_page_renders_form(clean_client):
    res = clean_client.get("/login")
    assert res.status_code == 200
    assert "Operator Authentication" in res.text
    assert 'name="username"' in res.text
    assert 'name="password"' in res.text


def test_login_invalid_credentials_rejected(clean_client, db_session, auth_settings):
    ensure_bootstrap_operator(db_session, auth_settings)

    # Wrong password
    res = clean_client.post(
        "/login",
        data={"username": "test_admin", "password": "WrongPassword!"},
    )
    assert res.status_code == 401
    assert "Invalid username or password" in res.text
    assert auth_settings.SESSION_COOKIE_NAME not in clean_client.cookies


def test_login_success_sets_session_cookies_and_redirects(clean_client, db_session, auth_settings):
    ensure_bootstrap_operator(db_session, auth_settings)

    res = clean_client.post(
        "/login",
        data={"username": "test_admin", "password": "SuperSecretPassword2026!", "next": "/leads"},
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/leads"

    # Cookies must be present
    assert auth_settings.SESSION_COOKIE_NAME in res.cookies
    assert "intentlead_csrf" in res.cookies

    # Following with the session cookie grants access to protected routes
    cookie_val = res.cookies[auth_settings.SESSION_COOKIE_NAME]
    clean_client.cookies.set(auth_settings.SESSION_COOKIE_NAME, cookie_val)

    dash_res = clean_client.get("/leads")
    assert dash_res.status_code == 200
    assert "Lead Intelligence" in dash_res.text


def test_logout_invalidates_session_and_clears_cookies(clean_client, db_session, auth_settings):
    from app.services.auth import generate_csrf_token
    op = ensure_bootstrap_operator(db_session, auth_settings)
    _, token = create_operator_session(db_session, op)
    csrf_token = generate_csrf_token(token, auth_settings.SESSION_SECRET_KEY)
    clean_client.cookies.set(auth_settings.SESSION_COOKIE_NAME, token)
    clean_client.cookies.set("intentlead_csrf", csrf_token)

    # Verify initially authorized
    res_before = clean_client.get("/")
    assert res_before.status_code == 200

    # Logout without CSRF token is rejected with 403 Forbidden (CSRF defense)
    res_no_csrf = clean_client.post("/logout")
    assert res_no_csrf.status_code == 403

    # Logout with valid CSRF token succeeds and redirects to /login
    res_logout = clean_client.post("/logout", headers={"X-CSRF-Token": csrf_token})
    assert res_logout.status_code == 303
    assert res_logout.headers["location"] == "/login"

    # Session in DB must be gone
    assert validate_session_token(db_session, token) is None

    # Subsequent access without cookies redirects to login
    clean_client.cookies.clear()
    res_after = clean_client.get("/", headers={"Accept": "text/html"})
    assert res_after.status_code == 303
    assert "/login" in res_after.headers["location"]


# ==============================================================================
# 5. Brute-Force Rate Limiting (5 attempts / 15 minutes)
# ==============================================================================

def test_login_rate_limiting(clean_client, db_session, auth_settings):
    ensure_bootstrap_operator(db_session, auth_settings)
    _LOGIN_ATTEMPTS.clear()

    # Perform 5 failed attempts
    for _ in range(5):
        res = clean_client.post(
            "/login",
            data={"username": "test_admin", "password": "bad_password"},
        )
        assert res.status_code == 401

    # 6th attempt must be blocked with HTTP 429 Too Many Requests
    blocked_res = clean_client.post(
        "/login",
        data={"username": "test_admin", "password": "bad_password"},
    )
    assert blocked_res.status_code == 429
    assert "Too many failed login attempts" in blocked_res.text


# ==============================================================================
# 6. Session Expiration & Cleanup Tests
# ==============================================================================

def test_expired_session_rejected(db_session, auth_settings):
    op = ensure_bootstrap_operator(db_session, auth_settings)
    session_rec, token = create_operator_session(db_session, op, max_age_seconds=1)

    # Fast-forward expiration
    session_rec.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    db_session.commit()

    assert validate_session_token(db_session, token) is None


def test_cleanup_expired_sessions(db_session, auth_settings):
    op = ensure_bootstrap_operator(db_session, auth_settings)
    s1, t1 = create_operator_session(db_session, op, max_age_seconds=3600)
    s2, t2 = create_operator_session(db_session, op, max_age_seconds=3600)

    # Expire s1
    s1.expires_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    db_session.commit()

    cleaned = cleanup_expired_sessions(db_session)
    assert cleaned >= 1
    assert validate_session_token(db_session, t1) is None
    assert validate_session_token(db_session, t2) is not None


# ==============================================================================
# 7. CSRF Token Generation & Validation Tests
# ==============================================================================

def test_csrf_token_lifecycle():
    secret = "test-secret-key-32-chars-long"
    session_token = "random-operator-session-token-xyz"

    csrf = generate_csrf_token(session_token, secret)
    assert len(csrf) == 64  # SHA256 hex
    assert validate_csrf_token(session_token, secret, csrf) is True
    assert validate_csrf_token(session_token, secret, "wrong-token") is False
    assert validate_csrf_token("different-session", secret, csrf) is False
    assert validate_csrf_token(session_token, secret, None) is False
