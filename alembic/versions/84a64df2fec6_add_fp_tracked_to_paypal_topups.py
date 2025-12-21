"""add fp_tracked to paypal_topups

Revision ID: 84a64df2fec6
Revises: aa0d5e5cfb88
Create Date: 2025-12-20 20:05:58.984239

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '84a64df2fec6'
down_revision: Union[str, Sequence[str], None] = 'aa0d5e5cfb88'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "paypal_topups",
        sa.Column("fp_tracked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column("paypal_topups", "fp_tracked", server_default=None)


def downgrade() -> None:
    op.drop_column("paypal_topups", "fp_tracked")