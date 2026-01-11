"""add is_18 flags for subscriptions wallets daily_usage

Revision ID: 19d0ec0d3061
Revises: 2056171fd5ef
Create Date: 2026-01-09 07:28:45.582765

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '19d0ec0d3061'
down_revision: Union[str, Sequence[str], None] = '2056171fd5ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------
    # 1) influencer_subscriptions: add is_18_selected
    # -----------------------------
    op.execute("""
        ALTER TABLE influencer_subscriptions
        ADD COLUMN IF NOT EXISTS is_18_selected BOOLEAN NOT NULL DEFAULT false
    """)

    # If you previously had is_18_selected on users and want to remove it:
    op.execute("""
        ALTER TABLE users
        DROP COLUMN IF EXISTS is_18_selected
    """)

    # -----------------------------
    # 2) influencer_wallets: add is_18
    # -----------------------------
    op.execute("""
        ALTER TABLE influencer_wallets
        ADD COLUMN IF NOT EXISTS is_18 BOOLEAN NOT NULL DEFAULT false
    """)

    # IMPORTANT: if you want uniqueness per (user_id, influencer_id, is_18)
    # Drop old constraint if it exists, then recreate a new one.
    # Adjust the constraint name if yours differs.
    op.execute("""
        ALTER TABLE influencer_wallets
        DROP CONSTRAINT IF EXISTS uq_user_influencer_wallet
    """)
    op.execute("""
        ALTER TABLE influencer_wallets
        ADD CONSTRAINT uq_user_influencer_wallet
        UNIQUE (user_id, influencer_id, is_18)
    """)

    # -----------------------------
    # 3) daily_usage: add is_18 + change primary key
    # -----------------------------
    op.execute("""
        ALTER TABLE daily_usage
        ADD COLUMN IF NOT EXISTS is_18 BOOLEAN NOT NULL DEFAULT false
    """)

    # Default existing rows to is_18=false (safe even if already false)
    op.execute("""
        UPDATE daily_usage SET is_18 = false WHERE is_18 IS NULL
    """)

    # Drop the old PK and create new PK including is_18
    # Postgres default pk name: daily_usage_pkey
    op.execute("""
        ALTER TABLE daily_usage
        DROP CONSTRAINT IF EXISTS daily_usage_pkey
    """)
    op.execute("""
        ALTER TABLE daily_usage
        ADD CONSTRAINT daily_usage_pkey PRIMARY KEY (user_id, date, is_18)
    """)


def downgrade() -> None:
    # Revert daily_usage PK
    op.execute("""
        ALTER TABLE daily_usage
        DROP CONSTRAINT IF EXISTS daily_usage_pkey
    """)
    op.execute("""
        ALTER TABLE daily_usage
        ADD CONSTRAINT daily_usage_pkey PRIMARY KEY (user_id, date)
    """)
    op.execute("""
        ALTER TABLE daily_usage
        DROP COLUMN IF EXISTS is_18
    """)

    # influencer_wallets
    op.execute("""
        ALTER TABLE influencer_wallets
        DROP CONSTRAINT IF EXISTS uq_user_influencer_wallet
    """)
    op.execute("""
        ALTER TABLE influencer_wallets
        ADD CONSTRAINT uq_user_influencer_wallet
        UNIQUE (user_id, influencer_id)
    """)
    op.execute("""
        ALTER TABLE influencer_wallets
        DROP COLUMN IF EXISTS is_18
    """)

    # influencer_subscriptions
    op.execute("""
        ALTER TABLE influencer_subscriptions
        DROP COLUMN IF EXISTS is_18_selected
    """)
