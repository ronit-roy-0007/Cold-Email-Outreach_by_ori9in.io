from app.services.robots import robots_allows


def test_disallow_star():
    txt = "User-agent: *\nDisallow: /hidden\n"
    assert robots_allows(txt, "https://ex.com/") is True
    assert robots_allows(txt, "https://ex.com/hidden/page") is False


def test_unknown_allows():
    assert robots_allows(None, "https://ex.com/") is True


def test_custom_user_agent_disallow():
    txt = "User-agent: IntentLeadBot\nDisallow: /secret\nUser-agent: *\nDisallow: /nothing\n"
    assert robots_allows(txt, "https://ex.com/secret") is False
    assert robots_allows(txt, "https://ex.com/public") is True
