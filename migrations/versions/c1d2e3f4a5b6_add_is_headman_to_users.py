"""add is_headman to users

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-11-17 13:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column() -> bool:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    return "is_headman" in columns


def upgrade() -> None:
    # Dev mode creates tables from metadata at app startup, so the column may
    # already exist before the migration ever runs.
    if _has_column():
        return
    op.add_column(
        "users",
        sa.Column("is_headman", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    if _has_column():
        op.drop_column("users", "is_headman")
