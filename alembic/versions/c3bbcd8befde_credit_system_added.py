"""credit system added

Revision ID: c3bbcd8befde
Revises: 9f47dee7e661
Create Date: 2025-08-04 14:52:46.603995

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3bbcd8befde'
down_revision: Union[str, Sequence[str], None] = '9f47dee7e661'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
