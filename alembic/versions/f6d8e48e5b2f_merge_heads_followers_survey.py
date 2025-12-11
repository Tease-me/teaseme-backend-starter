"""Merge heads: followers table + survey token on pre_influencers.

Revision ID: f6d8e48e5b2f
Revises: 1b0c2f2c7f01, c9aeb0f7695c
Create Date: 2025-12-11 00:00:00.000000
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "f6d8e48e5b2f"
down_revision: Union[str, Sequence[str], None] = ("1b0c2f2c7f01", "c9aeb0f7695c")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op merge revision."""
    pass


def downgrade() -> None:
    """No-op merge revision."""
    pass
