"""add subject, version, and updated_at to message_drafts

Revision ID: 0005_add_draft_subject
Revises: 0004_conversations_and_followups
Create Date: 2026-11-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_add_draft_subject"
down_revision: Union[str, None] = "0004_conversations_and_followups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("message_drafts") as batch_op:
        batch_op.add_column(
            sa.Column("subject", sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("message_drafts") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("version")
        batch_op.drop_column("subject")
