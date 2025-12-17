"""merge heads 30dff913e3ac and d45e995bf92d

Revision ID: 2a9b4f8e2b76
Revises: 30dff913e3ac, d45e995bf92d
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a9b4f8e2b76'
down_revision: Union[str, Sequence[str], None] = ('30dff913e3ac', 'd45e995bf92d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge heads."""
    pass


def downgrade() -> None:
    """Split heads."""
    pass
