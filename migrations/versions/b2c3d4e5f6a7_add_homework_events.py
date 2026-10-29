"""add homework events

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-29 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Dev mode creates tables from metadata at app startup, so the table may
    # already exist before the migration ever runs.
    if sa.inspect(op.get_bind()).has_table("homework_events"):
        return

    op.create_table(
        "homework_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("homework_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_username", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["homework_id"], ["homeworks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_homework_events_id"), "homework_events", ["id"], unique=False)
    op.create_index(
        op.f("ix_homework_events_homework_id"),
        "homework_events",
        ["homework_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_homework_events_created_at"),
        "homework_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_homework_events_created_at"), table_name="homework_events")
    op.drop_index(op.f("ix_homework_events_homework_id"), table_name="homework_events")
    op.drop_index(op.f("ix_homework_events_id"), table_name="homework_events")
    op.drop_table("homework_events")
