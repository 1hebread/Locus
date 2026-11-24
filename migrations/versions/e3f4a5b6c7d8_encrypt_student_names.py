"""encrypt student full names

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-11-24 13:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import column, table

from locus.crypto import decrypt_string, encrypt_string


# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_index(name: str) -> bool:
    return any(
        index["name"] == name
        for index in sa.inspect(op.get_bind()).get_indexes("students")
    )


def upgrade() -> None:
    # Ciphertext is longer than the original VARCHAR(255) and is
    # non-deterministic, so the unique index cannot be kept.
    if _has_index("ix_students_full_name"):
        op.drop_index("ix_students_full_name", table_name="students")

    columns = {
        column_info["name"]: column_info
        for column_info in sa.inspect(op.get_bind()).get_columns("students")
    }
    if not isinstance(columns["full_name"]["type"], sa.Text):
        with op.batch_alter_table("students", schema=None) as batch_op:
            batch_op.alter_column(
                "full_name",
                existing_type=sa.String(length=255),
                type_=sa.Text(),
                existing_nullable=False,
            )

    bind = op.get_bind()
    students = table(
        "students",
        column("id", sa.Integer),
        column("full_name", sa.Text),
    )
    rows = bind.execute(sa.select(students.c.id, students.c.full_name)).fetchall()
    for student_id, full_name in rows:
        if full_name and not full_name.strip().startswith("gAAAAA"):
            bind.execute(
                sa.update(students)
                .where(students.c.id == student_id)
                .values(full_name=encrypt_string(full_name))
            )


def downgrade() -> None:
    bind = op.get_bind()
    students = table(
        "students",
        column("id", sa.Integer),
        column("full_name", sa.Text),
    )
    rows = bind.execute(sa.select(students.c.id, students.c.full_name)).fetchall()
    for student_id, full_name in rows:
        if full_name and full_name.strip().startswith("gAAAAA"):
            decrypted = decrypt_string(full_name)
            if decrypted is None:
                raise RuntimeError(
                    f"Cannot decrypt full_name for student ID {student_id} during "
                    "downgrade: invalid encryption key. Aborting downgrade to "
                    "prevent silent data loss."
                )
            bind.execute(
                sa.update(students)
                .where(students.c.id == student_id)
                .values(full_name=decrypted[:255])
            )

    with op.batch_alter_table("students", schema=None) as batch_op:
        batch_op.alter_column(
            "full_name",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=False,
        )

    if not _has_index("ix_students_full_name"):
        op.create_index(
            "ix_students_full_name",
            "students",
            ["full_name"],
            unique=True,
        )
