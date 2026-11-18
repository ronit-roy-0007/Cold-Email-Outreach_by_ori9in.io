from __future__ import annotations

import logging
import httpx

logger = logging.getLogger(__name__)

# Fast offline coordinates for major global & metropolitan areas
CITY_COORDINATES: dict[str, tuple[str, str]] = {
    # India
    "delhi": ("28.6139", "77.2090"),
    "new delhi": ("28.6139", "77.2090"),
    "mumbai": ("19.0760", "72.8777"),
    "bangalore": ("12.9716", "77.5946"),
    "bengaluru": ("12.9716", "77.5946"),
    "hyderabad": ("17.3850", "78.4867"),
    "chennai": ("13.0827", "80.2707"),
    "kolkata": ("22.5726", "88.3639"),
    "pune": ("18.5204", "73.8567"),
    "ahmedabad": ("23.0225", "72.5714"),
    "jaipur": ("26.9124", "75.7873"),
    "noida": ("28.5355", "77.3910"),
    "gurgaon": ("28.4595", "77.0266"),
    "gurugram": ("28.4595", "77.0266"),
    # UK & Europe
    "london": ("51.5074", "-0.1278"),
    "manchester": ("53.4808", "-2.2426"),
    "birmingham": ("52.4862", "-1.8904"),
    "edinburgh": ("55.9533", "-3.1883"),
    "paris": ("48.8566", "2.3522"),
    "berlin": ("52.5200", "13.4050"),
    "amsterdam": ("52.3676", "4.9041"),
    "dublin": ("53.3498", "-6.2603"),
    # US & Canada
    "dallas": ("32.7767", "-96.7970"),
    "austin": ("30.2672", "-97.7431"),
    "houston": ("29.7604", "-95.3698"),
    "new york": ("40.7128", "-74.0060"),
    "nyc": ("40.7128", "-74.0060"),
    "los angeles": ("34.0522", "-118.2437"),
    "la": ("34.0522", "-118.2437"),
    "chicago": ("41.8781", "-87.6298"),
    "san francisco": ("37.7749", "-122.4194"),
    "miami": ("25.7617", "-80.1918"),
    "seattle": ("47.6062", "-122.3321"),
    "toronto": ("43.6532", "-79.3832"),
    "vancouver": ("49.2827", "-123.1207"),
    # Australia & Asia
    "sydney": ("-33.8688", "151.2093"),
    "melbourne": ("-37.8136", "144.9631"),
    "dubai": ("25.2048", "55.2708"),
    "singapore": ("1.3521", "103.8198"),
    "tokyo": ("35.6762", "139.6503"),
}


def geocode_location(location: str) -> tuple[str, str]:
    """
    Returns (lat, lon) strings for a given location string.
    Checks fast offline lookup first, then OpenStreetMap Nominatim.
    Defaults to ('28.6139', '77.2090') if unresolvable.
    """
    if not location or not location.strip():
        return "28.6139", "77.2090"

    loc_clean = location.lower().strip()
    for city, coords in CITY_COORDINATES.items():
        if city in loc_clean:
            return coords

    # Try OpenStreetMap Nominatim for any unlisted city
    try:
        url = "https://nominatim.openstreetmap.org/search"
        resp = httpx.get(
            url,
            params={"q": location, "format": "json", "limit": 1},
            headers={"User-Agent": "IntentLead-Scraper/1.0"},
            timeout=3.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0 and "lat" in data[0] and "lon" in data[0]:
                return str(data[0]["lat"]), str(data[0]["lon"])
    except Exception as exc:
        logger.warning("Online geocoding lookup failed for '%s': %s", location, exc)

    return "28.6139", "77.2090"
