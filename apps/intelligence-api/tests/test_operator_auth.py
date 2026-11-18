from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import OperatorProfile, OperatorSession, OperatorUser
from app.services.telegram_bot import handle_telegram_update
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
    assert 'name="csrf_token"' in res.text
    assert "intentlead_login_csrf" in res.cookies


def test_login_invalid_credentials_rejected(clean_client, db_session, auth_settings):
    ensure_bootstrap_operator(db_session, auth_settings)

    page_res = clean_client.get("/login")
    csrf_token = page_res.cookies["intentlead_login_csrf"]

    # Wrong password with valid CSRF token passes CSRF check and fails credential verification
    res = clean_client.post(
        "/login",
        data={"username": "test_admin", "password": "WrongPassword!", "csrf_token": csrf_token},
    )
    assert res.status_code == 401
    assert "Invalid username or password" in res.text
    assert auth_settings.SESSION_COOKIE_NAME not in clean_client.cookies


def test_login_success_sets_session_cookies_and_redirects(clean_client, db_session, auth_settings):
    ensure_bootstrap_operator(db_session, auth_settings)

    page_res = clean_client.get("/login")
    csrf_token = page_res.cookies["intentlead_login_csrf"]

    res = clean_client.post(
        "/login",
        data={"username": "test_admin", "password": "SuperSecretPassword2026!", "next": "/leads", "csrf_token": csrf_token},
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/leads"

    # Cookies must be present
    assert auth_settings.SESSION_COOKIE_NAME in res.cookies
    assert "intentlead_csrf" in res.cookies

    # Pre-session login CSRF cookie must be deleted
    assert "intentlead_login_csrf" not in res.cookies or res.cookies["intentlead_login_csrf"] == '""'

    # Following with the session cookie grants access to protected routes
    cookie_val = res.cookies[auth_settings.SESSION_COOKIE_NAME]
    clean_client.cookies.set(auth_settings.SESSION_COOKIE_NAME, cookie_val)

    dash_res = clean_client.get("/leads")
    assert dash_res.status_code == 200
    assert "Lead Intelligence" in dash_res.text


# ==============================================================================
# 4b. Mandatory Login CSRF Protection Tests (5 Scenarios)
# ==============================================================================

def test_login_csrf_missing_cookie_rejected_403(clean_client):
    """Scenario 1: Missing login CSRF cookie -> 403 Forbidden."""
    clean_client.cookies.clear()
    res = clean_client.post(
        "/login",
        data={"username": "test_admin", "password": "AnyPassword123!", "csrf_token": "token-without-cookie"},
    )
    assert res.status_code == 403
    assert "Security validation failed" in res.text


def test_login_csrf_missing_submitted_token_rejected_403(clean_client):
    """Scenario 2: Missing submitted CSRF token -> 403 Forbidden."""
    page_res = clean_client.get("/login")
    assert "intentlead_login_csrf" in page_res.cookies

    # Post with cookie present but omitted csrf_token
    res_omitted = clean_client.post(
        "/login",
        data={"username": "test_admin", "password": "AnyPassword123!"},
    )
    assert res_omitted.status_code == 403
    assert "Security validation failed" in res_omitted.text

    # Post with cookie present but empty csrf_token
    res_empty = clean_client.post(
        "/login",
        data={"username": "test_admin", "password": "AnyPassword123!", "csrf_token": "   "},
    )
    assert res_empty.status_code == 403
    assert "Security validation failed" in res_empty.text


def test_login_csrf_incorrect_submitted_token_rejected_403(clean_client):
    """Scenario 3: Incorrect submitted token -> 403 Forbidden."""
    page_res = clean_client.get("/login")
    assert "intentlead_login_csrf" in page_res.cookies

    res = clean_client.post(
        "/login",
        data={
            "username": "test_admin",
            "password": "AnyPassword123!",
            "csrf_token": "attacker-forged-or-mismatched-token",
        },
    )
    assert res.status_code == 403
    assert "Security validation failed" in res.text


def test_login_csrf_valid_matching_token_proceeds_through_auth(clean_client, db_session, auth_settings):
    """Scenario 4: Valid matching cookie and submitted token -> proceeds through authentication."""
    ensure_bootstrap_operator(db_session, auth_settings)
    page_res = clean_client.get("/login")
    valid_csrf = page_res.cookies["intentlead_login_csrf"]

    # 4a. With invalid credentials -> passes CSRF check, fails with 401 Unauthorized
    res_invalid = clean_client.post(
        "/login",
        data={"username": "test_admin", "password": "WrongPassword!", "csrf_token": valid_csrf},
    )
    assert res_invalid.status_code == 401
    assert "Invalid username or password" in res_invalid.text

    # 4b. With valid credentials -> passes CSRF check, authenticates, 303 Redirects
    res_valid = clean_client.post(
        "/login",
        data={"username": "test_admin", "password": "SuperSecretPassword2026!", "csrf_token": valid_csrf},
    )
    assert res_valid.status_code == 303
    assert res_valid.headers["location"] == "/"

    # 4c. Via X-CSRF-Token header also works
    clean_client.cookies.clear()
    page_res2 = clean_client.get("/login")
    csrf2 = page_res2.cookies["intentlead_login_csrf"]
    res_header = clean_client.post(
        "/login",
        data={"username": "test_admin", "password": "SuperSecretPassword2026!"},
        headers={"X-CSRF-Token": csrf2},
    )
    assert res_header.status_code == 303


def test_login_page_creates_presession_csrf_cookie(clean_client):
    """Scenario 5: GET /login creates pre-session CSRF cookie (intentlead_login_csrf)."""
    clean_client.cookies.clear()
    res = clean_client.get("/login")
    assert res.status_code == 200
    assert "intentlead_login_csrf" in res.cookies
    token = res.cookies["intentlead_login_csrf"]
    assert len(token) >= 32
    # Verify embedded in form field
    assert f'value="{token}"' in res.text


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

    page_res = clean_client.get("/login")
    csrf_token = page_res.cookies["intentlead_login_csrf"]

    # Perform 5 failed attempts with valid CSRF token
    for _ in range(5):
        res = clean_client.post(
            "/login",
            data={"username": "test_admin", "password": "bad_password", "csrf_token": csrf_token},
        )
        assert res.status_code == 401

    # 6th attempt must be blocked with HTTP 429 Too Many Requests
    blocked_res = clean_client.post(
        "/login",
        data={"username": "test_admin", "password": "bad_password", "csrf_token": csrf_token},
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


# ==============================================================================
# 8. Full Integration: Telegram Onboarding & Web Login Synchronization
# ==============================================================================

def test_telegram_onboarding_and_web_login_flow(clean_client, db_session, auth_settings):
    """
    End-to-End Test:
    1. A brand new user chats with the Telegram bot for the first time.
    2. Bot guides them through 3-step registration (Username, Agency Name, Password).
    3. User is created in `operator_users` (with PBKDF2 hash) and `operator_profiles`.
    4. User logs into the Web Dashboard at /login with their exact credentials.
    5. User changes their password via Telegram (/setpassword).
    6. Old password is now rejected; new password successfully logs in.
    7. User changes their username via Telegram (/setusername) and logs in.
    """
    _LOGIN_ATTEMPTS.clear()
    new_user_id = 987654321

    # 1. Telegram /start -> Step 1 (Username)
    res1 = handle_telegram_update(
        {"message": {"from": {"id": new_user_id}, "text": "/start"}},
        db_session,
        auth_settings,
    )
    assert res1["status"] == "onboarding_start"
    assert "Step 1/3: What is your Name?" in res1["reply"]

    # 2. User enters Username -> Step 2 (Agency Name)
    res2 = handle_telegram_update(
        {"message": {"from": {"id": new_user_id}, "text": "charlie"}},
        db_session,
        auth_settings,
    )
    assert res2["status"] == "onboarding_step"
    assert "Step 2/3: What is your Agency or Business Name?" in res2["reply"]

    # 3. User enters Agency -> Step 3 (Password)
    res3 = handle_telegram_update(
        {"message": {"from": {"id": new_user_id}, "text": "Charlie Growth Agency"}},
        db_session,
        auth_settings,
    )
    assert res3["status"] == "onboarding_step"
    assert "Step 3/3: Set your Web Dashboard Password" in res3["reply"]

    # 4. User enters Password -> Complete registration
    res4 = handle_telegram_update(
        {"message": {"from": {"id": new_user_id}, "text": "CharlieSecure999!"}},
        db_session,
        auth_settings,
    )
    db_session.commit()
    assert res4["status"] == "success"
    assert "Account Created Successfully!" in res4["reply"]
    assert "http://localhost:8000/login" in res4["reply"]

    # Verify database persistence
    prof = db_session.get(OperatorProfile, str(new_user_id))
    assert prof is not None
    assert prof.sender_name == "charlie"
    assert prof.agency_name == "Charlie Growth Agency"
    assert prof.operator_user_id is not None

    user = db_session.get(OperatorUser, prof.operator_user_id)
    assert user is not None
    assert user.username == "charlie"
    assert verify_password("CharlieSecure999!", user.password_hash)

    # 5. Log in to the Web Dashboard at /login using the newly created credentials
    login_page = clean_client.get("/login")
    csrf_token = login_page.cookies["intentlead_login_csrf"]

    login_post = clean_client.post(
        "/login",
        data={
            "username": "charlie",
            "password": "CharlieSecure999!",
            "next": "/leads",
            "csrf_token": csrf_token,
        },
    )
    assert login_post.status_code == 303
    assert login_post.headers["location"] == "/leads"
    assert auth_settings.SESSION_COOKIE_NAME in login_post.cookies

    # 6. Change password via Telegram /setpassword
    res_pw = handle_telegram_update(
        {"message": {"from": {"id": new_user_id}, "text": "/setpassword CharlieBrandNew888!"}},
        db_session,
        auth_settings,
    )
    db_session.commit()
    assert res_pw["status"] == "success"
    assert "Password Successfully Updated" in res_pw["reply"]

    # 7. Old password is now rejected
    clean_client.cookies.clear()
    login_page2 = clean_client.get("/login")
    csrf_token2 = login_page2.cookies["intentlead_login_csrf"]

    bad_login = clean_client.post(
        "/login",
        data={
            "username": "charlie",
            "password": "CharlieSecure999!",
            "csrf_token": csrf_token2,
        },
    )
    assert bad_login.status_code == 401

    # 8. New password successfully logs in
    good_login = clean_client.post(
        "/login",
        data={
            "username": "charlie",
            "password": "CharlieBrandNew888!",
            "csrf_token": csrf_token2,
        },
    )
    assert good_login.status_code == 303
    assert auth_settings.SESSION_COOKIE_NAME in good_login.cookies

    # 9. Change username via Telegram /setusername
    res_un = handle_telegram_update(
        {"message": {"from": {"id": new_user_id}, "text": "/setusername charlie_vip"}},
        db_session,
        auth_settings,
    )
    db_session.commit()
    assert res_un["status"] == "success"
    assert "charlie_vip" in res_un["reply"]

    # 10. Web login with new username succeeds
    clean_client.cookies.clear()
    login_page3 = clean_client.get("/login")
    csrf_token3 = login_page3.cookies["intentlead_login_csrf"]

    vip_login = clean_client.post(
        "/login",
        data={
            "username": "charlie_vip",
            "password": "CharlieBrandNew888!",
            "csrf_token": csrf_token3,
        },
    )
    assert vip_login.status_code == 303
    assert auth_settings.SESSION_COOKIE_NAME in vip_login.cookies


def test_web_delete_campaign_authenticated(clean_client, db_session, auth_settings):
    import uuid
    from app.models import Campaign
    from app.services.campaigns import create_campaign

    # Bootstrap operator
    user = ensure_bootstrap_operator(db_session, auth_settings)
    session_record, raw_token = create_operator_session(
        db_session, user, max_age_seconds=auth_settings.SESSION_MAX_AGE_SECONDS
    )
    csrf_token = generate_csrf_token(raw_token, auth_settings.SESSION_SECRET_KEY)
    clean_client.cookies.set(auth_settings.SESSION_COOKIE_NAME, raw_token)
    clean_client.cookies.set("intentlead_csrf", csrf_token)

    # Create a campaign
    camp = create_campaign(
        db_session,
        {
            "niche": "Solar Installers",
            "location": "Phoenix, AZ",
            "requested_quantity": 5,
            "target_services": ["website_development"],
        },
        auth_settings,
    )
    db_session.commit()
    camp_id = camp.id

    assert db_session.get(Campaign, camp_id) is not None

    # Call web delete endpoint
    res = clean_client.post(
        f"/api/web/campaigns/{camp_id}/delete",
        headers={"x-csrf-token": csrf_token},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # Verify completely wiped from DB
    assert db_session.get(Campaign, camp_id) is None

