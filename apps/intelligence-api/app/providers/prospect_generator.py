from __future__ import annotations

import random
from typing import Any
import uuid


# Curated naming components by niche category
NICHE_PATTERNS: dict[str, dict[str, list[str]]] = {
    "real estate": {
        "prefixes": [
            "Prime", "Apex", "Preston", "Highland", "Summit", "Heritage", "Beacon", "Vanguard",
            "Sterling", "Metropolitan", "Crestview", "Oakridge", "Sovereign", "Paramount",
            "Golden Gate", "Parkview", "Centennial", "Horizon", "Grandview", "Westminster",
            "Crown", "Lakeside", "Ascent", "Meridian", "Riverfront", "Boutique", "First Choice",
            "Urban Living", "Regal", "Latitude", "Compass Point", "Kensington", "Mayfair",
            "Chelsea", "Dallas Metro", "Lone Star", "Trinity River", "Deep Ellum", "Uptown",
            "Highland Park", "Lakewood", "Northgate", "Capital", "Providence", "Pinnacle"
        ],
        "suffixes": [
            "Realty Group", "Properties", "Real Estate Partners", "Estates", "Residential & Commercial",
            "Property Advisers", "Realtors", "Real Estate Co.", "Home Specialists", "Realty Advisors",
            "Living & Land", "Asset Management", "Property Solutions", "Elite Properties", "Brokers Group"
        ],
        "category": "Real estate agency",
    },
    "dental": {
        "prefixes": [
            "Apex", "Smile", "Gentle Care", "Artisan", "Family First", "Precision", "Lumina",
            "Radiant", "Pure", "Complete Care", "Premier", "Parkway", "Elite", "Advanced",
            "Harmony", "Bright Smile", "Dental Arts", "Metro", "Cornerstone", "Signature"
        ],
        "suffixes": [
            "Dental Clinic", "Family Dentistry", "Dental Spa", "Dental Care Center",
            "Oral Health Specialists", "Orthodontics & Dental Care", "Dental Studio"
        ],
        "category": "Dental clinic",
    },
    "legal": {
        "prefixes": [
            "Sterling", "Vanguard", "Beacon", "Apex", "Summit", "Cornerstone", "Preston",
            "Oakridge", "Centennial", "Justice First", "Heritage", "Sovereign", "Alliance"
        ],
        "suffixes": [
            "Law Partners", "Legal Group", "Attorneys at Law", "Advocates & Counselors",
            "Legal Solutions", "Law Practice", "Litigation & Advisory Group"
        ],
        "category": "Legal services",
    },
    "law": {
        "prefixes": [
            "Sterling", "Vanguard", "Beacon", "Apex", "Summit", "Cornerstone", "Preston",
            "Oakridge", "Centennial", "Justice First", "Heritage", "Sovereign", "Alliance",
            "Liberty", "Benchmark", "Pinnacle", "Meridian", "Founders", "Capitol"
        ],
        "suffixes": [
            "Law Partners", "Legal Group", "Attorneys at Law", "Advocates & Counselors",
            "Legal Solutions", "Law Practice", "Litigation & Advisory Group", "Law Firm",
            "Associates & Counsel", "Legal Advisors", "Trial Attorneys"
        ],
        "category": "Law firm",
    },
    "attorney": {
        "prefixes": [
            "Sterling", "Vanguard", "Beacon", "Apex", "Summit", "Cornerstone", "Preston",
            "Oakridge", "Centennial", "Justice First", "Heritage", "Sovereign", "Alliance"
        ],
        "suffixes": [
            "Law Partners", "Legal Group", "Attorneys at Law", "Advocates & Counselors",
            "Legal Solutions", "Law Practice", "Litigation & Advisory Group"
        ],
        "category": "Attorneys",
    },
    "accounting": {
        "prefixes": ["Apex", "Sterling", "Summit", "Prime", "Vanguard", "Beacon", "Precision"],
        "suffixes": ["CPA Group", "Accounting Advisors", "Tax & Financial Services", "Financial Partners"],
        "category": "Accounting firm",
    },
    "roofing": {
        "prefixes": ["Apex", "Summit", "Pinnacle", "Vanguard", "Precision", "Heritage", "Titan"],
        "suffixes": ["Roofing Specialists", "Roofing & Construction", "Roofing Solutions", "Roofing Co."],
        "category": "Roofing contractor",
    },
    "hvac": {
        "prefixes": ["Apex", "Climate Care", "Precision", "Prime", "Air Solutions", "Pure"],
        "suffixes": ["HVAC Services", "Heating & Air Conditioning", "Air Systems", "Mechanical Services"],
        "category": "HVAC contractor",
    },
}

DEFAULT_PREFIXES = [
    "Apex", "Prime", "Summit", "Vanguard", "Beacon", "Sterling", "Pinnacle",
    "Preston", "Horizon", "Crestview", "Heritage", "Metropolitan", "Alliance",
    "Nexus", "Empower", "Catalyst", "Alpha", "Velocity", "Synergy", "Quantum"
]

DEFAULT_SUFFIXES = [
    "Solutions", "Group", "Partners", "Enterprises", "Associates", "Services",
    "Advisors", "Consulting", "Innovations", "Systems", "Specialists", "Direct"
]


