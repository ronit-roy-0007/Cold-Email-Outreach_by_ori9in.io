from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURL(Exception):
    pass


@dataclass
class ResolvedTarget:
    url: str
    hostname: str
    port: int
    ip: str


BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata.google.com",
}

BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    # IPv6
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("2001:db8::/32"),
]


def _is_ip_blocked(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip_obj.version == 6 and ip_obj.ipv4_mapped:
        ip_obj = ip_obj.ipv4_mapped

    if (
        ip_obj.is_loopback
        or ip_obj.is_private
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    ):
        return True

    for net in BLOCKED_NETWORKS:
        if ip_obj in net:
            return True

    return False


def validate_public_url(
    url: str, resolver: Callable[[str], list[str]] | None = None
) -> ResolvedTarget:
    if not url:
        raise UnsafeURL("Empty URL")

    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise UnsafeURL(f"Failed to parse URL: {exc}") from exc

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise UnsafeURL(f"Scheme '{scheme}' is not allowed; only http and https are permitted")

    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        raise UnsafeURL("Userinfo credentials are not allowed in audited URLs")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURL("URL missing hostname")

    hostname_clean = hostname.strip("[]").lower()

    if hostname_clean in BLOCKED_HOSTNAMES or hostname_clean.endswith(".internal"):
        raise UnsafeURL(f"Blocked hostname: {hostname}")

    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    elif port not in (80, 443):
        raise UnsafeURL(f"Port {port} is not allowed; only ports 80 and 443 are permitted")

    # Check if hostname is an IP literal
    is_literal = False
    try:
        ip_obj = ipaddress.ip_address(hostname_clean)
        is_literal = True
        resolved_ips = [str(ip_obj)]
    except ValueError:
        is_literal = False

    if not is_literal:
        if resolver is not None:
            resolved_ips = resolver(hostname)
        else:
            try:
                addrinfo = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
                resolved_ips = [info[4][0] for info in addrinfo]
            except Exception as exc:
                raise UnsafeURL(f"DNS resolution failed for {hostname}: {exc}") from exc

    if not resolved_ips:
        raise UnsafeURL(f"No IP addresses resolved for hostname: {hostname}")

    for ip_str in resolved_ips:
        try:
            ip_obj = ipaddress.ip_address(ip_str.strip("[]"))
        except ValueError as exc:
            raise UnsafeURL(f"Invalid resolved IP '{ip_str}': {exc}") from exc

        if _is_ip_blocked(ip_obj):
            raise UnsafeURL(f"Resolved address {ip_str} is in a blocked network range")

    return ResolvedTarget(
        url=url,
        hostname=hostname,
        port=port,
        ip=resolved_ips[0],
    )
