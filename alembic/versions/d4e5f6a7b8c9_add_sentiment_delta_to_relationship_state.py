"""add_sentiment_delta_to_relationship_state

Revision ID: d4e5f6a7b8c9
Revises: 3594509c9947
Create Date: 2026-02-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = '3594509c9947'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add sentiment_delta column with default 0.0
    op.add_column('relationship_state', 
        sa.Column('sentiment_delta', sa.Float(), nullable=False, server_default='0.0')
    )
    
    # Remove server default after adding the column
    op.alter_column('relationship_state', 'sentiment_delta', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop the sentiment_delta column
    op.drop_column('relationship_state', 'sentiment_delta')
