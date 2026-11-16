"""add conversation management and automated follow-up execution tables

Revision ID: 0004_conversations_and_followups
Revises: 0003_outreach_mailboxes
Create Date: 2026-11-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_conversations_and_followups"
down_revision: Union[str, None] = "0003_outreach_mailboxes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add followup_sequence to campaigns
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.add_column(
            sa.Column("followup_sequence", sa.JSON(), nullable=True, server_default="{}")
        )

    # 2. Create conversations table
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("lead_id", sa.Uuid(as_uuid=True), sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("business_id", sa.Uuid(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recipient_email", sa.String(), nullable=False),
        sa.Column("sender_email", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("followup_status", sa.String(), nullable=False, server_default="idle"),
        sa.Column("followup_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.create_index("ix_conversations_lead_id", ["lead_id"], unique=False)
        batch_op.create_index("ix_conversations_campaign_id", ["campaign_id"], unique=False)
        batch_op.create_index("ix_conversations_recipient", ["recipient_email"], unique=False)
        batch_op.create_index("ix_conversations_status", ["status"], unique=False)
        batch_op.create_index("ix_conversations_last_msg", ["last_message_at"], unique=False)

    # 3. Create conversation_messages table
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("message_type", sa.String(), nullable=False),
        sa.Column("sender", sa.String(), nullable=False),
        sa.Column("recipient", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.String(), nullable=True),
        sa.Column("in_reply_to", sa.String(), nullable=True),
        sa.Column("references", sa.Text(), nullable=True),
        sa.Column("delivery_status", sa.String(), nullable=False, server_default="sent"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("conversation_messages") as batch_op:
        batch_op.create_index("ix_conv_msg_conversation_id", ["conversation_id"], unique=False)
        batch_op.create_index("ix_conv_msg_provider_msg_id", ["provider_message_id"], unique=False)
        batch_op.create_index("ix_conv_msg_in_reply_to", ["in_reply_to"], unique=False)
        batch_op.create_index("ix_conv_msg_created_at", ["created_at"], unique=False)

    # 4. Create followup_executions table
    op.create_table(
        "followup_executions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lead_id", sa.Uuid(as_uuid=True), sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sequence_step", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="scheduled"),
        sa.Column("stop_reason", sa.String(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("followup_executions") as batch_op:
        batch_op.create_index("ix_followup_conv_status", ["conversation_id", "status"], unique=False)
        batch_op.create_index("ix_followup_sched", ["scheduled_at"], unique=False)


def downgrade() -> None:
    op.drop_table("followup_executions")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.drop_column("followup_sequence")
