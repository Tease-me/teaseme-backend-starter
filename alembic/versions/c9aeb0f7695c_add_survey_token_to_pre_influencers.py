"""add survey_token to pre_influencers

Revision ID: c9aeb0f7695c
Revises: 40e74fdc8b43
Create Date: 2025-12-09 23:51:16.966161

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9aeb0f7695c'
down_revision: Union[str, Sequence[str], None] = '40e74fdc8b43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('pre_influencers', sa.Column('survey_token', sa.String(), nullable=True))
    op.add_column('pre_influencers', sa.Column('survey_answers', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    pass