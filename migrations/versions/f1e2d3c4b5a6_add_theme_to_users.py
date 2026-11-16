"""add theme to users

Revision ID: f1e2d3c4b5a6
Revises: d1e2f3a4b5c6
Create Date: 2026-11-16 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f1e2d3c4b5a6"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column() -> bool:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    return "theme" in columns


def upgrade() -> None:
    # Dev mode creates tables from metadata at app startup, so the column may
    # already exist before the migration ever runs.
    if _has_column():
        return
    op.add_column(
        "users",
        sa.Column("theme", sa.String(length=20), nullable=False, server_default="system"),
    )


def downgrade() -> None:
    if _has_column():
        op.drop_column("users", "theme")
