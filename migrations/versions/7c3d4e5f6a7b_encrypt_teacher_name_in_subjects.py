"""encrypt teacher_name in subjects

Revision ID: 7c3d4e5f6a7b
Revises: 6b2c3d4e5f6a
Create Date: 2026-10-24 20:47:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import column, table

from locus.crypto import decrypt_string, encrypt_string


# revision identifiers, used by Alembic.
revision: str = "7c3d4e5f6a7b"
down_revision: Union[str, Sequence[str], None] = "6b2c3d4e5f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("subjects", schema=None) as batch_op:
        batch_op.alter_column(
            "teacher_name",
            existing_type=sa.String(length=120),
            type_=sa.Text(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "teacher_phone",
            existing_type=sa.String(length=512),
            type_=sa.Text(),
            existing_nullable=True,
        )

    bind = op.get_bind()
    subjects_table = table(
        "subjects",
        column("id", sa.Integer),
        column("teacher_name", sa.Text),
    )
    rows = bind.execute(sa.select(subjects_table.c.id, subjects_table.c.teacher_name)).fetchall()
    for row_id, teacher_name in rows:
        if teacher_name and not teacher_name.strip().startswith("gAAAAA"):
            encrypted = encrypt_string(teacher_name)
            bind.execute(
                sa.update(subjects_table)
                .where(subjects_table.c.id == row_id)
                .values(teacher_name=encrypted)
            )


def downgrade() -> None:
    bind = op.get_bind()
    subjects_table = table(
        "subjects",
        column("id", sa.Integer),
        column("teacher_name", sa.Text),
    )
    rows = bind.execute(sa.select(subjects_table.c.id, subjects_table.c.teacher_name)).fetchall()
    for row_id, teacher_name in rows:
        if teacher_name and teacher_name.strip().startswith("gAAAAA"):
            decrypted = decrypt_string(teacher_name)
            if decrypted is None:
                raise RuntimeError(
                    f"Cannot decrypt teacher_name for subject ID {row_id} during downgrade: "
                    "invalid encryption key. Aborting downgrade to prevent silent data loss."
                )
            bind.execute(
                sa.update(subjects_table)
                .where(subjects_table.c.id == row_id)
                .values(teacher_name=decrypted[:120])
            )

    with op.batch_alter_table("subjects", schema=None) as batch_op:
        batch_op.alter_column(
            "teacher_name",
            existing_type=sa.Text(),
            type_=sa.String(length=120),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "teacher_phone",
            existing_type=sa.Text(),
            type_=sa.String(length=512),
            existing_nullable=True,
        )
