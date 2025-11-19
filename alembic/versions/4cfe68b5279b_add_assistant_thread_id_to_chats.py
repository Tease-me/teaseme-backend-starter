"""add assistant thread id to chats

Revision ID: 4cfe68b5279b
Revises: a765e8fa21eb
Create Date: 2025-11-07 15:45:04.062955

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4cfe68b5279b'
down_revision: Union[str, Sequence[str], None] = 'a765e8fa21eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'chats',
        sa.Column('assistant_thread_id', sa.String(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chats', 'assistant_thread_id')
