"""remove fp_ref_id from users

Revision ID: ece6f4e155fb
Revises: 1153b75ea876
Create Date: 2026-01-05 02:02:23.209964

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ece6f4e155fb'
down_revision: Union[str, Sequence[str], None] = '1153b75ea876'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.drop_column("users", "fp_ref_id")


def downgrade():
    op.add_column(
        "users",
        sa.Column("fp_ref_id", sa.String(), nullable=True)
    )
