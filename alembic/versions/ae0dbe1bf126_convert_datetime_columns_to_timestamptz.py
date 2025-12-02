"""convert_datetime_columns_to_timestamptz

Revision ID: ae0dbe1bf126
Revises: db3d9cc045e1
Create Date: 2025-11-05 10:21:32.996060

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ae0dbe1bf126'
down_revision: Union[str, Sequence[str], None] = 'db3d9cc045e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: Convert datetime columns to timestamptz."""
    # Convert users.created_at
    op.execute("""
        ALTER TABLE users 
        ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE 
        USING created_at AT TIME ZONE 'UTC'
    """)
    
    # Convert chats.started_at
    op.execute("""
        ALTER TABLE chats 
        ALTER COLUMN started_at TYPE TIMESTAMP WITH TIME ZONE 
        USING started_at AT TIME ZONE 'UTC'
    """)
    
    # Convert credit_transactions.ts
    op.execute("""
        ALTER TABLE credit_transactions 
        ALTER COLUMN ts TYPE TIMESTAMP WITH TIME ZONE 
        USING ts AT TIME ZONE 'UTC'
    """)
    
    # Convert calls.created_at
    op.execute("""
        ALTER TABLE calls 
        ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE 
        USING created_at AT TIME ZONE 'UTC'
    """)


def downgrade() -> None:
    """Downgrade schema: Convert timestamptz columns back to timestamp."""
    # Convert users.created_at
    op.execute("""
        ALTER TABLE users 
        ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE 
        USING created_at AT TIME ZONE 'UTC'
    """)
    
    # Convert chats.started_at
    op.execute("""
        ALTER TABLE chats 
        ALTER COLUMN started_at TYPE TIMESTAMP WITHOUT TIME ZONE 
        USING started_at AT TIME ZONE 'UTC'
    """)
    
    # Convert credit_transactions.ts
    op.execute("""
        ALTER TABLE credit_transactions 
        ALTER COLUMN ts TYPE TIMESTAMP WITHOUT TIME ZONE 
        USING ts AT TIME ZONE 'UTC'
    """)
    
    # Convert calls.created_at
    op.execute("""
        ALTER TABLE calls 
        ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE 
        USING created_at AT TIME ZONE 'UTC'
    """)
