"""chat18+_by_influencer

Revision ID: ebd318ce2b02
Revises: 831d21ddebc3
Create Date: 2026-01-08 23:52:42.503968

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ebd318ce2b02'
down_revision: Union[str, Sequence[str], None] = '831d21ddebc3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
