"""add name and type columns to system_prompts

Revision ID: a7b8c9d0e1f2
Revises: 2139b2e332d3
Create Date: 2026-01-27 13:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'ea2a1df4f0bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add name and type columns to system_prompts table."""
    # Add name column (nullable)
    op.add_column('system_prompts', sa.Column('name', sa.String(), nullable=True))
    
    # Add type column with default 'normal'
    op.add_column(
        'system_prompts',
        sa.Column('type', sa.String(), nullable=False, server_default='normal')
    )


def downgrade() -> None:
    """Remove name and type columns from system_prompts table."""
    op.drop_column('system_prompts', 'type')
    op.drop_column('system_prompts', 'name')
