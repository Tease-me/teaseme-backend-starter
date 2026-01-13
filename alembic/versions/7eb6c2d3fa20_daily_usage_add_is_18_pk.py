"""daily_usage add is_18 pk

Revision ID: 7eb6c2d3fa20
Revises: 19d0ec0d3061
Create Date: 2026-01-09 07:36:47.341651

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7eb6c2d3fa20'
down_revision: Union[str, Sequence[str], None] = '19d0ec0d3061'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    # 1) add column (default false for existing rows)
    op.execute(
        "ALTER TABLE daily_usage "
        "ADD COLUMN IF NOT EXISTS is_18 BOOLEAN NOT NULL DEFAULT false"
    )

    # 2) drop old PK (usually daily_usage_pkey)
    op.execute("ALTER TABLE daily_usage DROP CONSTRAINT IF EXISTS daily_usage_pkey")

    # 3) create new PK including is_18
    op.create_primary_key("daily_usage_pkey", "daily_usage", ["user_id", "date", "is_18"])

    # 4) optional: remove server default (keep if you want DB default)
    op.alter_column("daily_usage", "is_18", server_default=None)


def downgrade() -> None:
    # reverse the PK back
    op.execute("ALTER TABLE daily_usage DROP CONSTRAINT IF EXISTS daily_usage_pkey")
    op.create_primary_key("daily_usage_pkey", "daily_usage", ["user_id", "date"])

    op.execute("ALTER TABLE daily_usage DROP COLUMN IF EXISTS is_18")
    
