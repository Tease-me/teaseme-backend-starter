"""merge heads airwallex and subscriptions

Revision ID: d1a9f1c2b3e4
Revises: 3c9b1b8a2c1a, 6b7c9f96c1c2
Create Date: 2025-12-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d1a9f1c2b3e4"
down_revision: Union[str, Sequence[str], None] = ("3c9b1b8a2c1a", "6b7c9f96c1c2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge-only revision (no-op)."""
    pass


def downgrade() -> None:
    """Merge-only revision (no-op)."""
    pass

