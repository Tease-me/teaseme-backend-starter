"""merge heads

Revision ID: 5ba9d755e52f
Revises: 2188ca984f3a, 23649145b822, 8860075a6b90
Create Date: 2026-01-12 02:18:10.474240

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ba9d755e52f'
down_revision: Union[str, Sequence[str], None] = ('2188ca984f3a', '23649145b822', '8860075a6b90')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
