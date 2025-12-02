"""Merge alembic heads into single branch.

Revision ID: e5f8f202b6eb
Revises: 2475ffd4422c, 4cfe68b5279b
Create Date: 2025-02-15 00:00:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "e5f8f202b6eb"
down_revision: Union[str, Sequence[str], None] = ("2475ffd4422c", "4cfe68b5279b")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op merge revision."""
    pass


def downgrade() -> None:
    """No schema changes to reverse."""
    pass

