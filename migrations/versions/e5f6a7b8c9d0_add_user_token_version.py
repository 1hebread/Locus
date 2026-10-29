"""add user token version

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-29 19:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column() -> bool:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    return "token_version" in columns


def upgrade() -> None:
    # Dev mode creates tables from metadata at app startup, so the column may
    # already exist before the migration ever runs.
    if _has_column():
        return
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    if _has_column():
        op.drop_column("users", "token_version")
