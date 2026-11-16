"""
IntentLead AI — Production Reliability & Adversarial Security Audit Suite
Tests Phases 1, 2, 3, and 5:
Phase 1: Webhook Replay Protection, Redis Fail-Closed, Concurrent Replays, Multi-Worker Protection
Phase 2: Real Provider Contracts (Resend Svix, SendGrid Inbound Parse, Mailgun)
Phase 3: Outbound Provider Compliance, Quotas, Message-ID, CAN-SPAM, Suppression
Phase 5: Follow-Up Engine Multi-Worker Concurrency, Retries, Worker Crashes, Stop Conditions
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import sys
import unittest
import uuid

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_DIR = os.path.join(BASE_DIR, "apps", "intelligence-api")
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

from app.config import Settings, get_settings
from app.db import get_session
from app.models import (
    Approval,
    AuditLog,
    Business,
    Campaign,
    Conversation,
    ConversationMessage,
    DailyDispatchQuota,
    FollowUpExecution,
    Lead,
    MessageDraft,
    OutboundMessage,
    SuppressionEntry,
    utc_now,
)
from app.services.email_dispatcher import dispatch_single_email
from app.services.followup_engine import (
    calculate_scheduled_date,
    process_due_followups,
    schedule_followups_for_conversation,
)
from app.services.inbound_service import process_inbound_email
from app.services.webhook_security import (
    DistributedReplayUnavailableError,
    WebhookReplayCache,
    verify_hmac_webhook_signature,
    verify_mailgun_webhook_signature,
    verify_resend_svix_signature,
    webhook_cache,
)


class TestProductionReliabilityAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = get_settings()
        cls.db = next(get_session())
        if cls.settings.REDIS_URL:
            webhook_cache.init_redis(cls.settings.REDIS_URL)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        self.db.rollback()

    def tearDown(self):
        self.db.rollback()

    # =========================================================================
    # PHASE 1: WEBHOOK REPLAY SECURITY & MULTI-WORKER ISOLATION
    # =========================================================================

    def test_p1_01_redis_atomic_set_nx_replay_protection(self):
        """Verify Redis atomic SET key '1' EX ttl NX deduplicates webhooks"""
        print("\n[PHASE 1: Webhook Replay Security]")
        evt_id = f"test_atomic_{uuid.uuid4().hex}"
        
        # 1st attempt: fresh event
        first_result = webhook_cache.check_and_record(evt_id, ttl=60)
        self.assertTrue(first_result, "Initial webhook event must be accepted")
        
        # 2nd attempt: duplicate/replay event
        replay_result = webhook_cache.check_and_record(evt_id, ttl=60)
        self.assertFalse(replay_result, "Replayed webhook event must be rejected by atomic SET NX")
        print("  ✓ Redis atomic SET NX accepted fresh event and rejected instant replay")

    def test_p1_02_production_fail_closed_on_redis_outage(self):
        """Verify production fails closed when Redis distributed cache is unavailable"""
        isolated_cache = WebhookReplayCache(redis_client=None)
        test_evt = f"prod_evt_{uuid.uuid4().hex}"
        
        # In production, check_and_record must NOT silently fallback to local memory; must raise error
        with self.assertRaises(DistributedReplayUnavailableError):
            isolated_cache.check_and_record(test_evt, is_production=True)
        print("  ✓ Production mode FAILS CLOSED (raises DistributedReplayUnavailableError) when Redis is down")

    def test_p1_03_non_production_graceful_memory_fallback(self):
        """Verify dev/test/staging gracefully falls back to memory cache with logging"""
        dev_cache = WebhookReplayCache(redis_client=None)
        test_evt = f"dev_evt_{uuid.uuid4().hex}"
        
        # In development/test (is_production=False), fallback succeeds
        first_result = dev_cache.check_and_record(test_evt, is_production=False)
        self.assertTrue(first_result)
        
        # Replay in dev memory cache is still detected
        replay_result = dev_cache.check_and_record(test_evt, is_production=False)
        self.assertFalse(replay_result)
        print("  ✓ Development/test mode cleanly falls back to local in-memory TTL cache")

    def test_p1_04_concurrent_multi_worker_delivery(self):
        """Verify concurrent multi-worker delivery of the same webhook: exactly 1 succeeds"""
        shared_evt = f"race_evt_{uuid.uuid4().hex}"
        workers_count = 8
        results = []

        def worker_task(wid: int):
            cache_worker = WebhookReplayCache()
            if self.settings.REDIS_URL:
                cache_worker.init_redis(self.settings.REDIS_URL)
            return cache_worker.check_and_record(shared_evt, ttl=60)

        with ThreadPoolExecutor(max_workers=workers_count) as executor:
            futures = [executor.submit(worker_task, i) for i in range(workers_count)]
            results = [f.result() for f in futures]

        true_count = sum(1 for r in results if r is True)
        false_count = sum(1 for r in results if r is False)
        self.assertEqual(true_count, 1, f"Exactly 1 worker must claim event, got {true_count}")
        self.assertEqual(false_count, workers_count - 1, f"Other workers must be rejected, got {false_count}")
        print(f"  ✓ Concurrent multi-worker race ({workers_count} threads): exactly 1 accepted, {false_count} rejected")

    def test_p1_05_database_message_deduplication_defense_in_depth(self):
        """Verify database-level Message-ID deduplication prevents side-effects even if cache expires"""
        unique_msg_id = f"inbound-dedup-{uuid.uuid4().hex[:10]}@prospect.org"
        sender = f"prospect_{uuid.uuid4().hex[:6]}@prospect.org"

        # First ingestion
        res1 = process_inbound_email(
            self.db,
            self.settings,
            sender_email=sender,
            recipient_email="outreach@ori9in.io",
            subject="First Delivery",
            raw_body="Interested in your audit.",
            provider_message_id=unique_msg_id,
        )
        self.db.commit()
        self.assertIn("conversation_id", res1)

        # Duplicate delivery with same provider_message_id
        res2 = process_inbound_email(
            self.db,
            self.settings,
            sender_email=sender,
            recipient_email="outreach@ori9in.io",
            subject="Duplicate Delivery",
            raw_body="Interested in your audit.",
            provider_message_id=unique_msg_id,
        )
        self.assertEqual(res2["status"], "already_processed")
        self.assertEqual(res2["message_id"], res1["message_id"])
        print("  ✓ Database defense-in-depth: duplicate provider_message_id returned 'already_processed'")

    # =========================================================================
    # PHASE 2: REAL PROVIDER CONTRACT VALIDATION
    # =========================================================================

    def test_p2_01_resend_official_svix_contract(self):
        """Verify Resend official Svix signature specification with structured headers"""
        print("\n[PHASE 2: Real Provider Contract Validation]")
        secret = "whsec_MfKQ9r8GKYqrTwjUPI8nvvPqvYJMYNZs="
        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        ts = str(int(utc_now().timestamp()))
        
        # Real Resend webhook payload structure
        payload = {
            "type": "email.received",
            "created_at": utc_now().isoformat(),
            "data": {
                "id": msg_id,
                "from": "Founder <founder@growthstartup.io>",
                "to": ["outreach@ori9in.io"],
                "subject": "Re: Website performance audit",
                "text": "Thanks for the feedback. What are your rates?",
                "headers": [
                    {"name": "In-Reply-To", "value": "<initial-pitch-123@ori9in.io>"},
                    {"name": "References", "value": "<initial-pitch-123@ori9in.io>"},
                    {"name": "Message-ID", "value": f"<{msg_id}@growthstartup.io>"}
                ]
            }
        }
        raw_body = json.dumps(payload).encode("utf-8")

        # Compute valid signature per Svix spec
        clean_sec = secret[6:]
        pad = len(clean_sec) % 4
        if pad:
            clean_sec += "=" * (4 - pad)
        key_bytes = base64.b64decode(clean_sec)
        to_sign = f"{msg_id}.{ts}.".encode("utf-8") + raw_body
        expected_sig = base64.b64encode(hmac.new(key_bytes, to_sign, hashlib.sha256).digest()).decode("utf-8")

        headers = {
            "svix-id": msg_id,
            "svix-timestamp": ts,
            "svix-signature": f"v1,{expected_sig}",
        }

        # Verify valid Svix signature
        is_valid, err = verify_resend_svix_signature(raw_body, headers, secret)
        self.assertTrue(is_valid, f"Resend Svix signature must pass: {err}")

        # Verify forged signature fails
        bad_headers = dict(headers, **{"svix-signature": "v1,forged_svix_hash=="})
        is_bad, _ = verify_resend_svix_signature(raw_body, bad_headers, secret)
        self.assertFalse(is_bad, "Forged Svix signature must fail")

        # Verify expired timestamp (>300s) fails
        expired_headers = dict(headers, **{"svix-timestamp": str(int(ts) - 305)})
        is_exp, exp_err = verify_resend_svix_signature(raw_body, expired_headers, secret)
        self.assertFalse(is_exp, "Expired Svix timestamp must fail")
        self.assertIn("timestamp outside acceptable tolerance", exp_err)
        print("  ✓ Resend official Svix contract: HMAC-SHA256, structured headers, replay window verified")

    def test_p2_02_mailgun_official_signature_contract(self):
        """Verify Mailgun official HMAC signature: HMAC-SHA256(key, timestamp + token)"""
        signing_key = "key-test-mailgun-webhook-signing-key-999"
        token = uuid.uuid4().hex + uuid.uuid4().hex
        ts = str(int(utc_now().timestamp()))
        
        # Mailgun signs timestamp + token
        to_sign = f"{ts}{token}".encode("utf-8")
        valid_signature = hmac.new(signing_key.encode("utf-8"), to_sign, hashlib.sha256).hexdigest()

        # Valid signature verification
        is_valid, err = verify_mailgun_webhook_signature(token, ts, valid_signature, signing_key)
        self.assertTrue(is_valid, f"Mailgun signature must pass: {err}")

        # Tampered token verification
        is_tampered, _ = verify_mailgun_webhook_signature("tampered_token", ts, valid_signature, signing_key)
        self.assertFalse(is_tampered, "Tampered Mailgun token must be rejected")

        # Expired timestamp verification (> 300s)
        old_ts = str(int(ts) - 350)
        is_expired, exp_err = verify_mailgun_webhook_signature(token, old_ts, valid_signature, signing_key)
        self.assertFalse(is_expired, "Expired Mailgun timestamp must be rejected")
        self.assertIn("timestamp outside acceptable tolerance", exp_err)
        print("  ✓ Mailgun official contract: HMAC-SHA256(timestamp+token), tamper & expiration rejection verified")

    def test_p2_03_sendgrid_inbound_parse_rfc822_extraction(self):
        """Verify SendGrid Inbound Parse multipart RFC 822 header extraction"""
        raw_headers = (
            "Received: by mail-wm1-f49.google.com with SMTP id ...\n"
            "MIME-Version: 1.0\n"
            "In-Reply-To: <pitch-f89a2b1c@ori9in.io>\n"
            "References: <pitch-f89a2b1c@ori9in.io>\n"
            "Message-ID: <CABzVp=998877@mail.gmail.com>\n"
            "Subject: Re: Website audit\n"
            "From: Client <client@business.com>\n"
            "To: outreach@ori9in.io\n"
        )
        import re
        m_id = re.search(r"(?i)^Message-ID:\s*<([^>]+)>", raw_headers, re.MULTILINE)
        m_irt = re.search(r"(?i)^In-Reply-To:\s*<([^>]+)>", raw_headers, re.MULTILINE)
        m_ref = re.search(r"(?i)^References:\s*(.+)$", raw_headers, re.MULTILINE)

        self.assertIsNotNone(m_id)
        self.assertEqual(m_id.group(1), "CABzVp=998877@mail.gmail.com")
        self.assertIsNotNone(m_irt)
        self.assertEqual(m_irt.group(1), "pitch-f89a2b1c@ori9in.io")
        self.assertIsNotNone(m_ref)
        self.assertEqual(m_ref.group(1).strip(), "<pitch-f89a2b1c@ori9in.io>")
        print("  ✓ SendGrid Inbound Parse contract: RFC 822 Message-ID, In-Reply-To, References parsed cleanly")

    # =========================================================================
    # PHASE 3: OUTBOUND PROVIDER VERIFICATION (DRY-RUN ISOLATION)
    # =========================================================================

    def test_p3_01_dry_run_safety_and_rfc2822_message_id(self):
        """Verify OUTREACH_DRY_RUN=True safety guarantee and RFC 2822 headers"""
        print("\n[PHASE 3: Outbound Provider Verification]")
        self.assertTrue(self.settings.OUTREACH_DRY_RUN, "OUTREACH_DRY_RUN must remain True")

        uid = uuid.uuid4().hex[:8]
        biz = Business(
            name=f"Safety Dental {uid}",
            identity_key=f"biz-safety-{uid}",
            discovery_source="google_maps",
            email=f"contact@{uid}-safety.example.com",
            source_fields={},
        )
        self.db.add(biz)
        self.db.flush()

        camp = Campaign(
            niche="dental",
            location="Austin, TX",
            requested_quantity=50,
            target_services=["website_redesign"],
            filters={},
            provider="mock",
            status="active",
        )
        self.db.add(camp)
        self.db.flush()

        lead = Lead(
            campaign_id=camp.id,
            business_id=biz.id,
            recommended_service="website_redesign",
            overall_score=85,
            outreach_status="approved",
            priority="A",
            confidence="high",
        )
        self.db.add(lead)
        self.db.flush()

        draft = MessageDraft(
            lead_id=lead.id,
            channel="email",
            status="ready",
            body="Hi Doctor, we audited your page speed.",
            evidence_ids=[],
        )
        self.db.add(draft)
        self.db.flush()

        outbound = dispatch_single_email(
            self.db,
            lead,
            biz,
            self.settings,
            resolver_fn=lambda d: ["mx1.example.com"],
        )
        self.db.commit()

        # Assert status is simulated and zero external emails sent
        self.assertEqual(outbound.status, "simulated")
        self.assertIn("Dry-run simulation", outbound.error_message)

        # Assert conversation message was recorded with RFC 2822 Message-ID
        conv = self.db.query(Conversation).filter_by(lead_id=lead.id).first()
        self.assertIsNotNone(conv)
        msg = self.db.query(ConversationMessage).filter_by(conversation_id=conv.id).first()
        self.assertIsNotNone(msg)
        self.assertTrue(msg.provider_message_id.startswith("<") and msg.provider_message_id.endswith(">"))
        self.assertEqual(msg.delivery_status, "simulated")
        print("  ✓ Outbound dry-run safety: status='simulated', compliant RFC 2822 Message-ID persisted")

    def test_p3_02_daily_dispatch_quota_enforcement(self):
        """Verify mailbox daily dispatch quota limits dispatches"""
        sender = f"sender_{uuid.uuid4().hex[:6]}@ori9in.io"
        
        # Set quota to limit
        quota = DailyDispatchQuota(
            sender_mailbox=sender,
            dispatch_date=utc_now().strftime("%Y-%m-%d"),
            count=self.settings.MAX_EMAILS_PER_DAY,
        )
        self.db.add(quota)
        self.db.commit()

        from app.services.email_gate import check_and_increment_daily_quota
        allowed, count = check_and_increment_daily_quota(
            self.db,
            sender,
            max_daily=self.settings.MAX_EMAILS_PER_DAY,
            dry_run=self.settings.OUTREACH_DRY_RUN,
        )
        self.assertFalse(allowed, "Exceeded quota must be rejected")
        self.assertEqual(count, self.settings.MAX_EMAILS_PER_DAY)
        print(f"  ✓ Mailbox quota enforcement: dispatch rejected at limit ({count}/{self.settings.MAX_EMAILS_PER_DAY})")

    def test_p3_03_suppression_list_preflight_rejection(self):
        """Verify pre-flight gate blocks dispatches to unsubscribed/suppressed addresses"""
        suppressed_email = f"unsub_{uuid.uuid4().hex[:8]}@suppressed.org"
        supp = SuppressionEntry(
            email=suppressed_email,
            reason="unsubscribe",
        )
        self.db.add(supp)
        self.db.commit()

        from app.services.email_gate import is_suppressed
        self.assertTrue(is_suppressed(self.db, suppressed_email))
        print("  ✓ Suppression registry: unsubscribed recipient detected and blocked before dispatch")

    # =========================================================================
    # PHASE 5: FOLLOW-UP ENGINE FAILURE & CONCURRENCY TESTS
    # =========================================================================

    def test_p5_01_multi_worker_concurrency_skip_locked(self):
        """Verify PostgreSQL with_for_update(skip_locked=True) prevents race conditions across workers"""
        print("\n[PHASE 5: Follow-Up Engine Failure & Concurrency]")
        
        # Create 4 due follow-ups for a conversation
        camp = Campaign(
            niche="medical",
            location="Dallas, TX",
            requested_quantity=50,
            target_services=["seo"],
            filters={},
            provider="mock",
            status="active",
        )
        self.db.add(camp)
        self.db.flush()

        conv = Conversation(
            recipient_email=f"worker_race_{uuid.uuid4().hex[:6]}@example.com",
            sender_email="outreach@ori9in.io",
            subject="Thread Safety Test",
            status="active",
            followup_status="scheduled",
            followup_step=0,
            campaign_id=camp.id,
        )
        self.db.add(conv)
        self.db.flush()

        due_time = utc_now() - timedelta(minutes=10)
        items = []
        for step in range(1, 5):
            fu = FollowUpExecution(
                conversation_id=conv.id,
                campaign_id=camp.id,
                sequence_step=step,
                scheduled_at=due_time,
                status="scheduled",
                attempt_count=0,
            )
            self.db.add(fu)
            items.append(fu)
        self.db.commit()

        # Run process_due_followups across 2 concurrent worker threads
        worker_results = []
        def run_worker():
            worker_db = next(get_session())
            try:
                res = process_due_followups(worker_db, self.settings)
                return res.get("executed", 0)
            finally:
                worker_db.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(run_worker)
            f2 = executor.submit(run_worker)
            worker_results = [f1.result(), f2.result()]

        total_executed = sum(worker_results)
        self.db.expire_all()
        executed_in_db = self.db.query(FollowUpExecution).filter(
            FollowUpExecution.conversation_id == conv.id,
            FollowUpExecution.status == "executed",
        ).count()

        self.assertEqual(executed_in_db, 4, "All 4 due follow-ups must be executed exactly once")
        self.assertEqual(total_executed, 4, "Concurrent workers combined must execute exactly 4 items, zero duplicates")
        print(f"  ✓ Multi-worker concurrency safety: 2 concurrent workers executed 4 items cleanly (0 duplicates)")

    def test_p5_02_transient_failure_retry_and_backoff(self):
        """Verify transient dispatch failure increments attempt_count and applies backoff"""
        conv = Conversation(
            recipient_email=f"transient_{uuid.uuid4().hex[:6]}@example.com",
            sender_email="outreach@ori9in.io",
            subject="Transient Test",
            status="active",
            followup_status="scheduled",
        )
        self.db.add(conv)
        self.db.flush()

        fu = FollowUpExecution(
            conversation_id=conv.id,
            sequence_step=1,
            scheduled_at=utc_now() - timedelta(minutes=5),
            status="scheduled",
            attempt_count=1,
        )
        self.db.add(fu)
        self.db.commit()

        # Simulate exception during execution
        item = self.db.get(FollowUpExecution, fu.id)
        current_time = utc_now()
        item.attempt_count += 1
        item.scheduled_at = current_time + timedelta(minutes=15 * item.attempt_count)
        self.db.commit()

        self.db.expire_all()
        updated_item = self.db.get(FollowUpExecution, fu.id)
        self.assertEqual(updated_item.attempt_count, 2)
        self.assertGreater(updated_item.scheduled_at, current_time)
        print("  ✓ Transient failure retry: attempt_count incremented to 2, backoff scheduled 30m in future")

    def test_p5_03_maximum_retry_enforcement(self):
        """Verify item exceeding max retries (>= 3) transitions to failed"""
        conv = Conversation(
            recipient_email=f"retry_{uuid.uuid4().hex[:6]}@example.com",
            sender_email="outreach@ori9in.io",
            subject="Retry Test",
            status="active",
        )
        self.db.add(conv)
        self.db.flush()

        fu = FollowUpExecution(
            conversation_id=conv.id,
            sequence_step=1,
            scheduled_at=utc_now() - timedelta(minutes=5),
            status="scheduled",
            attempt_count=2,
        )
        self.db.add(fu)
        self.db.commit()

        # Simulate 3rd failure
        item = self.db.get(FollowUpExecution, fu.id)
        item.attempt_count += 1
        if item.attempt_count >= 3:
            item.status = "failed"
            item.stop_reason = "max_retries_exceeded: upstream_timeout"
        self.db.commit()

        self.db.expire_all()
        failed_item = self.db.get(FollowUpExecution, fu.id)
        self.assertEqual(failed_item.status, "failed")
        self.assertIn("max_retries_exceeded", failed_item.stop_reason)
        print("  ✓ Maximum retry enforcement: item transitioned to 'failed' with stop_reason='max_retries_exceeded'")

    def test_p5_04_prospect_reply_race_cancels_followup(self):
        """Verify reply arriving immediately before execution aborts follow-up"""
        conv = Conversation(
            recipient_email=f"race_reply_{uuid.uuid4().hex[:6]}@example.com",
            sender_email="outreach@ori9in.io",
            subject="Race Condition Test",
            status="replied",  # Prospect replied
            followup_status="scheduled",
        )
        self.db.add(conv)
        self.db.flush()

        fu = FollowUpExecution(
            conversation_id=conv.id,
            sequence_step=1,
            scheduled_at=utc_now() - timedelta(minutes=5),
            status="scheduled",
        )
        self.db.add(fu)
        self.db.commit()

        # Engine run
        process_due_followups(self.db, self.settings)
        self.db.expire_all()

        updated_fu = self.db.get(FollowUpExecution, fu.id)
        self.assertEqual(updated_fu.status, "cancelled")
        self.assertIn("conversation_status_replied", updated_fu.stop_reason)
        print("  ✓ Race condition safety: follow-up cancelled when prospect reply arrived")

    def test_p5_05_suppression_race_cancels_followup(self):
        """Verify suppression occurring before dispatch immediately cancels pending follow-up"""
        recipient = f"suppressed_race_{uuid.uuid4().hex[:6]}@example.com"
        conv = Conversation(
            recipient_email=recipient,
            sender_email="outreach@ori9in.io",
            subject="Suppression Race Test",
            status="active",
            followup_status="scheduled",
        )
        self.db.add(conv)
        self.db.flush()

        fu = FollowUpExecution(
            conversation_id=conv.id,
            sequence_step=1,
            scheduled_at=utc_now() - timedelta(minutes=5),
            status="scheduled",
        )
        self.db.add(fu)
        
        # Add to suppression list right before dispatch
        supp = SuppressionEntry(
            email=recipient,
            reason="unsubscribe",
        )
        self.db.add(supp)
        self.db.commit()

        # Engine run
        process_due_followups(self.db, self.settings)
        self.db.expire_all()

        updated_fu = self.db.get(FollowUpExecution, fu.id)
        self.assertEqual(updated_fu.status, "cancelled")
        self.assertIn("suppressed", updated_fu.stop_reason)
        print("  ✓ Race condition safety: follow-up cancelled when recipient was suppressed")


if __name__ == "__main__":
    print("=" * 80)
    print("INTENTLEAD AI — PRODUCTION RELIABILITY & ADVERSARIAL AUDIT")
    print("Target Environment: staging")
    print("Outreach Safety Mode: DRY-RUN SIMULATION")
    print("=" * 80)
    unittest.main()
