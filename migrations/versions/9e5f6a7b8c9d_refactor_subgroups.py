"""refactor subgroups schema

Revision ID: 9e5f6a7b8c9d
Revises: 8d4e5f6a7b8c
Create Date: 2026-10-28 14:40:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "9e5f6a7b8c9d"
down_revision: Union[str, Sequence[str], None] = "8d4e5f6a7b8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
