from app.providers.import_loader import load_import


def test_json_import_labels_import():
    data = b'[{"name":"A","address":"1 Main","city":"Dallas","category":"Real estate agency"}]'
    result = load_import(data, "x.json")
    assert result.listings[0].discovery_source == "import"
    assert result.listings[0].locality == "Dallas"
    assert result.listings[0].name == "A"


def test_missing_name_rejected_others_kept():
    data = b'[{"name":"","city":"Dallas"},{"name":"B","address":"2 Oak","city":"Dallas"}]'
    result = load_import(data, "x.json")
    assert len(result.listings) == 1
    assert result.listings[0].name == "B"
    assert len(result.row_errors) == 1


def test_csv_import_succeeds():
    csv_data = (
        b"name,category,address,city,website,phone,email,rating,review_count,place_id\n"
        b"Acme Realty,Real estate agency,100 Main St,Dallas,https://example.com,+12145550100,info@example.com,4.5,20,ChIJ-123\n"
        b",Real estate agency,200 Oak St,Dallas,,,,,,\n"
    )
    result = load_import(csv_data, "leads.csv")
    assert len(result.listings) == 1
    assert len(result.row_errors) == 1
    listing = result.listings[0]
    assert listing.name == "Acme Realty"
    assert listing.category == "Real estate agency"
    assert listing.address == "100 Main St"
    assert listing.locality == "Dallas"
    assert listing.website == "https://example.com"
    assert listing.phone == "+12145550100"
    assert listing.email == "info@example.com"
    assert listing.rating == 4.5
    assert listing.review_count == 20
    assert listing.place_id == "ChIJ-123"
    assert listing.discovery_source == "import"
