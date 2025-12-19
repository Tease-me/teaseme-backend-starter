"""merge multiple heads

Revision ID: aa0d5e5cfb88
Revises: 3f0b16e442ac, e8c61cce384b
Create Date: 2025-01-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = "aa0d5e5cfb88"
down_revision: Union[str, Sequence[str], None] = (
    "3f0b16e442ac",
    "e8c61cce384b",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge revision; no schema changes."""
    pass


def downgrade() -> None:
    """Downgrade merge; no schema changes."""
    pass
