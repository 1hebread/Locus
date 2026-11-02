"""add gender subgroups to users lessons homeworks

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-02 17:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("gender_subgroup", sa.String(length=20), nullable=True))

    with op.batch_alter_table("lessons") as batch_op:
        batch_op.alter_column(
            "subgroup",
            existing_type=sa.Integer(),
            type_=sa.String(length=20),
            existing_nullable=True,
        )

    with op.batch_alter_table("homeworks") as batch_op:
        batch_op.alter_column(
            "subgroup",
            existing_type=sa.Integer(),
            type_=sa.String(length=20),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("homeworks") as batch_op:
        batch_op.alter_column(
            "subgroup",
            existing_type=sa.String(length=20),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using="CASE WHEN subgroup IN ('1', '2') THEN subgroup::integer ELSE NULL END",
        )

    with op.batch_alter_table("lessons") as batch_op:
        batch_op.alter_column(
            "subgroup",
            existing_type=sa.String(length=20),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using="CASE WHEN subgroup IN ('1', '2') THEN subgroup::integer ELSE NULL END",
        )

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("gender_subgroup")
