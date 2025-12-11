"""merge heads

Revision ID: 43e630570a46
Revises: 1f215bd507f8, 5a8b6c4d2e1f
Create Date: 2025-12-10 10:16:22.028652

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '43e630570a46'
down_revision: Union[str, Sequence[str], None] = ('1f215bd507f8', '5a8b6c4d2e1f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
