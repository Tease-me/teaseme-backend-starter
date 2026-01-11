"""is18+

Revision ID: 2056171fd5ef
Revises: ce6ce6661a10
Create Date: 2026-01-09 06:38:10.244114

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2056171fd5ef'
down_revision: Union[str, Sequence[str], None] = 'ce6ce6661a10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
        # 1) add column
    op.add_column(
        "influencer_wallets",
        sa.Column("is_18", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # 2) drop old unique constraint if it exists (name may differ)
    # If your old constraint name is different, replace it here.
    op.drop_constraint("uq_user_influencer_wallet", "influencer_wallets", type_="unique")

    # 3) create new unique constraint including is_18
    op.create_unique_constraint(
        "uq_user_influencer_wallet_mode",
        "influencer_wallets",
        ["user_id", "influencer_id", "is_18"],
    )

    # 4) helpful index
    op.create_index(
        "ix_infl_wallet_user_infl_mode",
        "influencer_wallets",
        ["user_id", "influencer_id", "is_18"],
        unique=False,
    )

    # 5) remove server_default (optional, but keeps schema clean)
    op.alter_column("influencer_wallets", "is_18", server_default=None)


def downgrade():
    op.drop_index("ix_infl_wallet_user_infl_mode", table_name="influencer_wallets")
    op.drop_constraint("uq_user_influencer_wallet_mode", "influencer_wallets", type_="unique")

    # restore old unique
    op.create_unique_constraint(
        "uq_user_influencer_wallet",
        "influencer_wallets",
        ["user_id", "influencer_id"],
    )

    op.drop_column("influencer_wallets", "is_18")