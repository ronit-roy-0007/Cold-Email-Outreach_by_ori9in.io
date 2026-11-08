from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NormalizedListing(BaseModel):
    place_id: str | None = None
    name: str
    category: str | None = None
    address: str | None = None
    locality: str | None = None
    website: str | None = None
    phone: str | None = None
    email: str | None = None
    rating: float | None = None
    review_count: int | None = None
    listing_status: str | None = None
    source_fields: dict[str, Any] = Field(default_factory=dict)
    discovery_source: str
    reviews: list[str] = []
