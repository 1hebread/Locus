"""add duty days table

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-11-09 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Development runs Base.metadata.create_all on startup, so the table may already exist.
    if sa.inspect(op.get_bind()).has_table("duty_days"):
        return

    op.create_table(
        "duty_days",
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("day_of_week"),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("duty_days"):
        op.drop_table("duty_days")
