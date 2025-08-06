"""add users fields

Revision ID: 0a768f8a864a
Revises: 3de6b853327e
Create Date: 2025-07-24 12:58:57.535244

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a768f8a864a'
down_revision: Union[str, Sequence[str], None] = '3de6b853327e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('full_name', sa.String(), nullable=True))
    op.add_column('users', sa.Column('date_of_birth', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('gender', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('users', 'full_name')
    op.drop_column('users', 'date_of_birth')
    op.drop_column('users', 'gender')