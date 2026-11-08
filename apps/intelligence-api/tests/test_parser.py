from app.services.parser import parse_campaign, ParseError


def test_rejects_missing_required():
    err = parse_campaign({})
    assert isinstance(err, ParseError)
    assert "niche" in err.fields
    assert "location" in err.fields
    assert "requested_quantity" in err.fields
    assert "target_services" in err.fields


def test_quantity_bounds():
    err = parse_campaign({"niche": "n", "location": "Dallas, Texas", "requested_quantity": 0, "target_services": ["ai_chatbot"]})
    assert isinstance(err, ParseError)
    ok = parse_campaign({"niche": "n", "location": "Dallas, Texas", "requested_quantity": 10, "target_services": ["ai_chatbot"]})
    assert ok.dry_run is True
    assert ok.requested_quantity == 10


def test_quantity_max_25():
    err = parse_campaign({"niche": "n", "location": "Dallas, Texas", "requested_quantity": 26, "target_services": ["ai_chatbot"]})
    assert isinstance(err, ParseError)


def test_does_not_invent_services():
    err = parse_campaign({"niche": "n", "location": "Dallas, Texas", "requested_quantity": 5, "target_services": ["seo"]})
    assert isinstance(err, ParseError)


def test_always_dry_run():
    ok = parse_campaign({"niche": "n", "location": "Dallas, Texas", "requested_quantity": 5, "target_services": ["website_redesign"], "dry_run": False})
    assert ok.dry_run is True
