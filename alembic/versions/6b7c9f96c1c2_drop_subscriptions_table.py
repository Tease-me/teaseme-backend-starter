"""Drop subscriptions table

Revision ID: 6b7c9f96c1c2
Revises: f24e5ddb5269
Create Date: 2026-02-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6b7c9f96c1c2"
down_revision: Union[str, Sequence[str], None] = "f24e5ddb5269"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Remove subscriptions table."""
    bind = op.get_bind()
    if _table_exists(bind, "subscriptions"):
        op.drop_table("subscriptions")


def downgrade() -> None:
    """Recreate subscriptions table."""
    bind = op.get_bind()
    if _table_exists(bind, "subscriptions"):
        return

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("subscription_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

