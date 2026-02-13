"""add_vector_indexes

Revision ID: g5h6i7j8k9l0
Revises: f3d4e5a6b7c8
Create Date: 2026-02-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g5h6i7j8k9l0'
down_revision: Union[str, Sequence[str], None] = 'f3d4e5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add vector indexes for faster similarity search on embeddings."""
    
    # Add IVFFlat index on memories.embedding for cosine distance operations
    # IVFFlat is faster to build and provides good performance for most use cases
    # lists=100 is a good starting point for 1K-100K vectors (adjust based on data size)
    op.execute("""
        CREATE INDEX IF NOT EXISTS memories_embedding_cosine_idx 
        ON memories 
        USING ivfflat (embedding vector_cosine_ops) 
        WITH (lists = 100)
    """)
    
    # Add IVFFlat index on messages.embedding for cosine distance operations
    op.execute("""
        CREATE INDEX IF NOT EXISTS messages_embedding_cosine_idx 
        ON messages 
        USING ivfflat (embedding vector_cosine_ops) 
        WITH (lists = 100)
    """)
    
    # Note: After creating the index, you may want to run ANALYZE on these tables
    # to update statistics for the query planner:
    #   ANALYZE memories;
    #   ANALYZE messages;


def downgrade() -> None:
    """Remove vector indexes."""
    op.execute("DROP INDEX IF EXISTS messages_embedding_cosine_idx")
    op.execute("DROP INDEX IF EXISTS memories_embedding_cosine_idx")
