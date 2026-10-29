"""add subgroup to users lessons homeworks

Revision ID: 8d4e5f6a7b8c
Revises: 7c3d4e5f6a7b
Create Date: 2026-10-28 13:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8d4e5f6a7b8c"
down_revision: Union[str, Sequence[str], None] = "7c3d4e5f6a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("subgroup", sa.Integer(), nullable=True))

    with op.batch_alter_table("lessons", schema=None) as batch_op:
        batch_op.add_column(sa.Column("subgroup", sa.Integer(), nullable=True))

    with op.batch_alter_table("homeworks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("subgroup", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("homeworks", schema=None) as batch_op:
        batch_op.drop_column("subgroup")

    with op.batch_alter_table("lessons", schema=None) as batch_op:
        batch_op.drop_column("subgroup")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("subgroup")
