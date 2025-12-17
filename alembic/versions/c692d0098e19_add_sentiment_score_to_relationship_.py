"""add sentiment_score to relationship_state

Revision ID: c692d0098e19
Revises: 98701b0dafbf
Create Date: 2025-12-16 05:52:29.255634

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c692d0098e19'
down_revision: Union[str, Sequence[str], None] = '98701b0dafbf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 1) add nullable first
    op.add_column("relationship_state", sa.Column("sentiment_score", sa.Float(), nullable=True))

    # 2) backfill existing rows
    op.execute("UPDATE relationship_state SET sentiment_score = 0 WHERE sentiment_score IS NULL")

    # 3) default for new rows
    op.execute("ALTER TABLE relationship_state ALTER COLUMN sentiment_score SET DEFAULT 0")

    # 4) make not-null
    op.alter_column("relationship_state", "sentiment_score", nullable=False)

def downgrade():
    op.drop_column("relationship_state", "sentiment_score")
