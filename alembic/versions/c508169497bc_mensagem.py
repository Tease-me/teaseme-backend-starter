"""mensagem

Revision ID: c508169497bc
Revises: 8860075a6b90
Create Date: 2025-07-15 09:43:26.256817

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector 

# revision identifiers, used by Alembic.
revision: str = 'c508169497bc'
down_revision: Union[str, Sequence[str], None] = 'f3e6b7294a1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Ensure vector extension exists and add embedding only if missing.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS embedding VECTOR(1536)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS embedding")
