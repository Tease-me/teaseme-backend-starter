"""remove fp_tid from users

Revision ID: 114ced4b59ae
Revises: d58615a8cdc0
Create Date: 2025-12-22 13:18:11.904685

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '114ced4b59ae'
down_revision: Union[str, Sequence[str], None] = 'd58615a8cdc0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("users", "fp_tid")

def downgrade() -> None:
    op.add_column("users", sa.Column("fp_tid", sa.String(), nullable=True))
