"""add students and attendance records

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-11-24 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # Development runs Base.metadata.create_all on startup, so tables may
    # already exist before the migration ever runs.
    if not inspector.has_table("students"):
        op.create_table(
            "students",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("full_name", sa.String(length=255), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_students_id"), "students", ["id"], unique=False)
        op.create_index(
            op.f("ix_students_full_name"),
            "students",
            ["full_name"],
            unique=True,
        )

    if not inspector.has_table("attendance_records"):
        op.create_table(
            "attendance_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("student_id", sa.Integer(), nullable=False),
            sa.Column("attendance_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("marked_by_id", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["marked_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "student_id",
                "attendance_date",
                name="uq_attendance_records_student_date",
            ),
        )
        op.create_index(
            op.f("ix_attendance_records_id"),
            "attendance_records",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_attendance_records_student_id"),
            "attendance_records",
            ["student_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_attendance_records_attendance_date"),
            "attendance_records",
            ["attendance_date"],
            unique=False,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("attendance_records"):
        op.drop_table("attendance_records")
    if inspector.has_table("students"):
        op.drop_table("students")
