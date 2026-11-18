from __future__ import annotations

import hashlib
import hmac
import urllib.parse


def generate_unsubscribe_token(email: str, secret: str) -> str:
    clean = email.strip().lower()
    return hmac.new(secret.encode("utf-8"), clean.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def verify_unsubscribe_token(email: str, token: str, secret: str) -> bool:
    clean = email.strip().lower()
    expected = generate_unsubscribe_token(clean, secret)
    return hmac.compare_digest(token.strip(), expected)


def build_unsubscribe_url(email: str, secret: str, base_url: str) -> str:
    clean = email.strip().lower()
    token = generate_unsubscribe_token(clean, secret)
    query = urllib.parse.urlencode({"email": clean, "token": token})
    clean_base = base_url.rstrip("/")
    return f"{clean_base}?{query}"


def format_compliant_email_body(
    body: str,
    agency_name: str,
    sender_name: str,
    agency_address: str,
    unsubscribe_url: str,
    force_footer: bool = False,
) -> str:
    """
    Appends CAN-SPAM compliant agency physical address footer and automated 1-click unsubscribe link.
    Skips footer entirely for cold outreach messages (both generic high-reply and personalized AI pitches)
    so the email looks 100% genuine, clean, and personal without any footer description or unsubscribe link.
    """
    clean_body = (body or "").strip()
    if not force_footer:
        # High-reply casual outreach or personalized AI pitches should never contain corporate footers or unsubscribe links
        if (
            "tried to reach you a few times" in clean_body
            or "Should I show you the demo" in clean_body
            or "Where should we go from here" in clean_body
        ):
            return clean_body

    address_line = f"{agency_address.strip()}\n" if agency_address.strip() else ""
    footer = (
        f"\n\n--\n"
        f"{sender_name.strip() or 'Outreach Team'} | {agency_name.strip() or 'Agency'}\n"
        f"{address_line}"
        f"To unsubscribe from future inquiries, click here: {unsubscribe_url}"
    )
    return clean_body + footer


def get_unsubscribe_headers(unsubscribe_url: str) -> dict[str, str]:
    """
    RFC 8058 standard 1-click unsubscribe headers for Gmail / Yahoo / Microsoft deliverability.
    """
    return {
        "List-Unsubscribe": f"<{unsubscribe_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
