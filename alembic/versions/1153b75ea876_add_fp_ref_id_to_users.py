"""add fp_ref_id to users

Revision ID: 1153b75ea876
Revises: 114ced4b59ae
Create Date: 2025-12-22 13:33:30.946215

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1153b75ea876'
down_revision: Union[str, Sequence[str], None] = '114ced4b59ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("users", sa.Column("fp_ref_id", sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column("users", "fp_ref_id")
