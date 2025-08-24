"""add chat_id to calls with FK to chats, backfill

Revision ID: 8ecc284af443
Revises: f24e5ddb5269
Create Date: 2025-08-24 10:46:46.614622

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ecc284af443'
down_revision: Union[str, Sequence[str], None] = 'f24e5ddb5269'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
