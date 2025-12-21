"""add fp_tracked (final)

Revision ID: 4ba999b9c879
Revises: 721e7aac1897
Create Date: 2025-12-20 11:01:45.504250

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ba999b9c879'
down_revision: Union[str, Sequence[str], None] = '721e7aac1897'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE paypal_topups
        ADD COLUMN IF NOT EXISTS fp_tracked boolean NOT NULL DEFAULT false;
    """)
    op.execute("""
        ALTER TABLE paypal_topups
        ALTER COLUMN fp_tracked DROP DEFAULT;
    """)

def downgrade() -> None:
    op.execute("""
        ALTER TABLE paypal_topups
        DROP COLUMN IF EXISTS fp_tracked;
    """)
