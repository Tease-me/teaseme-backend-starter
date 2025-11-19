"""add influencer_gpt_agent_id

Revision ID: a765e8fa21eb
Revises: ae0dbe1bf126
Create Date: 2025-11-07 11:13:29.891839

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a765e8fa21eb'
down_revision: Union[str, Sequence[str], None] = 'ae0dbe1bf126'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'influencers',
        sa.Column('influencer_gpt_agent_id', sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('influencers', 'influencer_gpt_agent_id')
