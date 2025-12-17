"""add auto topup fields to credit_wallets

Revision ID: 5e5e2f12e930
Revises: 5103c8c5c3cf
Create Date: 2025-12-17 11:47:01.885910

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e5e2f12e930'
down_revision: Union[str, Sequence[str], None] = '5103c8c5c3cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "credit_wallets",
        sa.Column("auto_topup_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "credit_wallets",
        sa.Column("auto_topup_amount_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "credit_wallets",
        sa.Column("low_balance_threshold_cents", sa.Integer(), nullable=True),
    )
    op.alter_column("credit_wallets", "auto_topup_enabled", server_default=None)

def downgrade() -> None:
    op.drop_column("credit_wallets", "low_balance_threshold_cents")
    op.drop_column("credit_wallets", "auto_topup_amount_cents")
    op.drop_column("credit_wallets", "auto_topup_enabled")
