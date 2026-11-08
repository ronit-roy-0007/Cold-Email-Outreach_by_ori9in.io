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
