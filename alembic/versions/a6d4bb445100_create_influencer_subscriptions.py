"""create_influencer_subscriptions

Revision ID: a6d4bb445100
Revises: 19109d84d4b5
Create Date: 2026-01-08 00:26:22.444025

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a6d4bb445100'
down_revision: Union[str, Sequence[str], None] = '19109d84d4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade():
    op.create_table(
        "influencer_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("influencer_id", sa.String(), sa.ForeignKey("influencers.id", ondelete="CASCADE"), nullable=False),

        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="AUD"),
        sa.Column("interval", sa.String(), nullable=False, server_default="monthly"),

        sa.Column("status", sa.String(), nullable=False, server_default="active"),

        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True)),
        sa.Column("current_period_end", sa.DateTime(timezone=True)),
        sa.Column("last_payment_at", sa.DateTime(timezone=True)),
        sa.Column("next_payment_at", sa.DateTime(timezone=True)),

        sa.Column("canceled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String()),

        sa.Column("provider", sa.String()),
        sa.Column("provider_customer_id", sa.String()),
        sa.Column("provider_subscription_id", sa.String()),

        sa.Column("meta", postgresql.JSONB()),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),

        sa.UniqueConstraint("user_id", "influencer_id", name="uq_user_influencer_subscription"),
    )

    op.create_index(
        "ix_inf_sub_user_infl",
        "influencer_subscriptions",
        ["user_id", "influencer_id"],
    )

    op.create_index(
        "ix_inf_sub_status_nextpay",
        "influencer_subscriptions",
        ["status", "next_payment_at"],
    )

    op.create_table(
        "influencer_subscription_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("influencer_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("influencer_id", sa.String(), sa.ForeignKey("influencers.id", ondelete="CASCADE"), nullable=False),

        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="AUD"),

        sa.Column("kind", sa.String(), nullable=False, server_default="charge"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),

        sa.Column("provider", sa.String()),
        sa.Column("provider_event_id", sa.String(), unique=True),
        sa.Column("provider_payload", postgresql.JSONB()),

        sa.Column("failure_code", sa.String()),
        sa.Column("failure_message", sa.Text()),

        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index(
        "ix_inf_sub_pay_user_infl_time",
        "influencer_subscription_payments",
        ["user_id", "influencer_id", "occurred_at"],
    )


def downgrade():
    op.drop_table("influencer_subscription_payments")
    op.drop_table("influencer_subscriptions")
