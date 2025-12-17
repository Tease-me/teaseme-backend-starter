"""add airwallex payment records

Revision ID: 3c9b1b8a2c1a
Revises: 5e5e2f12e930
Create Date: 2025-12-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3c9b1b8a2c1a"
down_revision: Union[str, Sequence[str], None] = "5e5e2f12e930"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "airwallex_billing_checkouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("airwallex_checkout_id", sa.String(), nullable=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("billing_customer_id", sa.String(), nullable=True),
        sa.Column("purpose", sa.String(), nullable=True),
        sa.Column("success_url", sa.String(), nullable=True),
        sa.Column("back_url", sa.String(), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=True),
        sa.Column("response_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("airwallex_checkout_id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index(
        "ix_airwallex_billing_checkouts_user_id",
        "airwallex_billing_checkouts",
        ["user_id"],
    )
    op.create_index(
        "ix_airwallex_billing_checkouts_billing_customer_id",
        "airwallex_billing_checkouts",
        ["billing_customer_id"],
    )

    op.create_table(
        "airwallex_payment_intents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("merchant_order_id", sa.String(), nullable=False),
        sa.Column("airwallex_payment_intent_id", sa.String(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("purpose", sa.String(), nullable=True),
        sa.Column("billing_customer_id", sa.String(), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=True),
        sa.Column("response_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("airwallex_payment_intent_id"),
        sa.UniqueConstraint("merchant_order_id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index(
        "ix_airwallex_payment_intents_user_id",
        "airwallex_payment_intents",
        ["user_id"],
    )
    op.create_index(
        "ix_airwallex_payment_intents_billing_customer_id",
        "airwallex_payment_intents",
        ["billing_customer_id"],
    )

    op.create_table(
        "wallet_topups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="USD"),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("airwallex_payment_intent_row_id", sa.Integer(), nullable=True),
        sa.Column("airwallex_billing_checkout_row_id", sa.Integer(), nullable=True),
        sa.Column("credit_transaction_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["airwallex_billing_checkout_row_id"], ["airwallex_billing_checkouts.id"]),
        sa.ForeignKeyConstraint(["airwallex_payment_intent_row_id"], ["airwallex_payment_intents.id"]),
        sa.ForeignKeyConstraint(["credit_transaction_id"], ["credit_transactions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wallet_topups_user_id", "wallet_topups", ["user_id"])
    op.create_index(
        "ix_wallet_topups_airwallex_payment_intent_row_id",
        "wallet_topups",
        ["airwallex_payment_intent_row_id"],
    )
    op.create_index(
        "ix_wallet_topups_airwallex_billing_checkout_row_id",
        "wallet_topups",
        ["airwallex_billing_checkout_row_id"],
    )
    op.create_index(
        "ix_wallet_topups_credit_transaction_id",
        "wallet_topups",
        ["credit_transaction_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_wallet_topups_credit_transaction_id", table_name="wallet_topups")
    op.drop_index("ix_wallet_topups_airwallex_billing_checkout_row_id", table_name="wallet_topups")
    op.drop_index("ix_wallet_topups_airwallex_payment_intent_row_id", table_name="wallet_topups")
    op.drop_index("ix_wallet_topups_user_id", table_name="wallet_topups")
    op.drop_table("wallet_topups")

    op.drop_index("ix_airwallex_payment_intents_billing_customer_id", table_name="airwallex_payment_intents")
    op.drop_index("ix_airwallex_payment_intents_user_id", table_name="airwallex_payment_intents")
    op.drop_table("airwallex_payment_intents")

    op.drop_index("ix_airwallex_billing_checkouts_billing_customer_id", table_name="airwallex_billing_checkouts")
    op.drop_index("ix_airwallex_billing_checkouts_user_id", table_name="airwallex_billing_checkouts")
    op.drop_table("airwallex_billing_checkouts")

