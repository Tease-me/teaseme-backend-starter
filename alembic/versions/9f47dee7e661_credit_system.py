"""credit system

Revision ID: 9f47dee7e661
Revises: a2065cabad4f
Create Date: 2025-08-04 13:38:20.957828

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f47dee7e661'
down_revision: Union[str, Sequence[str], None] = 'a2065cabad4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
