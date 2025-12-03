"""Add user nickname and normalize influencer timestamps

Revision ID: f3e6b7294a1c
Revises: 23649145b822
Create Date: 2025-12-02 23:15:53

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f3e6b7294a1c"
down_revision: Union[str, Sequence[str], None] = "23649145b822"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("nickname", sa.String(), nullable=True))

    # Align influencer.created_at with other timestamptz audit columns.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'influencers'
                  AND column_name = 'created_at'
                  AND data_type = 'timestamp with time zone'
            ) THEN
                ALTER TABLE influencers
                ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE
                USING created_at AT TIME ZONE 'UTC';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "nickname")
    op.execute(
        """
        ALTER TABLE influencers
        ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE
        USING created_at AT TIME ZONE 'UTC';
        """
    )
