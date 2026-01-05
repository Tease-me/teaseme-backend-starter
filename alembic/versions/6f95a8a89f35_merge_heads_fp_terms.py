"""Merge the two latest heads (fp fields + terms agreement).

Revision ID: 6f95a8a89f35
Revises: 05e2844dfdc9, fdd8efd44855
Create Date: 2025-01-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6f95a8a89f35"
down_revision: Union[str, Sequence[str], None] = ("05e2844dfdc9", "fdd8efd44855")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op merge revision to unify heads."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
