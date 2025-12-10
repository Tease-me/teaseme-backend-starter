"""add password to pre_influencers

Revision ID: 1f215bd507f8
Revises: 77e47424f031
Create Date: 2025-12-09 09:29:20.854114

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1f215bd507f8'
down_revision: Union[str, Sequence[str], None] = '77e47424f031'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns("pre_influencers")}
    if "password" not in existing_cols:
        op.add_column('pre_influencers', sa.Column('password', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns("pre_influencers")}
    if "password" in existing_cols:
        op.drop_column('pre_influencers', 'password')
