"""remove_separate_balance_fields

Revision ID: ea2a1df4f0bb
Revises: ec78501d47f5
Create Date: 2026-01-23 08:24:54.267501

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea2a1df4f0bb'
down_revision: Union[str, Sequence[str], None] = 'ec78501d47f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Ensure balance_cents has the total (subscription + addon)
    op.execute("""
        UPDATE influencer_wallets
        SET balance_cents = COALESCE(subscription_balance_cents, 0) + COALESCE(addon_balance_cents, 0)
    """)
    
    # Drop the separate balance columns
    op.drop_column('influencer_wallets', 'subscription_balance_cents')
    op.drop_column('influencer_wallets', 'addon_balance_cents')


def downgrade() -> None:
    """Downgrade schema."""
    # Add columns back
    op.add_column('influencer_wallets', sa.Column('subscription_balance_cents', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('influencer_wallets', sa.Column('addon_balance_cents', sa.Integer(), nullable=False, server_default='0'))
    
    # Migrate balance_cents to subscription_balance_cents
    op.execute("""
        UPDATE influencer_wallets
        SET subscription_balance_cents = balance_cents
    """)
    
    op.alter_column('influencer_wallets', 'subscription_balance_cents', server_default=None)
    op.alter_column('influencer_wallets', 'addon_balance_cents', server_default=None)
