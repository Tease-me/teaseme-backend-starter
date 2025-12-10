"""merge_heads

Revision ID: 167f995bc156
Revises: f57926b8f1d8, f6d8e48e5b2f
Create Date: 2025-12-11 08:20:37.875659

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '167f995bc156'
down_revision: Union[str, Sequence[str], None] = ('f57926b8f1d8', 'f6d8e48e5b2f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
