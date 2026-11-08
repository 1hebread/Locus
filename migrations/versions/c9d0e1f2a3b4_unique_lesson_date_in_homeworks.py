"""unique lesson and due date in homeworks

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-08 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_homeworks_lesson_due_date"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if INDEX_NAME in {ix["name"] for ix in inspector.get_indexes("homeworks")}:
        return

    # Legacy duplicates would block the index. Detach the older rows instead of
    # deleting them: the assignment and everyone's completion status survive as
    # unassigned homework, and the dashboard keeps the newest row (as it did).
    bind.execute(
        sa.text(
            """
            UPDATE homeworks SET lesson_id = NULL
            WHERE lesson_id IS NOT NULL
              AND id NOT IN (
                  SELECT MAX(id) FROM homeworks
                  WHERE lesson_id IS NOT NULL
                  GROUP BY lesson_id, due_date
              )
            """
        )
    )

    op.create_index(
        INDEX_NAME,
        "homeworks",
        ["lesson_id", "due_date"],
        unique=True,
        sqlite_where=sa.text("lesson_id IS NOT NULL"),
        postgresql_where=sa.text("lesson_id IS NOT NULL"),
    )


def downgrade() -> None:
    if INDEX_NAME in {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes("homeworks")}:
        op.drop_index(INDEX_NAME, table_name="homeworks")
