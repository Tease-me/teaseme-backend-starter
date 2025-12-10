"""add pre_influencers survey

Revision ID: 40e74fdc8b43
Revises: 1f215bd507f8
Create Date: 2025-12-09 23:30:36.415487

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40e74fdc8b43'
down_revision: Union[str, Sequence[str], None] = '1f215bd507f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('pre_influencers', sa.Column('survey_token', sa.String(), nullable=True))
    op.add_column('pre_influencers', sa.Column('survey_answers', sa.JSON(), nullable=True))
    op.add_column(
        'pre_influencers',
        sa.Column('survey_step', sa.Integer(), nullable=False, server_default="0"),
    )


def upgrade():
    op.add_column(
        "pre_influencers",
        sa.Column("survey_step", sa.Integer(), nullable=True, server_default="0"),
    )
    op.execute("UPDATE pre_influencers SET survey_step = 0 WHERE survey_step IS NULL")
    op.alter_column(
        "pre_influencers",
        "survey_step",
        existing_type=sa.Integer(),
        nullable=False,
    )