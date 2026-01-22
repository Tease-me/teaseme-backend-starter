"""merge heads

Revision ID: e041cca691d0
Revises: 6f95a8a89f35, b1c2d3e4f5a6
Create Date: 2026-01-22 23:24:56.300182

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e041cca691d0'
down_revision: Union[str, Sequence[str], None] = ('6f95a8a89f35', 'b1c2d3e4f5a6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