def _get_area_code_and_city(location: str) -> tuple[str, str, str]:
    """Returns (phone_prefix, city_name, street_suffix) based on location string."""
    loc_lower = location.lower()
    if "london" in loc_lower or "uk" in loc_lower or "england" in loc_lower:
        return ("+44 20 7946", "London", "Street, London EC2")
    elif "dallas" in loc_lower or "tx" in loc_lower or "texas" in loc_lower:
        return ("+1 214-555", "Dallas", "St, Dallas, TX 75201")
    elif "austin" in loc_lower:
        return ("+1 512-555", "Austin", "Congress Ave, Austin, TX 78701")
    elif "new york" in loc_lower or "nyc" in loc_lower:
        return ("+1 212-555", "New York", "Broadway, New York, NY 10001")
    elif "los angeles" in loc_lower or "la" in loc_lower or "california" in loc_lower:
        return ("+1 310-555", "Los Angeles", "Wilshire Blvd, Los Angeles, CA 90024")
    elif "chicago" in loc_lower:
        return ("+1 312-555", "Chicago", "Michigan Ave, Chicago, IL 60601")
    elif "miami" in loc_lower or "florida" in loc_lower:
        return ("+1 305-555", "Miami", "Biscayne Blvd, Miami, FL 33131")
    else:
        city = location.split(",")[0].strip() or "Metropolis"
        return ("+1 415-555", city, f"Main St, {city}")


def generate_candidate_businesses(
    niche: str,
    location: str,
    count: int = 50,
    seed_offset: int = 0,
) -> list[dict[str, Any]]:
    """
    Generates deterministic, highly realistic candidate businesses for any niche and location.
    Distributes website scenarios across:
    - explicit_intent (scores 90-98, high intent)
    - listing_form (scores 82-88, qualified)
    - widgets (scores 75-84)
    - whatsapp (scores 70-78)
    - brochure (scores 55-65)
    - unreachable (scores 30-45)
    - no_website (scores 40-50)
    """
    niche_lower = niche.lower()
    matched_niche = None
    for k in NICHE_PATTERNS:
        if k in niche_lower:
            matched_niche = NICHE_PATTERNS[k]
            break

    prefixes = matched_niche["prefixes"] if matched_niche else DEFAULT_PREFIXES
    suffixes = matched_niche["suffixes"] if matched_niche else [f"{niche.title()} {s}" for s in DEFAULT_SUFFIXES]
    category = matched_niche["category"] if matched_niche else f"{niche.title()} services"

    phone_prefix, city_name, street_template = _get_area_code_and_city(location)

    # Scenarios for website audit to produce realistic score spread
    # ~55% will score >= 80 (explicit_intent + listing_form + some widgets)
    scenarios_cycle = [
        "explicit_intent",
        "listing_form",
        "explicit_intent",
        "listing_form",
        "widgets",
        "whatsapp",
        "brochure",
        "widgets",
        "no_website",
        "unreachable",
    ]

    streets = [
        "Main St", "Market St", "High St", "Park Ave", "Commercial Way",
        "Kingsway", "Victoria Rd", "Baker St", "Oxford St", "Regent St",
        "Commerce St", "Elm St", "Oak Lawn Ave", "McKinney Ave", "Preston Rd"
    ]

    businesses: list[dict[str, Any]] = []
    rng = random.Random(42 + seed_offset)

    for i in range(count):
        idx = seed_offset + i
        p = prefixes[idx % len(prefixes)]
        s = suffixes[(idx // len(prefixes) + idx) % len(suffixes)]
        name = f"{p} {s}"
        if i >= len(prefixes) * len(suffixes):
            name = f"{name} #{i + 1}"

        scenario = scenarios_cycle[i % len(scenarios_cycle)]
        if scenario == "no_website":
            website = None
        else:
            website = f"https://fixtures.intentlead.test/{scenario}?biz={idx+1}"

        street_num = 100 + (idx * 17) % 8900
        street_name = streets[idx % len(streets)]
        address = f"{street_num} {street_name}, {city_name}"

        phone_num = f"{phone_prefix}-{1000 + (idx * 31) % 8999:04d}"
        rating = round(3.8 + (idx % 12) * 0.1, 1)
        review_count = 15 + (idx * 13) % 250

        clean_domain = p.lower().replace(" ", "").replace("&", "") + s.lower().replace(" ", "").replace("&", "")
        email = f"contact@{clean_domain[:20]}.com"

        # Provide process friction reviews on explicit_intent and brochure candidates
        # to reflect real operational pain points (slow response, hard to reach, friction)
        if scenario in ("explicit_intent", "brochure", "widgets"):
            reviews = [
                f"Slow response time to customer inquiry at {name}.",
                f"Hard to reach online; experienced friction booking consultation.",
            ]
        else:
            reviews = [
                f"Good {niche_lower} service in {city_name}",
                f"Professional team at {name}",
            ]

        businesses.append({
            "title": name,
            "category": category,
            "address": address,
            "locality": city_name,
            "website": website,
            "phone": phone_num,
            "emails": [email],
            "rating": rating,
            "reviewCount": review_count,
            "placeId": f"gen-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{name}-{city_name}')}",
            "reviews": reviews,
            "listingStatus": "open",
            "scenario": scenario,
        })

    return businesses
