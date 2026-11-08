from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CampaignInput(BaseModel):
    niche: str
    location: str
    requested_quantity: int
    target_services: list[str]
    filters: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True


class ParseError:
    def __init__(self, fields: list[str]) -> None:
        self.fields = fields
