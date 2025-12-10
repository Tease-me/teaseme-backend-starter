"""drop title column from influencers (if present)

Revision ID: 5f1e2c6c9a7b
Revises: ea7b0f6d2c1a
Create Date: 2025-02-18 01:35:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5f1e2c6c9a7b"
down_revision: Union[str, Sequence[str], None] = "ea7b0f6d2c1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Guarded drop in case the column still exists from older runs.
    op.execute("ALTER TABLE influencers DROP COLUMN IF EXISTS title")


def downgrade() -> None:
    op.add_column("influencers", sa.Column("title", sa.String(), nullable=True))
