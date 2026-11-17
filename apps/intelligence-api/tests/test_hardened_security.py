from __future__ import annotations

import base64
import hashlib
import hmac
import time
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import MailboxAccount, SuppressionEntry
from app.security import (
    DistributedRateLimiter,
    extract_client_ip,
)
from app.services.crypto import (
    decrypt_credential,
    derive_fernet_key,
    encrypt_credential,
    mask_credential,
    rotate_credential,
)
from app.services.webhook_security import (
    verify_hmac_webhook_signature,
    verify_resend_svix_signature,
    webhook_cache,
)


# ==============================================================================
# 1. Credential Encryption & Migration Tests
# ==============================================================================

def test_credential_encryption_and_decryption():
    raw_password = "abcd efgh ijkl mnop"
    key = "test-secret-encryption-passphrase-32"

    token = encrypt_credential(raw_password, key)
    assert token.startswith("gAAAAA")
    assert token != raw_password

    decrypted = decrypt_credential(token, key)
    assert decrypted == raw_password


def test_invalid_encryption_key_raises():
    raw_password = "secure-mailbox-password-123"
    key_a = "secret-key-alpha-12345678901234"
    key_b = "secret-key-bravo-98765432109876"

    token = encrypt_credential(raw_password, key_a)

    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_credential(token, key_b)


def test_existing_legacy_credential_migration(db_session):
    # Existing unencrypted plaintext password from previous database versions
    legacy_pass = "legacy_unencrypted_pw_1234"

    # 1. decrypt_credential returns legacy plaintext intact without crashing
    assert decrypt_credential(legacy_pass, "any-key") == legacy_pass

    # 2. MailboxAccount ORM get_password transparently handles legacy plaintext
    mb = MailboxAccount(
        email="legacy@gmail.com",
        password=legacy_pass,
        sender_name="Legacy Sender",
        daily_limit=40,
        is_active=True,
    )
    db_session.add(mb)
    db_session.commit()

    assert mb.get_password("any-key") == legacy_pass

    # 3. Setting a new password encrypts it into a Fernet token
    mb.set_password("new_secret_password_5678", "my-key")
    db_session.commit()

    assert mb.password.startswith("gAAAAA")
    assert mb.get_password("my-key") == "new_secret_password_5678"


def test_safe_credential_rotation():
    raw_secret = "rotation-target-secret"
    old_key = "old-encryption-key-v1"
    new_key = "new-encryption-key-v2"

    token_v1 = encrypt_credential(raw_secret, old_key)
    token_v2 = rotate_credential(token_v1, old_key, new_key)

    assert token_v2.startswith("gAAAAA")
    assert token_v2 != token_v1
    assert decrypt_credential(token_v2, new_key) == raw_secret

    with pytest.raises(ValueError):
        decrypt_credential(token_v2, old_key)


def test_password_redaction_and_representation():
    raw_pass = "abcd efgh ijkl mnop"
    masked = mask_credential(raw_pass)
    assert masked == "•••• •••• •••• ••••"

    mb = MailboxAccount(email="audit@example.com", password=raw_pass)
    rep = repr(mb)
    assert "audit@example.com" in rep
    assert raw_pass not in rep
    assert "password" not in rep.lower()


# ==============================================================================
# 2. Webhook Cryptographic Verification & Replay Protection Tests
# ==============================================================================

def test_resend_svix_signature_verification_success():
    raw_key = b"0123456789abcdef0123456789abcdef"
    secret = "whsec_" + base64.b64encode(raw_key).decode("utf-8")
    body = b'{"email": "bounced@target.com", "event": "bounce"}'
    msg_id = "msg_test_12345"
    now_ts = str(int(time.time()))

    # Build valid Svix signature
    to_sign = f"{msg_id}.{now_ts}.".encode("utf-8") + body
    computed_sig = base64.b64encode(hmac.new(raw_key, to_sign, hashlib.sha256).digest()).decode("utf-8")

    headers = {
        "svix-id": msg_id,
        "svix-timestamp": now_ts,
        "svix-signature": f"v1,{computed_sig}",
    }

    is_valid, err = verify_resend_svix_signature(body, headers, secret)
    assert is_valid is True
    assert err is None


