"""fix add chat_id to calls

Revision ID: 1330a77f992a
Revises: 8ecc284af443
Create Date: 2025-08-24 11:06:27.092564

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1330a77f992a'
down_revision: Union[str, Sequence[str], None] = '8ecc284af443'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
