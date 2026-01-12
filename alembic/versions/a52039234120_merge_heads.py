"""merge heads

Revision ID: a52039234120
Revises: 51e95fc8e023, 6f95a8a89f35
Create Date: 2026-01-12 02:39:23.455474

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a52039234120'
down_revision: Union[str, Sequence[str], None] = ('51e95fc8e023', '6f95a8a89f35')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
