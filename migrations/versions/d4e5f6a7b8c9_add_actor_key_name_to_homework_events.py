"""add actor key name to homework events

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-29 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column() -> bool:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("homework_events")}
    return "actor_key_name" in columns


def upgrade() -> None:
    # Dev mode creates tables from metadata at app startup, so the column may
    # already exist before the migration ever runs.
    if _has_column():
        return
    op.add_column(
        "homework_events",
        sa.Column("actor_key_name", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    if _has_column():
        op.drop_column("homework_events", "actor_key_name")
