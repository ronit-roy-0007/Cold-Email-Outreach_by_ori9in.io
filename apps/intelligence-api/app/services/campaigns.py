from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Approval,
    AuditLog,
    Campaign,
    CampaignLeftoverLead,
    Conversation,
    ConversationMessage,
    DimensionScore,
    Evidence,
    FollowUpExecution,
    Lead,
    MessageDraft,
    OutboundMessage,
    ScrapeJob,
    ServiceScore,
)
from app.services.parser import parse_campaign, ParseError


def create_campaign(session: Session, payload: dict[str, Any], settings: Settings) -> Campaign:
    parsed = parse_campaign(payload)
    if isinstance(parsed, ParseError):
        raise ValueError(f"Campaign validation failed: {', '.join(parsed.fields)}")

    provider = payload.get("provider") or settings.DISCOVERY_PROVIDER

    campaign = Campaign(
        niche=parsed.niche,
        location=parsed.location,
        requested_quantity=parsed.requested_quantity,
        target_services=parsed.target_services,
        filters=parsed.filters,
        followup_sequence=payload.get("followup_sequence", {}),
        provider=provider,
        dry_run=payload.get("dry_run", settings.OUTREACH_DRY_RUN if settings else False),
        status="pending",
    )
    session.add(campaign)
    session.flush()

    scrape_job = ScrapeJob(
        campaign_id=campaign.id,
        provider=provider,
        external_job_id="",
        status="pending",
    )
    session.add(scrape_job)
    session.flush()

    return campaign


def list_campaigns(session: Session) -> list[Campaign]:
    return session.query(Campaign).order_by(Campaign.created_at.desc()).all()


def get_campaign(session: Session, campaign_id: uuid.UUID) -> Campaign | None:
    return session.get(Campaign, campaign_id)


def delete_campaign(session: Session, campaign_id: uuid.UUID) -> bool:
    camp = session.get(Campaign, campaign_id)
    if not camp:
        return False

    lead_ids = [r[0] for r in session.query(Lead.id).filter(Lead.campaign_id == campaign_id).all()]

    if lead_ids:
        session.query(DimensionScore).filter(DimensionScore.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        session.query(ServiceScore).filter(ServiceScore.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        session.query(MessageDraft).filter(MessageDraft.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        session.query(Approval).filter(Approval.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        session.query(OutboundMessage).filter(OutboundMessage.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        session.query(CampaignLeftoverLead).filter(CampaignLeftoverLead.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        session.query(FollowUpExecution).filter(FollowUpExecution.lead_id.in_(lead_ids)).delete(synchronize_session=False)

    # Clean conversations linked to campaign or leads
    if lead_ids:
        conv_query = session.query(Conversation.id).filter(
            or_(Conversation.campaign_id == campaign_id, Conversation.lead_id.in_(lead_ids))
        )
    else:
        conv_query = session.query(Conversation.id).filter(Conversation.campaign_id == campaign_id)

    conv_ids = [r[0] for r in conv_query.all()]
    if conv_ids:
        session.query(ConversationMessage).filter(ConversationMessage.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        session.query(FollowUpExecution).filter(FollowUpExecution.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        session.query(Conversation).filter(Conversation.id.in_(conv_ids)).delete(synchronize_session=False)

    # Clean leftover references and direct campaign records
    session.query(CampaignLeftoverLead).filter(
        or_(CampaignLeftoverLead.campaign_id == campaign_id, CampaignLeftoverLead.consumed_by_campaign_id == campaign_id)
    ).delete(synchronize_session=False)
    session.query(OutboundMessage).filter(OutboundMessage.campaign_id == campaign_id).delete(synchronize_session=False)
    session.query(FollowUpExecution).filter(FollowUpExecution.campaign_id == campaign_id).delete(synchronize_session=False)
    session.query(Evidence).filter(Evidence.campaign_id == campaign_id).delete(synchronize_session=False)
    session.query(ScrapeJob).filter(ScrapeJob.campaign_id == campaign_id).delete(synchronize_session=False)
    session.query(AuditLog).filter(AuditLog.entity_id == campaign_id).delete(synchronize_session=False)

    # Delete Leads
    session.query(Lead).filter(Lead.campaign_id == campaign_id).delete(synchronize_session=False)

    # Finally delete Campaign
    session.delete(camp)
    session.commit()
    return True

