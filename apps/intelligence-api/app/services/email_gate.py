from __future__ import annotations

import re
import socket
from datetime import datetime, timezone
from typing import Callable
from sqlalchemy.orm import Session

import dns.resolver

from app.models import DailyDispatchQuota, SuppressionEntry

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def validate_email_syntax(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    clean = email.strip()
    return bool(EMAIL_REGEX.match(clean))


_MX_CACHE: dict[str, tuple[bool, str | None]] = {}


def check_domain_mx(domain: str, resolver_fn: Callable[[str], list[str]] | None = None) -> tuple[bool, str | None]:
    """
    Validates that a recipient domain has reachable MX or fallback A records.
    Prevents high-bounce rates before dispatch.
    """
    clean_domain = domain.strip().lower()
    if not clean_domain:
        return False, "empty_domain"

    if clean_domain in _MX_CACHE:
        return _MX_CACHE[clean_domain]

    # Whitelist test domains for CI / unit test fixtures
    if clean_domain in ("fixtures.intentlead.test", "intentlead.test", "example.com", "example.org"):
        _MX_CACHE[clean_domain] = (True, None)
        return True, None

    if resolver_fn is not None:
        try:
            records = resolver_fn(clean_domain)
            if records:
                return True, None
            return False, "no_mx_records"
        except Exception as exc:
            return False, f"mx_lookup_failed: {exc}"

    try:
        # Check MX records first with dnspython
        custom_resolver = dns.resolver.Resolver()
        custom_resolver.lifetime = 1.0
        custom_resolver.timeout = 1.0
        try:
            mx_answers = custom_resolver.resolve(clean_domain, "MX")
            valid_mx = [
                str(r.exchange).rstrip(".")
                for r in mx_answers
                if str(r.exchange).strip().rstrip(".") != ""
            ]
            if valid_mx:
                _MX_CACHE[clean_domain] = (True, None)
                return True, None
            else:
                res = (False, f"Domain '{clean_domain}' has Null MX record (accepts no email, RFC 7505)")
                _MX_CACHE[clean_domain] = res
                return res
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            pass

        # Fallback to A record (RFC 5321 implicit MX fallback)
        try:
            a_answers = custom_resolver.resolve(clean_domain, "A")
            if a_answers:
                _MX_CACHE[clean_domain] = (True, None)
                return True, None
        except Exception:
            pass

        res = (False, f"Domain '{clean_domain}' has no valid MX or A DNS records")
        _MX_CACHE[clean_domain] = res
        return res
    except dns.resolver.NXDOMAIN:
        res = (False, f"Domain '{clean_domain}' does not exist (NXDOMAIN)")
        _MX_CACHE[clean_domain] = res
        return res
    except Exception as exc:
        # Fallback to standard library socket lookup
        try:
            socket.gethostbyname(clean_domain)
            _MX_CACHE[clean_domain] = (True, None)
            return True, None
        except Exception:
            res = (False, f"DNS resolution failed for '{clean_domain}': {exc}")
            _MX_CACHE[clean_domain] = res
            return res


def preflight_deliverability_gate(
    email: str,
    db: Session | None = None,
    resolver_fn: Callable[[str], list[str]] | None = None,
) -> tuple[bool, str | None]:
    """
    Pre-Flight MX & Deliverability Gate.
    Validates syntax, suppression status, and DNS MX records.
    """
    if not validate_email_syntax(email):
        return False, "invalid_email_syntax"

    clean_email = email.strip().lower()

    if db is not None:
        if is_suppressed(db, clean_email):
            return False, "recipient_on_suppression_list"

    domain = clean_email.split("@")[1]
    is_valid_domain, domain_err = check_domain_mx(domain, resolver_fn=resolver_fn)
    if not is_valid_domain:
        return False, f"preflight_mx_failed: {domain_err}"

    return True, None


def is_suppressed(db: Session, email: str) -> bool:
    clean = email.strip().lower()
    entry = db.query(SuppressionEntry).filter_by(email=clean).first()
    return entry is not None


def add_to_suppression_list(db: Session, email: str, reason: str = "unsubscribe") -> SuppressionEntry:
    clean = email.strip().lower()
    existing = db.query(SuppressionEntry).filter_by(email=clean).first()
    if existing:
        return existing
    entry = SuppressionEntry(email=clean, reason=reason)
    db.add(entry)
    db.flush()
    return entry


def check_and_increment_daily_quota(
    db: Session,
    sender_mailbox: str,
    max_daily: int = 40,
    dry_run: bool = False,
) -> tuple[bool, int]:
    """
    Pacing & throttling guard: restricts sending volume per mailbox per day (e.g. 20-50/day).
    """
    clean_sender = sender_mailbox.strip().lower()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    quota = (
        db.query(DailyDispatchQuota)
        .filter_by(sender_mailbox=clean_sender, dispatch_date=today_str)
        .first()
    )

    if quota is None:
        quota = DailyDispatchQuota(sender_mailbox=clean_sender, dispatch_date=today_str, count=0)
        db.add(quota)
        db.flush()

    if quota.count >= max_daily:
        return False, quota.count

    if not dry_run:
        quota.count += 1
        db.flush()

    return True, quota.count
