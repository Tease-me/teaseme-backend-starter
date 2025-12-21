"""add track paypal_topups

Revision ID: bcbc434b73e8
Revises: 84a64df2fec6
Create Date: 2025-12-20 10:17:31.255612

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bcbc434b73e8'
down_revision: Union[str, Sequence[str], None] = '84a64df2fec6'
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