def test_resend_svix_signature_verification_failure():
    secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2"
    body = b'{"email": "bounced@target.com", "event": "bounce"}'
    headers = {
        "svix-id": "msg_test_12345",
        "svix-timestamp": str(int(time.time())),
        "svix-signature": "v1,invalid_forged_base64_signature=",
    }

    is_valid, err = verify_resend_svix_signature(body, headers, secret)
    assert is_valid is False
    assert "Signature verification failed" in err


def test_webhook_replay_protection_and_expired_timestamp():
    secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2"
    body = b'{"email": "bounced@target.com", "event": "bounce"}'
    msg_id = "msg_expired_123"

    # Expired timestamp (10 minutes old)
    old_ts = str(int(time.time()) - 600)
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": old_ts,
        "svix-signature": "v1,some_sig",
    }

    is_valid, err = verify_resend_svix_signature(body, headers, secret, tolerance_seconds=300)
    assert is_valid is False
    assert "timestamp outside acceptable tolerance" in err


def test_webhook_event_deduplication(db_session):
    webhook_cache.reset()

    # First attempt: should record and allow
    assert webhook_cache.check_and_record("evt_unique_101") is True

    # Replay of same event: should detect duplicate
    assert webhook_cache.check_and_record("evt_unique_101") is False

    # Distinct event: should allow
    assert webhook_cache.check_and_record("evt_unique_102") is True


def test_webhook_endpoint_with_resend_signature_gate(db_session):
    webhook_cache.reset()
    raw_key = b"0123456789abcdef0123456789abcdef"
    secret = "whsec_" + base64.b64encode(raw_key).decode("utf-8")

    webhook_settings = Settings(
        APP_ENV="production",
        DATABASE_URL="sqlite:///:memory:",
        RESEND_WEBHOOK_SECRET=secret,
        RATE_LIMIT_PER_MINUTE=100,
    )

    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: webhook_settings

    with TestClient(app) as client:
        body_dict = {"email": "resend_bounced@example.com", "event": "bounce", "id": "msg_resend_999"}
        raw_body = b'{"email": "resend_bounced@example.com", "event": "bounce", "id": "msg_resend_999"}'
        msg_id = "msg_resend_999"
        ts = str(int(time.time()))

        # 1. Invalid signature -> 401
        res_bad = client.post(
            "/api/outreach/webhook/event",
            content=raw_body,
            headers={
                "svix-id": msg_id,
                "svix-timestamp": ts,
                "svix-signature": "v1,bad_sig",
                "content-type": "application/json",
            }
        )
        assert res_bad.status_code == 401

        # 2. Valid signature -> 200
        to_sign = f"{msg_id}.{ts}.".encode("utf-8") + raw_body
        valid_sig = base64.b64encode(hmac.new(raw_key, to_sign, hashlib.sha256).digest()).decode("utf-8")

        res_ok = client.post(
            "/api/outreach/webhook/event",
            content=raw_body,
            headers={
                "svix-id": msg_id,
                "svix-timestamp": ts,
                "svix-signature": f"v1,{valid_sig}",
                "content-type": "application/json",
            }
        )
        assert res_ok.status_code == 200
        assert res_ok.json()["status"] == "success"

        # Verify added to suppression list
        entry = db_session.query(SuppressionEntry).filter_by(email="resend_bounced@example.com").first()
        assert entry is not None

        # 3. Duplicate event with valid signature -> returns duplicate status without re-inserting
        res_dup = client.post(
            "/api/outreach/webhook/event",
            content=raw_body,
            headers={
                "svix-id": msg_id,
                "svix-timestamp": ts,
                "svix-signature": f"v1,{valid_sig}",
                "content-type": "application/json",
            }
        )
        assert res_dup.status_code == 200
        assert res_dup.json()["status"] == "duplicate"

    app.dependency_overrides.clear()


# ==============================================================================
# 3. Distributed Rate Limiter & Reverse-Proxy Security Tests
# ==============================================================================

def test_distributed_rate_limiter_redis_mock():
    limiter = DistributedRateLimiter()

    # Mock Redis instance with atomic sorted set pipeline
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe

    # Call 1 & 2: current count < limit (e.g. 1)
    mock_pipe.execute.return_value = [0, 1, 1, True]
    limiter._redis = mock_redis

    ip = "198.51.100.5"
    assert limiter.is_allowed(ip, max_requests=3, window_seconds=60) is True

    # Call 3: count reaches limit (3)
    mock_pipe.execute.return_value = [0, 3, 1, True]
    assert limiter.is_allowed(ip, max_requests=3, window_seconds=60) is False
    # Verifies member removed upon exceeding limit
    mock_redis.zrem.assert_called_once()


