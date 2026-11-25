"""rename ABSENT attendance status to TRUANT

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-11-25 17:32:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import column, table


# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rename_status(old_status: str, new_status: str) -> None:
    bind = op.get_bind()
    attendance_records = table(
        "attendance_records",
        column("status", sa.String(length=20)),
    )
    bind.execute(
        sa.update(attendance_records)
        .where(attendance_records.c.status == old_status)
        .values(status=new_status)
    )


def upgrade() -> None:
    _rename_status("ABSENT", "TRUANT")


def downgrade() -> None:
    _rename_status("TRUANT", "ABSENT")
