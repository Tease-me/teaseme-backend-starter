"""drop influencer knowledge tables

Revision ID: ce6ce6661a10
Revises: 74f92ac377aa
Create Date: 2026-01-09 00:59:54.605268

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce6ce6661a10'
down_revision: Union[str, Sequence[str], None] = '74f92ac377aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.drop_table("influencer_knowledge_chunks", if_exists=True)
    op.drop_table("influencer_knowledge_files", if_exists=True)


def downgrade() -> None:
    """Downgrade schema."""
    pass
