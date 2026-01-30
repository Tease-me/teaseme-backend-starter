"""merge_heads

Revision ID: 3594509c9947
Revises: bcf69c32ef01, f3d4e5a6b7c8
Create Date: 2026-01-30 10:29:32.376119

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3594509c9947'
down_revision: Union[str, Sequence[str], None] = ('bcf69c32ef01', 'f3d4e5a6b7c8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
