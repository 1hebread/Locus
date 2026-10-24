"""share schedule and homework, add per-user completions

Revision ID: 4f2c9a7b1d3e
Revises: 2029cefa06c9
Create Date: 2026-10-23 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4f2c9a7b1d3e"
down_revision: Union[str, Sequence[str], None] = "2029cefa06c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CANONICAL_USER = (
    "COALESCE("
    "(SELECT MIN(id) FROM users WHERE is_admin), "
    "(SELECT MIN(id) FROM users)"
    ")"
)


def upgrade() -> None:
    """Make subjects/lessons/homework shared and keep status per user."""
    op.create_table(
        "homework_completions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("homework_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["homework_id"], ["homeworks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "homework_id",
            "user_id",
            name="uq_homework_completions_homework_user",
        ),
    )
    op.create_index(
        op.f("ix_homework_completions_homework_id"),
        "homework_completions",
        ["homework_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_homework_completions_user_id"),
        "homework_completions",
        ["user_id"],
        unique=False,
    )

    # Preserve statuses from the old per-user homework rows.
    op.execute(
        """
        INSERT INTO homework_completions (homework_id, user_id, status, updated_at)
        SELECT id, user_id, status, updated_at FROM homeworks
        """
    )

    # Keep the first admin's diary as the shared one. This database is
    # single-user today; the cleanup prevents duplicate shared rows for older
    # multi-user installs.
    op.execute(f"DELETE FROM homeworks WHERE user_id <> {CANONICAL_USER}")
    op.execute(
        "DELETE FROM homework_completions "
        "WHERE homework_id NOT IN (SELECT id FROM homeworks)"
    )
    op.execute(f"DELETE FROM lessons WHERE user_id <> {CANONICAL_USER}")
    op.execute(f"DELETE FROM subjects WHERE user_id <> {CANONICAL_USER}")

    op.drop_index("ix_homeworks_user_id", table_name="homeworks")
    op.drop_index("ix_homeworks_status", table_name="homeworks")
    op.drop_index("ix_lessons_user_id", table_name="lessons")
    op.drop_index("ix_subjects_user_id", table_name="subjects")

    with op.batch_alter_table("homeworks", schema=None) as batch_op:
        batch_op.drop_column("user_id")
        batch_op.drop_column("status")

    with op.batch_alter_table("lessons", schema=None) as batch_op:
        batch_op.drop_column("user_id")

    with op.batch_alter_table("subjects", schema=None) as batch_op:
        batch_op.drop_column("user_id")


def downgrade() -> None:
    """Restore ownership columns and a single shared status column."""
    with op.batch_alter_table("subjects", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_subjects_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("lessons", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_lessons_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("homeworks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="TODO",
            )
        )
        batch_op.create_foreign_key(
            "fk_homeworks_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.execute(f"UPDATE subjects SET user_id = {CANONICAL_USER}")
    op.execute(f"UPDATE lessons SET user_id = {CANONICAL_USER}")
    op.execute(f"UPDATE homeworks SET user_id = {CANONICAL_USER}")
    op.execute(
        f"""
        UPDATE homeworks
        SET status = COALESCE(
            (
                SELECT status FROM homework_completions
                WHERE homework_id = homeworks.id
                  AND user_id = {CANONICAL_USER}
            ),
            'TODO'
        )
        """
    )

    op.create_index("ix_subjects_user_id", "subjects", ["user_id"], unique=False)
    op.create_index("ix_lessons_user_id", "lessons", ["user_id"], unique=False)
    op.create_index("ix_homeworks_user_id", "homeworks", ["user_id"], unique=False)
    op.create_index("ix_homeworks_status", "homeworks", ["status"], unique=False)

    op.drop_table("homework_completions")
