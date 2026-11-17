from __future__ import annotations

import re
from typing import Any

NEARBY_REGION_MAP: dict[str, list[str]] = {
    # Broad / Nationwide / Multi-Metro Fallbacks
    "nationwide": ["New York, NY", "Los Angeles, CA", "Chicago, IL", "Houston, TX", "Dallas, TX", "Miami, FL", "Atlanta, GA"],
    "usa": ["New York, NY", "Los Angeles, CA", "Chicago, IL", "Houston, TX", "Dallas, TX", "Miami, FL", "Atlanta, GA"],
    "united states": ["New York, NY", "Los Angeles, CA", "Chicago, IL", "Houston, TX", "Dallas, TX", "Miami, FL", "Atlanta, GA"],
    "us": ["New York, NY", "Los Angeles, CA", "Chicago, IL", "Houston, TX", "Dallas, TX", "Miami, FL", "Atlanta, GA"],
    "india": ["Delhi", "Mumbai", "Bangalore", "Hyderabad", "Chennai", "Kolkata", "Pune"],
    "pan india": ["Delhi", "Mumbai", "Bangalore", "Hyderabad", "Chennai", "Kolkata", "Pune"],
    "uk": ["London", "Manchester", "Birmingham", "Leeds", "Glasgow", "Edinburgh"],
    "united kingdom": ["London", "Manchester", "Birmingham", "Leeds", "Glasgow", "Edinburgh"],
    "england": ["London", "Manchester", "Birmingham", "Leeds", "Liverpool", "Bristol", "Newcastle", "Sheffield"],
    # India Cities
    "delhi": ["Noida", "Gurugram", "Ghaziabad", "Faridabad", "Greater Noida", "South Delhi", "Dwarka"],
    "new delhi": ["South Delhi", "Noida", "Gurugram", "Ghaziabad", "Faridabad"],
    "mumbai": ["Navi Mumbai", "Thane", "Kalyan", "Mira Bhayandar"],
    "bangalore": ["Whitefield", "Electronic City", "Yelahanka", "Sarjapur", "Koramangala"],
    "bengaluru": ["Whitefield", "Electronic City", "Yelahanka", "Sarjapur", "Koramangala"],
    "hyderabad": ["Secunderabad", "Gachibowli", "Hitec City", "Cyberabad"],
    "chennai": ["Tambaram", "Ambattur", "Avadi", "OMR"],
    "kolkata": ["Howrah", "Salt Lake", "New Town", "Rajarhat"],
    "pune": ["Pimpri-Chinchwad", "Hinjawadi", "Wakad", "Hadapsar"],
    "jaipur": ["Mansarovar", "Vaishali Nagar", "Malviya Nagar", "Sitapura"],
    # US & Canada
    "dallas": ["Fort Worth", "Plano", "Irving", "Arlington", "Frisco"],
    "austin": ["Round Rock", "Cedar Park", "Georgetown", "Pflugerville"],
    "houston": ["Sugar Land", "The Woodlands", "Katy", "Pearland"],
    "new york": ["Brooklyn", "Queens", "Jersey City", "Bronx", "Staten Island"],
    "nyc": ["Brooklyn", "Queens", "Jersey City", "Bronx", "Staten Island"],
    "los angeles": ["Pasadena", "Glendale", "Long Beach", "Santa Monica", "Burbank"],
    "chicago": ["Naperville", "Evanston", "Schaumburg", "Oak Park"],
    "miami": ["Fort Lauderdale", "Hialeah", "Coral Gables", "Hollywood"],
    "toronto": ["Mississauga", "Brampton", "Markham", "Vaughan"],
    # UK & Europe
    "london": ["Westminster", "Camden", "Greenwich", "Croydon", "Richmond", "Watford"],
    "manchester": ["Salford", "Stockport", "Bolton", "Oldham"],
    "birmingham": ["Solihull", "Wolverhampton", "Dudley", "Walsall"],
    "paris": ["Boulogne-Billancourt", "Saint-Denis", "Versailles", "Nanterre"],
}


def get_nearby_regions(location: str) -> list[str]:
    """
    Returns concentric rings / adjacent regions for a given location.
    """
    loc_clean = location.lower().strip()
    for key, regions in NEARBY_REGION_MAP.items():
        if key in loc_clean:
            return list(regions)

    # General fallback for any unmapped town or city
    clean_title = location.strip().title()
    return [
        f"Greater {clean_title}",
        f"{clean_title} North",
        f"{clean_title} South",
        f"{clean_title} East",
        f"{clean_title} West",
    ]


def get_next_expansion_location(location: str, visited_locations: list[str] | None = None) -> str | None:
    """
    Finds the next concentric location that has not been searched yet.
    """
    visited_lower = {v.lower().strip() for v in (visited_locations or [])}
    visited_lower.add(location.lower().strip())

    candidates = get_nearby_regions(location)
    for cand in candidates:
        if cand.lower().strip() not in visited_lower:
            return cand

    # Outer ring fallback centered on initial location
    clean_title = location.strip().title()
    ring_num = len(visited_lower)
    return f"Greater {clean_title} Outer Ring {ring_num}"
