"""switch users to username and admin

Revision ID: 2029cefa06c9
Revises: e734e3391fa0
Create Date: 2026-10-23 18:33:00.335901

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2029cefa06c9'
down_revision: Union[str, Sequence[str], None] = 'e734e3391fa0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename email to username, add admin flag, promote first user."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false())
        )

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(op.f('ix_users_email'))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column(
            'email',
            new_column_name='username',
            existing_type=sa.String(length=255),
            existing_nullable=False,
        )

    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.execute("UPDATE users SET is_admin = TRUE WHERE id = (SELECT MIN(id) FROM users)")


def downgrade() -> None:
    """Restore email column and remove admin flag."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(op.f('ix_users_username'))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column(
            'username',
            new_column_name='email',
            existing_type=sa.String(length=255),
            existing_nullable=False,
        )

    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('is_admin')
