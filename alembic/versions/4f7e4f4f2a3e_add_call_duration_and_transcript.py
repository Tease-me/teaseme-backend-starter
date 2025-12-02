"""Add duration and transcript to calls

Revision ID: 4f7e4f4f2a3e
Revises: db3d9cc045e1
Create Date: 2025-02-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4f7e4f4f2a3e"
down_revision: Union[str, None] = "db3d9cc045e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column("calls", sa.Column("call_duration_secs", sa.Integer(), nullable=True))
    op.add_column("calls", sa.Column("transcript", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("calls", "transcript")
    op.drop_column("calls", "call_duration_secs")

