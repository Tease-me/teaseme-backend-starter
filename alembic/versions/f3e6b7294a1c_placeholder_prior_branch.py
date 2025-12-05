"""placeholder to bridge historical revision f3e6b7294a1c

Revision ID: f3e6b7294a1c
Revises: 8860075a6b90
Create Date: 2025-02-18 00:25:00.000000
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "f3e6b7294a1c"
down_revision: Union[str, Sequence[str], None] = "8860075a6b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op placeholder to align DB state."""
    pass


def downgrade() -> None:
    """No-op placeholder to align DB state."""
    pass
