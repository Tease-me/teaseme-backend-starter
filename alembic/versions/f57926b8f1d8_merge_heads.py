"""merge heads

Revision ID: f57926b8f1d8
Revises: 43e630570a46, c9aeb0f7695c
Create Date: 2025-12-10 15:21:32.863561

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f57926b8f1d8'
down_revision: Union[str, Sequence[str], None] = ('43e630570a46', 'c9aeb0f7695c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
