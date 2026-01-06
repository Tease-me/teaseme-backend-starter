"""add created_at to influencer_credit_transactions

Revision ID: 60badaca636b
Revises: 3c132e441043
Create Date: 2026-01-05 23:19:02.259883

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '60badaca636b'
down_revision: Union[str, Sequence[str], None] = '3c132e441043'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    op.execute("""
        ALTER TABLE influencer_credit_transactions
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
    """)
    op.execute("""
        ALTER TABLE influencer_credit_transactions
        ALTER COLUMN created_at DROP DEFAULT;
    """)

def downgrade():
    op.drop_column("influencer_credit_transactions", "created_at")
