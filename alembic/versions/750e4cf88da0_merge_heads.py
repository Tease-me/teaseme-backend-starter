"""merge heads

Revision ID: 750e4cf88da0
Revises: 4f7e4f4f2a3e, e5f8f202b6eb
Create Date: 2025-11-24 00:11:22.221567

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '750e4cf88da0'
down_revision: Union[str, Sequence[str], None] = ('4f7e4f4f2a3e', 'e5f8f202b6eb')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
