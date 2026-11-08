from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    niche: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str] = mapped_column(String, nullable=False)
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    target_services: Mapped[Any] = mapped_column(JSON, nullable=False)
    filters: Mapped[Any] = mapped_column(JSON, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("campaigns.id"), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    external_job_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_snapshot: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    identity_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    place_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    locality: Mapped[str | None] = mapped_column(String, nullable=True)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    listing_status: Mapped[str | None] = mapped_column(String, nullable=True)
    source_fields: Mapped[Any] = mapped_column(JSON, nullable=False)
    discovery_source: Mapped[str] = mapped_column(String, nullable=False)
    scrape_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("scrape_jobs.id"), nullable=True
    )


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source_scope: Mapped[str | None] = mapped_column(String, nullable=True)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("campaigns.id"), nullable=False
    )
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_type: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    inspected_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String, nullable=False)
    supporting_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    caveat: Mapped[str | None] = mapped_column(Text, nullable=True)


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("campaign_id", "business_id", name="uq_leads_campaign_business"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("campaigns.id"), nullable=False
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[str] = mapped_column(String, nullable=False)
    recommended_service: Mapped[str | None] = mapped_column(String, nullable=True)
    outreach_status: Mapped[str] = mapped_column(
        String, nullable=False, default="draft"
    )
    crm_stage: Mapped[str | None] = mapped_column(String, nullable=True)


class DimensionScore(Base):
    __tablename__ = "dimension_scores"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(String, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    max_points: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_ids: Mapped[Any] = mapped_column(JSON, nullable=False)
    reason_code: Mapped[str] = mapped_column(String, nullable=False)


class ServiceScore(Base):
    __tablename__ = "service_scores"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    service: Mapped[str] = mapped_column(String, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_ids: Mapped[Any] = mapped_column(JSON, nullable=False)
    reason_code: Mapped[str] = mapped_column(String, nullable=False)


class MessageDraft(Base):
    __tablename__ = "message_drafts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String, nullable=False, default="preview")
    status: Mapped[str] = mapped_column(String, nullable=False, default="preview")
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    not_recommended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ids: Mapped[Any] = mapped_column(JSON, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    payload: Mapped[Any] = mapped_column(JSON, nullable=False)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