def test_distributed_rate_limiter_redis_outage_fallback():
    limiter = DistributedRateLimiter()

    # Simulate Redis connection failure
    mock_redis = MagicMock()
    mock_redis.pipeline.side_effect = Exception("Redis cluster unavailable (Connection refused)")
    limiter._redis = mock_redis

    ip = "192.0.2.1"
    # Should seamlessly fall back to local in-memory limiter without crashing
    assert limiter.is_allowed(ip, max_requests=2, window_seconds=10) is True
    assert limiter.is_allowed(ip, max_requests=2, window_seconds=10) is True
    assert limiter.is_allowed(ip, max_requests=2, window_seconds=10) is False


def test_secure_reverse_proxy_ip_handling():
    class DummyRequest:
        def __init__(self, host, headers=None):
            self.client = MagicMock()
            self.client.host = host
            self.headers = headers or {}

    trusted = "127.0.0.1,10.0.0.1"

    # Case 1: Untrusted direct connection with spoofed X-Forwarded-For -> strictly use client.host
    req_untrusted = DummyRequest("203.0.113.50", {"x-forwarded-for": "1.1.1.1, 8.8.8.8"})
    assert extract_client_ip(req_untrusted, trusted) == "203.0.113.50"

    # Case 2: Connection from trusted proxy (127.0.0.1) -> inspects X-Forwarded-For
    req_trusted = DummyRequest("127.0.0.1", {"x-forwarded-for": "198.51.100.77"})
    assert extract_client_ip(req_trusted, trusted) == "198.51.100.77"

    # Case 3: Chained trusted proxies: Client -> Proxy1 (untrusted) -> Proxy2 (trusted 10.0.0.1) -> Gateway (trusted 127.0.0.1)
    req_chained = DummyRequest("127.0.0.1", {"x-forwarded-for": "198.51.100.99, 10.0.0.1"})
    assert extract_client_ip(req_chained, trusted) == "198.51.100.99"


def test_multi_worker_consistency():
    """
    Verifies that multiple worker processes sharing the same Redis backend
    enforce atomic rate limits consistently across workers.
    """
    shared_redis_store = {}

    def mock_pipeline():
        pipe = MagicMock()
        def execute():
            current_count = len(shared_redis_store.get("rate:test_ip", []))
            shared_redis_store.setdefault("rate:test_ip", []).append(time.time())
            return [0, current_count, 1, True]
        pipe.execute.side_effect = execute
        return pipe

    mock_redis = MagicMock()
    mock_redis.pipeline.side_effect = mock_pipeline

    worker_a = DistributedRateLimiter()
    worker_a._redis = mock_redis

    worker_b = DistributedRateLimiter()
    worker_b._redis = mock_redis

    ip = "198.51.100.9"
    # Worker A processes request 1 (allowed, count=1 <= 2)
    assert worker_a.is_allowed(ip, max_requests=2, window_seconds=60) is True

    # Worker B processes request 2 (allowed, count=2 <= 2)
    assert worker_b.is_allowed(ip, max_requests=2, window_seconds=60) is True

    # Worker A attempts request 3 (rejected, count=3 > 2)
    assert worker_a.is_allowed(ip, max_requests=2, window_seconds=60) is False

    # Worker B attempts request 4 (rejected, count=4 > 2)
    assert worker_b.is_allowed(ip, max_requests=2, window_seconds=60) is False


# ==============================================================================
# 4. Mandatory Human Approval Enforcement Tests
# ==============================================================================

