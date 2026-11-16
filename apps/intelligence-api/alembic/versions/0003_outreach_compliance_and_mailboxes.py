"""add outreach compliance and mailbox rotation tables and indexes

Revision ID: 0003_outreach_compliance_and_mailboxes
Revises: 0002_approvals
Create Date: 2026-11-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_outreach_compliance_and_mailboxes"
down_revision: Union[str, None] = "0002_approvals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add extra columns to campaigns
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.add_column(sa.Column("target_sent_emails", sa.Integer(), nullable=True, server_default="50"))
        batch_op.add_column(sa.Column("total_sent_emails", sa.Integer(), nullable=True, server_default="0"))
        batch_op.add_column(sa.Column("sub_campaign_index", sa.Integer(), nullable=True, server_default="1"))
        batch_op.add_column(sa.Column("is_auto_mode", sa.Boolean(), nullable=True, server_default="0"))
        batch_op.add_column(sa.Column("is_exhausted", sa.Boolean(), nullable=True, server_default="0"))
        batch_op.add_column(sa.Column("radius_expanded", sa.Boolean(), nullable=True, server_default="0"))
        batch_op.add_column(sa.Column("expanded_locations", sa.JSON(), nullable=True, server_default="[]"))

    # 2. Add indexes to existing businesses table
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.create_index("ix_businesses_website", ["website"], unique=False)
        batch_op.create_index("ix_businesses_place_id", ["place_id"], unique=False)
        batch_op.create_index("ix_businesses_email", ["email"], unique=False)

    # 3. Add indexes to existing leads table
    with op.batch_alter_table("leads") as batch_op:
        batch_op.create_index("ix_leads_campaign_status", ["campaign_id", "outreach_status"], unique=False)
        batch_op.create_index("ix_leads_score", ["overall_score"], unique=False)

    # 4. Operator Profiles
    op.create_table(
        "operator_profiles",
        sa.Column("user_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("sender_name", sa.String(), nullable=False),
        sa.Column("agency_name", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )

    # 5. Outbound Messages
    op.create_table(
        "outbound_messages",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("recipient_email", sa.String(), nullable=False),
        sa.Column("sender_email", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("outbound_messages") as batch_op:
        batch_op.create_index("ix_outbound_messages_recipient_email", ["recipient_email"], unique=False)
        batch_op.create_index("ix_outbound_camp_status", ["campaign_id", "status"], unique=False)
        batch_op.create_index("ix_outbound_sender", ["sender_email"], unique=False)
        batch_op.create_index("ix_outbound_dispatched_at", ["dispatched_at"], unique=False)

    # 6. Suppression List
    op.create_table(
        "suppression_list",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    with op.batch_alter_table("suppression_list") as batch_op:
        batch_op.create_index("ix_suppression_list_email", ["email"], unique=True)

    # 7. Daily Dispatch Quotas
    op.create_table(
        "daily_dispatch_quotas",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("sender_mailbox", sa.String(), nullable=False),
        sa.Column("dispatch_date", sa.String(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("daily_dispatch_quotas") as batch_op:
        batch_op.create_index("ix_daily_dispatch_quotas_sender_mailbox", ["sender_mailbox"], unique=False)
        batch_op.create_index("ix_daily_dispatch_quotas_dispatch_date", ["dispatch_date"], unique=False)
        batch_op.create_index("ix_daily_quotas_sender_date", ["sender_mailbox", "dispatch_date"], unique=False)

    # 8. Mailbox Accounts
    op.create_table(
        "mailbox_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password", sa.String(), nullable=False),
        sa.Column("sender_name", sa.String(), nullable=False, server_default="Roy"),
        sa.Column("daily_limit", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    with op.batch_alter_table("mailbox_accounts") as batch_op:
        batch_op.create_index("ix_mailbox_accounts_email", ["email"], unique=True)

    # 9. Campaign Leftover Leads
    op.create_table(
        "campaign_leftover_leads",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("niche", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("is_consumed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("consumed_by_campaign_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["consumed_by_campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("campaign_leftover_leads") as batch_op:
        batch_op.create_index("ix_leftovers_niche_loc_avail", ["niche", "location", "is_consumed"], unique=False)


def downgrade() -> None:
    op.drop_table("campaign_leftover_leads")
    op.drop_table("mailbox_accounts")
    op.drop_table("daily_dispatch_quotas")
    op.drop_table("suppression_list")
    op.drop_table("outbound_messages")
    op.drop_table("operator_profiles")
    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_index("ix_leads_score")
        batch_op.drop_index("ix_leads_campaign_status")
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.drop_index("ix_businesses_email")
        batch_op.drop_index("ix_businesses_place_id")
        batch_op.drop_index("ix_businesses_website")
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.drop_column("expanded_locations")
        batch_op.drop_column("radius_expanded")
        batch_op.drop_column("is_exhausted")
        batch_op.drop_column("is_auto_mode")
        batch_op.drop_column("sub_campaign_index")
        batch_op.drop_column("total_sent_emails")
        batch_op.drop_column("target_sent_emails")
