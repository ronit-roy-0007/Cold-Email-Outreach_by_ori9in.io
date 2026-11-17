import pytest

from app.services.ssrf import UnsafeURL, validate_public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "file:///etc/passwd",
        "http://example.com:8080/",
        "http://user:pass@example.com/",
    ],
)
def test_blocked(url):
    with pytest.raises(UnsafeURL):
        validate_public_url(url)


def test_redirect_to_private_is_blocked():
    with pytest.raises(UnsafeURL):
        validate_public_url("http://192.168.0.5/next")


def test_hostname_resolving_to_loopback_blocked():
    with pytest.raises(UnsafeURL):
        validate_public_url("http://evil.test/", resolver=lambda h: ["127.0.0.1"])


def test_public_a_record_allowed():
    t = validate_public_url("https://example.com/", resolver=lambda h: ["93.184.216.34"])
    assert t.ip == "93.184.216.34"
    assert t.port == 443
    assert t.hostname == "example.com"


def test_metadata_hostnames_blocked():
    with pytest.raises(UnsafeURL):
        validate_public_url(
            "http://metadata.google.internal/", resolver=lambda h: ["93.184.216.34"]
        )


def test_nat64_public_ipv4_allowed():
    # 64:ff9b::d471:c6ca translates to 212.113.198.202 (public IP)
    t = validate_public_url("http://example.com/", resolver=lambda h: ["64:ff9b::d471:c6ca"])
    assert t.ip == "64:ff9b::d471:c6ca"


def test_nat64_loopback_and_private_blocked():
    # 64:ff9b::7f00:1 translates to 127.0.0.1 (loopback)
    with pytest.raises(UnsafeURL):
        validate_public_url("http://evil.com/", resolver=lambda h: ["64:ff9b::7f00:1"])

    # 64:ff9b::a00:1 translates to 10.0.0.1 (private)
    with pytest.raises(UnsafeURL):
        validate_public_url("http://evil.com/", resolver=lambda h: ["64:ff9b::a00:1"])

    # 64:ff9b::a9fe:a9fe translates to 169.254.169.254 (metadata)
    with pytest.raises(UnsafeURL):
        validate_public_url("http://evil.com/", resolver=lambda h: ["64:ff9b::a9fe:a9fe"])

