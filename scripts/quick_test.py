import os
import sys

# Configure environment for development run
os.environ["APP_ENV"] = "development"
os.environ["DATABASE_URL"] = "sqlite:///./dev_quick_test.db"
os.environ["DISCOVERY_PROVIDER"] = "mock"
os.environ["AGENCY_NAME"] = "Apex Automation Labs"
os.environ["AGENCY_SENDER_NAME"] = "Jordan Reed"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db import engine, SessionLocal
from app.models import Base, Lead, Business, MessageDraft, DimensionScore, Evidence
from app.config import get_settings
from app.services.campaigns import create_campaign
from app.services.pipeline import run_campaign

# Create tables in SQLite
Base.metadata.create_all(bind=engine)
session = SessionLocal()

print("=" * 80)
print("INTENTLEAD AI — QUICK END-TO-END PIPELINE TEST")
print("=" * 80)

payload = {
    "niche": "Real Estate Agencies",
    "location": "Dallas, Texas",
    "requested_quantity": 10,
    "target_services": [
        "website_development",
        "website_redesign",
        "real_estate_listing_portal",
        "ai_chatbot",
    ],
    "filters": {},
}

settings = get_settings()

print("\n1. Creating Campaign...")
campaign = create_campaign(session, payload, settings)
print(f"   Campaign ID: {campaign.id}")
print(f"   Target: {campaign.niche} in {campaign.location} (Qty: {campaign.requested_quantity})")
print(f"   Provider: {campaign.provider} | Dry-run: {campaign.dry_run}")

print("\n2. Executing Discovery -> Audit -> Scoring -> Draft Pipeline...")
run_campaign(session, campaign.id, settings)
print(f"   Pipeline Status: {campaign.status.upper()}")

leads = (
    session.query(Lead, Business)
    .join(Business, Lead.business_id == Business.id)
    .filter(Lead.campaign_id == campaign.id)
    .order_by(Lead.overall_score.desc())
    .all()
)

print(f"\n3. Pipeline Results: {len(leads)} Unique Leads Scored & Audited\n")
print(f"{'PRIORITY':<10} {'SCORE':<10} {'BUSINESS NAME':<30} {'RECOMMENDED SERVICE':<30}")
print("-" * 80)

for lead, biz in leads:
    svc = lead.recommended_service or "None (< 40)"
    print(f"[{lead.priority}]        {lead.overall_score:>3d}/100    {biz.name:<30} {svc:<30}")

print("-" * 80)

# Sample the top lead
top_lead, top_biz = leads[0]
top_draft = session.query(MessageDraft).filter_by(lead_id=top_lead.id).first()
top_evidence = (
    session.query(Evidence)
    .filter_by(business_id=top_biz.id, campaign_id=campaign.id)
    .all()
)
top_dims = session.query(DimensionScore).filter_by(lead_id=top_lead.id).all()

print(f"\n4. Deep Dive on Top Lead: '{top_biz.name}'")
print(f"   Website: {top_biz.website or 'None'}")
print(f"   Phone: {top_biz.phone} | Source: {top_biz.discovery_source}")
print(f"   Overall Score: {top_lead.overall_score}/100 (Priority: {top_lead.priority}, Confidence: {top_lead.confidence})")
print("   Score Dimensions Breakdown:")
for d in top_dims:
    print(f"     - {d.dimension:<25}: {d.points:>2d}/{d.max_points:>2d} pts (reason: {d.reason_code})")

print(f"\n5. Generated Dry-Run Outreach Draft (Status: {top_draft.status}):")
print("-" * 80)
print(top_draft.body)
print("-" * 80)

session.close()
engine.dispose()
# Remove temp SQLite database
if os.path.exists("./dev_quick_test.db"):
    os.remove("./dev_quick_test.db")

print("\nSUCCESS: End-to-end pipeline tested in ~1.5 seconds!")
