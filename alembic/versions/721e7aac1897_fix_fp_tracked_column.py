"""fix fp_tracked column

Revision ID: 721e7aac1897
Revises: bcbc434b73e8
Create Date: 2025-12-20 10:25:53.365602

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '721e7aac1897'
down_revision: Union[str, Sequence[str], None] = 'bcbc434b73e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None





def upgrade() -> None:
    # Safe even if you run it twice
    op.execute("ALTER TABLE paypal_topups ADD COLUMN IF NOT EXISTS fp_tracked boolean NOT NULL DEFAULT false;")
    # Optional: remove default after backfill so app controls it
    op.execute("ALTER TABLE paypal_topups ALTER COLUMN fp_tracked DROP DEFAULT;")


def downgrade() -> None:
    # Safe even if column is missing
    op.execute("ALTER TABLE paypal_topups DROP COLUMN IF EXISTS fp_tracked;")