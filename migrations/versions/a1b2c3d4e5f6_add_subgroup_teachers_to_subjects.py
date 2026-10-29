"""add subgroup teachers to subjects

Revision ID: a1b2c3d4e5f6
Revises: 9e5f6a7b8c9d
Create Date: 2026-10-28 15:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "9e5f6a7b8c9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("subjects", schema=None) as batch_op:
        batch_op.add_column(sa.Column("teacher2_name", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("teacher2_phone", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("room2", sa.String(length=50), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("subjects", schema=None) as batch_op:
        batch_op.drop_column("room2")
        batch_op.drop_column("teacher2_phone")
        batch_op.drop_column("teacher2_name")