def test_human_approval_enforcement_on_dispatch(db_session):
    from app.models import Business, Campaign, Lead
    from app.services.email_dispatcher import (
        dispatch_approved_campaign_leads,
        dispatch_single_email,
    )

    camp = Campaign(
        niche="Dentists",
        location="Chicago",
        requested_quantity=10,
        target_services=["SEO"],
        filters={},
        provider="live",
        status="created",
    )
    db_session.add(camp)
    db_session.flush()

    biz1 = Business(
        identity_key="biz-chicago-dental-1",
        name="Chicago Dental Care",
        category="Dentist",
        address="100 Michigan Ave",
        locality="Chicago",
        email="contact@chicagodental.example.com",
        discovery_source="google_maps",
        source_fields={},
    )
    biz2 = Business(
        identity_key="biz-chicago-dental-2",
        name="Lakeside Dental",
        category="Dentist",
        address="200 Michigan Ave",
        locality="Chicago",
        email="info@lakesidedental.example.com",
        discovery_source="google_maps",
        source_fields={},
    )
    db_session.add_all([biz1, biz2])
    db_session.flush()

    # 1. Lead in 'draft' status (unapproved)
    draft_lead = Lead(
        campaign_id=camp.id,
        business_id=biz1.id,
        overall_score=85,
        priority="A",
        confidence="high",
        recommended_service="SEO",
        outreach_status="draft",
    )
    # 2. Lead in 'rejected' status
    rejected_lead = Lead(
        campaign_id=camp.id,
        business_id=biz2.id,
        overall_score=75,
        priority="B",
        confidence="medium",
        recommended_service="SEO",
        outreach_status="rejected",
    )
    db_session.add_all([draft_lead, rejected_lead])
    db_session.commit()

    test_settings = Settings(
        OUTREACH_DRY_RUN=True,
        SMTP_USER="outreach_test@example.com",
        SMTP_PASSWORD="test_password_1234",
    )

    # A: Bulk dispatch query MUST ignore draft and rejected leads
    res = dispatch_approved_campaign_leads(db=db_session, campaign_id=camp.id, settings=test_settings)
    assert res["total_candidates"] == 0
    assert res["sent"] == 0
    assert res["simulated"] == 0

    # B: Explicit lead_ids MUST NOT bypass human approval
    res_explicit = dispatch_approved_campaign_leads(
        db=db_session,
        campaign_id=camp.id,
        settings=test_settings,
        lead_ids=[draft_lead.id, rejected_lead.id],
    )
    assert res_explicit["total_candidates"] == 0

    # C: Final dispatch boundary gate (Gate 0) in dispatch_single_email MUST reject unapproved lead
    outbound = dispatch_single_email(
        db=db_session,
        lead=draft_lead,
        biz=biz1,
        settings=test_settings,
        resolver_fn=lambda d: ["192.0.2.1"],
    )
    assert outbound.status == "rejected"
    assert "human approval required" in outbound.error_message.lower()

    # D: Once human approves the lead, dispatch succeeds cleanly
    draft_lead.outreach_status = "approved"
    db_session.commit()

    res_approved = dispatch_approved_campaign_leads(
        db=db_session,
        campaign_id=camp.id,
        settings=test_settings,
        resolver_fn=lambda d: ["192.0.2.1"],
    )
    assert res_approved["total_candidates"] == 1
    assert res_approved["simulated"] == 1


def test_sub_campaign_human_approval_enforcement(db_session):
    from app.models import Business, Campaign, Lead
    from app.services.sub_campaign_service import dispatch_subcampaign_batch

    camp = Campaign(
        niche="Plumbers",
        location="Boston",
        requested_quantity=10,
        target_services=["Chatbots"],
        filters={},
        provider="live",
        status="created",
    )
    db_session.add(camp)
    db_session.flush()

    biz = Business(
        identity_key="biz-boston-plumber-1",
        name="Boston Rapid Plumbing",
        category="Plumber",
        address="200 Commonwealth Ave",
        locality="Boston",
        email="info@bostonplumbing.example.com",
        discovery_source="google_maps",
        source_fields={},
    )
    db_session.add(biz)
    db_session.flush()

    lead = Lead(
        campaign_id=camp.id,
        business_id=biz.id,
        overall_score=90,
        priority="A",
        confidence="high",
        recommended_service="Chatbots",
        outreach_status="draft",
    )
    db_session.add(lead)
    db_session.commit()

    test_settings = Settings(
        OUTREACH_DRY_RUN=True,
        SMTP_USER="outreach_test@example.com",
        SMTP_PASSWORD="test_password_1234",
    )

    # Sub-campaign dispatch MUST reject draft leads
    res = dispatch_subcampaign_batch(
        db=db_session,
        campaign_id=camp.id,
        settings=test_settings,
        max_to_send=10,
        resolver_fn=lambda d: ["192.0.2.1"],
    )
    assert res["total_candidates"] == 0

    # Once approved, sub-campaign dispatches
    lead.outreach_status = "approved"
    db_session.commit()

    res_ok = dispatch_subcampaign_batch(
        db=db_session,
        campaign_id=camp.id,
        settings=test_settings,
        max_to_send=10,
        resolver_fn=lambda d: ["192.0.2.1"],
    )
    assert res_ok["total_candidates"] == 1
    assert res_ok["simulated"] == 1


