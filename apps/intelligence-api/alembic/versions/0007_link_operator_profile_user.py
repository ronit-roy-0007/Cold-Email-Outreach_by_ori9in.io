"""link operator_profiles to operator_users

Revision ID: 0007_link_operator_profile_user
Revises: 0006_operator_auth
Create Date: 2026-11-17

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0007_link_operator_profile_user"
down_revision: Union[str, None] = "0006_operator_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add operator_user_id column to operator_profiles table
    with op.batch_alter_table("operator_profiles") as batch_op:
        batch_op.add_column(sa.Column("operator_user_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_operator_profiles_operator_user",
            "operator_users",
            ["operator_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("operator_profiles") as batch_op:
        batch_op.drop_constraint("fk_operator_profiles_operator_user", type_="foreignkey")
        batch_op.drop_column("operator_user_id")
