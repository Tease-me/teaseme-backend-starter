"""add_plan_type_to_subscription_plans

Revision ID: 2f8f26c3e4ad
Revises: 1c9b122586e1
Create Date: 2026-01-23 08:15:39.954891

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f8f26c3e4ad'
down_revision: Union[str, Sequence[str], None] = '1c9b122586e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add plan_type column
    op.add_column('influencer_subscription_plans',
        sa.Column('plan_type', sa.String(), nullable=False, server_default='recurring')
    )
    
    # Update existing plans to be 'recurring' type
    op.execute("""
        UPDATE influencer_subscription_plans
        SET plan_type = 'recurring'
        WHERE interval IN ('monthly', 'yearly')
    """)
    
    # Remove server default after data migration
    op.alter_column('influencer_subscription_plans', 'plan_type',
        server_default=None
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('influencer_subscription_plans', 'plan_type')