# ==============================================================================
# 5. Telegram /testmailbox Decryption Tests
# ==============================================================================

def test_telegram_testmailbox_decryption_with_encrypted_and_legacy_passwords(db_session):
    from app.models import MailboxAccount
    from app.services.mailbox_pool import add_mailbox_account
    from app.services.telegram_bot import handle_telegram_update

    key = "test-secret-key-material-32bytes"
    settings = Settings(
        APP_ENV="development",
        TELEGRAM_ALLOWED_USER_ID="12345",
        FIELD_ENCRYPTION_KEY=key,
    )

    # 1. Add encrypted mailbox account
    enc_acc = add_mailbox_account(
        db=db_session,
        email="encrypted_mailbox@example.com",
        password="plain-secret-password-16",
        sender_name="Roy",
        encryption_key=key,
    )
    assert enc_acc.password.startswith("gAAAAA")

    # 2. Add legacy plaintext mailbox account directly into DB
    leg_acc = MailboxAccount(
        email="legacy_mailbox@example.com",
        password="legacy-plaintext-password",
        sender_name="Roy",
        is_active=True,
    )
    db_session.add(leg_acc)
    db_session.commit()

    with patch("app.services.telegram_bot.verify_gmail_credentials") as mock_verify:
        mock_verify.return_value = (True, "Connected")

        # Test Encrypted Mailbox
        res_enc = handle_telegram_update(
            update={"message": {"from": {"id": 12345}, "text": "/testmailbox encrypted_mailbox@example.com"}},
            db=db_session,
            settings=settings,
        )
        assert res_enc["status"] == "success"
        # Assert verify_gmail_credentials received DECRYPTED plaintext, NOT Fernet token!
        mock_verify.assert_called_with(
            email="encrypted_mailbox@example.com",
            password="plain-secret-password-16",
            smtp_host="smtp.gmail.com",
            smtp_port=587,
        )

        # Test Legacy Mailbox
        res_leg = handle_telegram_update(
            update={"message": {"from": {"id": 12345}, "text": "/testmailbox legacy_mailbox@example.com"}},
            db=db_session,
            settings=settings,
        )
        assert res_leg["status"] == "success"
        mock_verify.assert_called_with(
            email="legacy_mailbox@example.com",
            password="legacy-plaintext-password",
            smtp_host="smtp.gmail.com",
            smtp_port=587,
        )


# ==============================================================================
# 6. Production Security & Fail-Closed Webhook Tests
# ==============================================================================

def test_production_security_validation():
    from app.config import SecurityConfigError, Settings, validate_production_security

    # Missing FIELD_ENCRYPTION_KEY in production must raise SecurityConfigError
    prod_bad_key = Settings(
        APP_ENV="production",
        DATABASE_URL="postgresql://user:pass@localhost:5432/db",
        FIELD_ENCRYPTION_KEY="",
        CORS_ORIGINS="https://dashboard.example.com",
        UNSUBSCRIBE_SECRET="test-production-unsubscribe-secret-32b",
    )
    with pytest.raises(SecurityConfigError, match="FIELD_ENCRYPTION_KEY must be configured"):
        validate_production_security(prod_bad_key)

    # Wildcard CORS in production must raise SecurityConfigError
    prod_bad_cors = Settings(
        APP_ENV="production",
        DATABASE_URL="postgresql://user:pass@localhost:5432/db",
        FIELD_ENCRYPTION_KEY="prod-valid-encryption-key-passphrase",
        CORS_ORIGINS="*",
        UNSUBSCRIBE_SECRET="test-production-unsubscribe-secret-32b",
    )
    with pytest.raises(SecurityConfigError, match="CORS_ORIGINS cannot be set to wildcard"):
        validate_production_security(prod_bad_cors)

    # Insecure / default UNSUBSCRIBE_SECRET in production must raise SecurityConfigError
    prod_bad_unsub = Settings(
        APP_ENV="production",
        DATABASE_URL="postgresql://user:pass@localhost:5432/db",
        FIELD_ENCRYPTION_KEY="prod-valid-encryption-key-passphrase",
        CORS_ORIGINS="https://intentlead.agency",
        UNSUBSCRIBE_SECRET="intentlead-compliance-secret-key",
    )
    with pytest.raises(SecurityConfigError, match="UNSUBSCRIBE_SECRET must be set to a secure, unique secret"):
        validate_production_security(prod_bad_unsub)

    # Valid production settings pass cleanly with test-only secret
    prod_valid = Settings(
        APP_ENV="production",
        DATABASE_URL="postgresql://user:pass@localhost:5432/db",
        FIELD_ENCRYPTION_KEY="prod-valid-encryption-key-passphrase",
        CORS_ORIGINS="https://intentlead.agency,https://dashboard.intentlead.agency",
        UNSUBSCRIBE_SECRET="test-production-unsubscribe-secret-32b",
    )
    validate_production_security(prod_valid)


