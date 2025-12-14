"""merge heads

Revision ID: d45e995bf92d
Revises: ab542e9c3f26, d3267d470fc5
Create Date: 2025-12-15 08:33:25.028873

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd45e995bf92d'
down_revision: Union[str, Sequence[str], None] = ('ab542e9c3f26', 'd3267d470fc5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
