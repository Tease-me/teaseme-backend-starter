"""merge_heads_re_engagement

Revision ID: b1c2d3e4f5a6
Revises: 2a3b4c5d6e7f, ea7a1d780a7b
Create Date: 2025-02-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = (
    '2a3b4c5d6e7f',
    'ea7a1d780a7b',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
