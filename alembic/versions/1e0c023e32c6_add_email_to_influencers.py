"""add email to influencers

Revision ID: 1e0c023e32c6
Revises: 1a2b3c4d5e6f
Create Date: 2026-01-21 23:28:22.064615

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1e0c023e32c6'
down_revision: Union[str, Sequence[str], None] = '1a2b3c4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("ALTER TABLE influencers ADD COLUMN IF NOT EXISTS email VARCHAR")
    op.execute(
        """
        UPDATE influencers
        SET email = 'dummy_' || md5(random()::text || clock_timestamp()::text) || '@example.com'
        WHERE email IS NULL OR email = ''
        """
    )
    op.execute("ALTER TABLE influencers ALTER COLUMN email SET NOT NULL")


def downgrade():
    op.execute("ALTER TABLE influencers ALTER COLUMN email DROP NOT NULL")
    op.execute("ALTER TABLE influencers DROP COLUMN IF EXISTS email")
