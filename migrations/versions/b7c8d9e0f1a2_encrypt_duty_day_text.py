"""encrypt duty day text

Revision ID: b7c8d9e0f1a2
Revises: f1e2d3c4b5a6
Create Date: 2026-11-17 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import column, table

from locus.crypto import decrypt_string, encrypt_string


# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "f1e2d3c4b5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Blank rosters are stored as NULL, so the column has to allow it.
    with op.batch_alter_table("duty_days", schema=None) as batch_op:
        batch_op.alter_column("text", existing_type=sa.Text(), nullable=True)

    bind = op.get_bind()
    duty_days = table(
        "duty_days",
        column("day_of_week", sa.Integer),
        column("text", sa.Text),
    )
    rows = bind.execute(sa.select(duty_days.c.day_of_week, duty_days.c.text)).fetchall()
    for day_of_week, text in rows:
        if text and not text.strip().startswith("gAAAAA"):
            bind.execute(
                sa.update(duty_days)
                .where(duty_days.c.day_of_week == day_of_week)
                .values(text=encrypt_string(text))
            )


def downgrade() -> None:
    bind = op.get_bind()
    duty_days = table(
        "duty_days",
        column("day_of_week", sa.Integer),
        column("text", sa.Text),
    )
    rows = bind.execute(sa.select(duty_days.c.day_of_week, duty_days.c.text)).fetchall()
    for day_of_week, text in rows:
        if text is None:
            plaintext = ""
        elif text.strip().startswith("gAAAAA"):
            plaintext = decrypt_string(text)
            if plaintext is None:
                raise RuntimeError(
                    f"Cannot decrypt duty text for day {day_of_week} during downgrade: "
                    "invalid encryption key. Aborting downgrade to prevent silent data loss."
                )
        else:
            continue
        bind.execute(
            sa.update(duty_days)
            .where(duty_days.c.day_of_week == day_of_week)
            .values(text=plaintext)
        )

    with op.batch_alter_table("duty_days", schema=None) as batch_op:
        batch_op.alter_column("text", existing_type=sa.Text(), nullable=False)
