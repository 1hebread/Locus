"""add encrypted teacher_phone to subjects

Revision ID: 5a1b2c3d4e5f
Revises: 4f2c9a7b1d3e
Create Date: 2026-10-24 14:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5a1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "4f2c9a7b1d3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subjects", sa.Column("teacher_phone", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("subjects", "teacher_phone")
