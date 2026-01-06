"""fix influencer_wallets schema

Revision ID: 2188ca984f3a
Revises: 60badaca636b
Create Date: 2026-01-06 00:02:19.391264

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2188ca984f3a'
down_revision: Union[str, Sequence[str], None] = '60badaca636b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # drop old wrong table
    op.execute("DROP TABLE IF EXISTS influencer_wallets CASCADE;")

    op.create_table(
        "influencer_wallets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("influencer_id", sa.String(), sa.ForeignKey("influencers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("balance_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_unique_constraint("uq_user_influencer_wallet", "influencer_wallets", ["user_id", "influencer_id"])
    op.create_index("ix_infl_wallet_user_infl", "influencer_wallets", ["user_id", "influencer_id"])

def downgrade():
    op.execute("DROP TABLE IF EXISTS influencer_wallets CASCADE;")
