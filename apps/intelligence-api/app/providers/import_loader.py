from __future__ import annotations

import csv
from dataclasses import dataclass, field
import io
import json
from typing import Any

from app.providers.types import NormalizedListing


@dataclass
class ImportResult:
    listings: list[NormalizedListing] = field(default_factory=list)
    row_errors: list[str] = field(default_factory=list)


def _clean_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def load_import(content: bytes, filename: str) -> ImportResult:
    result = ImportResult()
    filename_lower = filename.lower()

    rows: list[dict[str, Any]] = []

    if filename_lower.endswith(".json"):
        try:
            text = content.decode("utf-8", errors="replace")
            parsed = json.loads(text)
            if isinstance(parsed, list):
                rows = parsed
            else:
                result.row_errors.append("JSON root must be an array of objects")
                return result
        except Exception as exc:
            result.row_errors.append(f"Invalid JSON: {exc}")
            return result
    else:
        try:
            text = content.decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            rows = [dict(r) for r in reader]
        except Exception as exc:
            result.row_errors.append(f"Invalid CSV: {exc}")
            return result

    for idx, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            result.row_errors.append(f"Row {idx}: expected object, got {type(row).__name__}")
            continue

        name = _clean_str(row.get("name") or row.get("title"))
        locality = _clean_str(row.get("city") or row.get("locality"))
        address = _clean_str(row.get("address"))

        if not name:
            result.row_errors.append(f"Row {idx}: missing required 'name'")
            continue

        if not locality and not address:
            result.row_errors.append(f"Row {idx}: missing required location ('city' or 'address')")
            continue

        place_id = _clean_str(row.get("place_id") or row.get("placeId"))
        category = _clean_str(row.get("category"))
        website = _clean_str(row.get("website"))
        phone = _clean_str(row.get("phone"))

        email = _clean_str(row.get("email"))
        if not email and isinstance(row.get("emails"), list) and row.get("emails"):
            email = _clean_str(row["emails"][0])

        rating: float | None = None
        raw_rating = row.get("rating")
        if raw_rating not in (None, ""):
            try:
                rating = float(raw_rating)
            except (ValueError, TypeError):
                rating = None

        review_count: int | None = None
        raw_rc = row.get("review_count") if "review_count" in row else row.get("reviewCount")
        if raw_rc not in (None, ""):
            try:
                review_count = int(float(raw_rc))
            except (ValueError, TypeError):
                review_count = None

        listing_status = _clean_str(row.get("listing_status") or row.get("listingStatus"))
        reviews = row.get("reviews") if isinstance(row.get("reviews"), list) else []

        listing = NormalizedListing(
            place_id=place_id,
            name=name,
            category=category,
            address=address,
            locality=locality,
            website=website,
            phone=phone,
            email=email,
            rating=rating,
            review_count=review_count,
            listing_status=listing_status,
            source_fields=row,
            discovery_source="import",
            reviews=reviews,
        )
        result.listings.append(listing)

    return result
