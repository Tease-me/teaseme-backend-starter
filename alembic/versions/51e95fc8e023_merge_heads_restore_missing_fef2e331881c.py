"""merge heads (restore missing fef2e331881c)

Revision ID: 51e95fc8e023
Revises: 5ba9d755e52f, fef2e331881c
Create Date: 2026-01-12 02:26:43.327366

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '51e95fc8e023'
down_revision: Union[str, Sequence[str], None] = ('5ba9d755e52f', 'fef2e331881c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
