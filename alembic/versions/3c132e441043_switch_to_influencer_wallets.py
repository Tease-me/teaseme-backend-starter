"""switch to influencer wallets

Revision ID: 3c132e441043
Revises: ece6f4e155fb
Create Date: 2026-01-05 05:50:04.859209

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c132e441043'
down_revision: Union[str, Sequence[str], None] = 'ece6f4e155fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "influencer_wallets",
        sa.Column("influencer_id", sa.String(), primary_key=True),
        sa.Column("balance_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["influencer_id"], ["influencers.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "influencer_credit_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("influencer_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("feature", sa.String(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["influencer_id"], ["influencers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
