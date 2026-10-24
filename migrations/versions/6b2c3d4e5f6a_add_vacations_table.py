"""add vacations table

Revision ID: 6b2c3d4e5f6a
Revises: 5a1b2c3d4e5f
Create Date: 2026-10-24 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6b2c3d4e5f6a"
down_revision: Union[str, Sequence[str], None] = "5a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vacations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vacations_id"), "vacations", ["id"], unique=False)
    op.create_index(op.f("ix_vacations_start_date"), "vacations", ["start_date"], unique=False)
    op.create_index(op.f("ix_vacations_end_date"), "vacations", ["end_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_vacations_end_date"), table_name="vacations")
    op.drop_index(op.f("ix_vacations_start_date"), table_name="vacations")
    op.drop_index(op.f("ix_vacations_id"), table_name="vacations")
    op.drop_table("vacations")
