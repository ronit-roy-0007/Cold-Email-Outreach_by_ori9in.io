"""add approvals table

Revision ID: 0002_approvals
Revises: 0001_initial
Create Date: 2026-11-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_approvals"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("approvals")
