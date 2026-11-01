"""alter push subscriptions endpoint length

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-01 16:05:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("push_subscriptions"):
        return

    with op.batch_alter_table("push_subscriptions") as batch_op:
        batch_op.alter_column(
            "endpoint",
            existing_type=sa.String(length=500),
            type_=sa.String(length=1024),
            nullable=False,
        )
        batch_op.alter_column(
            "p256dh",
            existing_type=sa.String(length=200),
            type_=sa.String(length=500),
            nullable=False,
        )
        batch_op.alter_column(
            "auth",
            existing_type=sa.String(length=100),
            type_=sa.String(length=200),
            nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("push_subscriptions"):
        return

    with op.batch_alter_table("push_subscriptions") as batch_op:
        batch_op.alter_column(
            "endpoint",
            existing_type=sa.String(length=1024),
            type_=sa.String(length=500),
            nullable=False,
        )
        batch_op.alter_column(
            "p256dh",
            existing_type=sa.String(length=500),
            type_=sa.String(length=200),
            nullable=False,
        )
        batch_op.alter_column(
            "auth",
            existing_type=sa.String(length=200),
            type_=sa.String(length=100),
            nullable=False,
        )