def test_webhook_fail_closed_when_secrets_missing(db_session):
    webhook_settings = Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        RESEND_WEBHOOK_SECRET="",
        OUTREACH_WEBHOOK_SECRET="",
    )
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: webhook_settings

    with TestClient(app) as client:
        res = client.post(
            "/api/outreach/webhook/event",
            json={"email": "attacker@example.com", "event": "complaint"},
        )
        # Must fail-closed with 401 Unauthorized
        assert res.status_code == 401
        assert "signature verification required" in res.json()["detail"].lower()

    app.dependency_overrides.clear()


def test_webhook_hmac_verification_success_and_tampered(db_session):
    secret = "outreach-hmac-secret-xyz"
    webhook_settings = Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///:memory:",
        OUTREACH_WEBHOOK_SECRET=secret,
    )
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: webhook_settings

    with TestClient(app) as client:
        raw_body = b'{"email": "hmac_bounce@example.com", "event": "bounce"}'
        ts = str(int(time.time()))
        to_sign = f"{ts}.".encode("utf-8") + raw_body
        valid_sig = hmac.new(secret.encode("utf-8"), to_sign, hashlib.sha256).hexdigest()

        # 1. Valid HMAC -> 200
        res_ok = client.post(
            "/api/outreach/webhook/event",
            content=raw_body,
            headers={
                "content-type": "application/json",
                "x-signature-sha256": valid_sig,
                "x-webhook-timestamp": ts,
            },
        )
        assert res_ok.status_code == 200
        assert res_ok.json()["status"] == "success"

        # 2. Tampered signature -> 401
        res_tampered = client.post(
            "/api/outreach/webhook/event",
            content=raw_body,
            headers={
                "content-type": "application/json",
                "x-signature-sha256": "tampered_fake_signature",
                "x-webhook-timestamp": ts,
            },
        )
        assert res_tampered.status_code == 401

    app.dependency_overrides.clear()


# ==============================================================================
# 7. Distributed Webhook Replay & Observability Tests
# ==============================================================================

def test_distributed_webhook_replay_protection_redis():
    from app.services.webhook_security import WebhookReplayCache

    mock_redis = MagicMock()
    # First call: key is fresh, set NX returns True
    # Second call: key already exists, set NX returns None/False
    mock_redis.set.side_effect = [True, None]

    cache = WebhookReplayCache(redis_client=mock_redis)

    # Worker 1 processes event
    assert cache.check_and_record("evt_worker_100") is True
    mock_redis.set.assert_called_with("webhook_replay:evt_worker_100", "1", ex=600, nx=True)

    # Worker 2 attempts same event -> atomically rejected
    assert cache.check_and_record("evt_worker_100") is False


def test_redis_rate_limiter_observability_logging(caplog):
    import logging
    limiter = DistributedRateLimiter()

    mock_redis = MagicMock()
    mock_redis.pipeline.side_effect = Exception("Redis cluster partition failure")
    limiter._redis = mock_redis

    with caplog.at_level(logging.WARNING, logger="intentlead.security"):
        allowed = limiter.is_allowed("198.51.100.42", max_requests=5, window_seconds=60)
        assert allowed is True
        assert any(
            "falling back to in-memory" in rec.message and "198.51.100.42" in rec.message
            for rec in caplog.records
        )

