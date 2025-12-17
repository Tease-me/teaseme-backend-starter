"""add stage_points to relationship_state

Revision ID: 98701b0dafbf
Revises: 2a9b4f8e2b76
Create Date: 2025-12-15 03:21:26.262723

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '98701b0dafbf'
down_revision: Union[str, Sequence[str], None] = '2a9b4f8e2b76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 1) add column nullable first
    op.add_column("relationship_state", sa.Column("stage_points", sa.Float(), nullable=True))

    # 2) backfill existing rows
    op.execute("UPDATE relationship_state SET stage_points = 0 WHERE stage_points IS NULL")

    # 3) set default for future rows
    op.execute("ALTER TABLE relationship_state ALTER COLUMN stage_points SET DEFAULT 0")

    # 4) make it NOT NULL
    op.alter_column("relationship_state", "stage_points", nullable=False)

def downgrade():
    op.drop_column("relationship_state", "stage_points")
