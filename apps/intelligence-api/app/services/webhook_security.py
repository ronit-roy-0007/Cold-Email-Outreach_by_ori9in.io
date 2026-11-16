from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Mapping, Optional


class WebhookReplayCache:
    """
    In-memory TTL cache for deduplicating webhook events and preventing replay attacks.
    """
    def __init__(self, ttl_seconds: int = 600):
        self._events: dict[str, float] = {}
        self.default_ttl = ttl_seconds

    def check_and_record(self, event_id: str, ttl: Optional[int] = None) -> bool:
        """
        Returns True if this is a fresh event (recorded successfully).
        Returns False if the event has already been processed (duplicate/replay).
        """
        if not event_id:
            return True
        now = time.time()
        self.prune(now)

        if event_id in self._events:
            return False

        expire_at = now + (ttl or self.default_ttl)
        self._events[event_id] = expire_at
        return True

    def prune(self, current_time: Optional[float] = None) -> None:
        now = current_time or time.time()
        expired = [eid for eid, exp in self._events.items() if exp < now]
        for eid in expired:
            del self._events[eid]

    def reset(self) -> None:
        self._events.clear()


webhook_cache = WebhookReplayCache()


def verify_resend_svix_signature(
    raw_body: bytes,
    headers: Mapping[str, str],
    secret: str,
    tolerance_seconds: int = 300,
) -> tuple[bool, Optional[str]]:
    """
    Verifies a Resend webhook using the Svix cryptographic signature protocol.
    Headers required:
      - svix-id: Unique message identifier
      - svix-timestamp: Unix timestamp (seconds)
      - svix-signature: Space-separated signatures (e.g. 'v1,base64...')
    """
    if not secret or not secret.strip():
        return False, "Missing configured webhook secret"

    # Normalize header lookup
    hdr_map = {k.lower(): v for k, v in headers.items()}
    msg_id = hdr_map.get("svix-id")
    msg_timestamp = hdr_map.get("svix-timestamp")
    msg_signature = hdr_map.get("svix-signature")

    if not msg_id or not msg_timestamp or not msg_signature:
        return False, "Missing required Svix signature headers (svix-id, svix-timestamp, svix-signature)"

    # Timestamp verification for replay protection
    try:
        ts = int(msg_timestamp)
    except ValueError:
        return False, "Invalid svix-timestamp format"

    now = int(time.time())
    if abs(now - ts) > tolerance_seconds:
        return False, f"Webhook timestamp outside acceptable tolerance ({abs(now - ts)}s > {tolerance_seconds}s)"

    # Prepare secret key
    clean_secret = secret.strip()
    if clean_secret.startswith("whsec_"):
        clean_secret = clean_secret[6:]
        pad = len(clean_secret) % 4
        if pad:
            clean_secret += "=" * (4 - pad)
        try:
            key_bytes = base64.b64decode(clean_secret)
        except Exception:
            key_bytes = clean_secret.encode("utf-8")
    else:
        key_bytes = clean_secret.encode("utf-8")

    # Compute expected signature: HMAC-SHA256(to_sign, key)
    # where to_sign = f"{msg_id}.{msg_timestamp}.{raw_body.decode('utf-8')}"
    to_sign = f"{msg_id}.{msg_timestamp}.".encode("utf-8") + raw_body
    computed_digest = hmac.new(key_bytes, to_sign, hashlib.sha256).digest()
    expected_b64 = base64.b64encode(computed_digest).decode("utf-8")

    # Validate against passed signatures (format: 'v1,sig1 v1,sig2')
    passed_sigs = msg_signature.split()
    for sig_entry in passed_sigs:
        parts = sig_entry.split(",", 1)
        if len(parts) == 2 and parts[0] == "v1":
            if hmac.compare_digest(parts[1], expected_b64):
                return True, None

    return False, "Signature verification failed"


def verify_hmac_webhook_signature(
    raw_body: bytes,
    signature: str,
    secret: str,
    timestamp: Optional[str] = None,
    tolerance_seconds: int = 300,
) -> tuple[bool, Optional[str]]:
    """
    Verifies a standard HMAC-SHA256 webhook signature.
    Supports optional timestamp prefixing for replay protection: f"{timestamp}.{raw_body}".
    """
    if not secret:
        return False, "Missing webhook secret"
    if not signature:
        return False, "Missing webhook signature"

    if timestamp:
        try:
            ts = int(timestamp)
            now = int(time.time())
            if abs(now - ts) > tolerance_seconds:
                return False, "Webhook timestamp expired"
            to_sign = f"{timestamp}.".encode("utf-8") + raw_body
        except ValueError:
            return False, "Invalid timestamp header"
    else:
        to_sign = raw_body

    expected_hex = hmac.new(secret.encode("utf-8"), to_sign, hashlib.sha256).hexdigest()
    expected_b64 = base64.b64encode(hmac.new(secret.encode("utf-8"), to_sign, hashlib.sha256).digest()).decode("utf-8")

    clean_sig = signature.strip()
    if clean_sig.startswith("sha256="):
        clean_sig = clean_sig[7:]

    if hmac.compare_digest(clean_sig, expected_hex) or hmac.compare_digest(clean_sig, expected_b64):
        return True, None

    return False, "HMAC signature mismatch"
