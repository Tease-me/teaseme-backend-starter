"""add influencer knowledge tables

Revision ID: add_influencer_knowledge
Revises: f24e5ddb5269
Create Date: 2025-01-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector


# revision identifiers, used by Alembic.
revision: str = 'add_influencer_knowledge'
down_revision: Union[str, Sequence[str], None] = 'ae0dbe1bf126'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create influencer_knowledge_files table
    op.create_table('influencer_knowledge_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('influencer_id', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('file_type', sa.String(), nullable=False),
        sa.Column('s3_key', sa.String(), nullable=False),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('uploaded_by', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='processing'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['influencer_id'], ['influencers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_influencer_knowledge_files_influencer_id'), 'influencer_knowledge_files', ['influencer_id'], unique=False)
    
    # Create influencer_knowledge_chunks table
    op.create_table('influencer_knowledge_chunks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('file_id', sa.Integer(), nullable=False),
        sa.Column('influencer_id', sa.String(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False),
        sa.Column('chunk_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['file_id'], ['influencer_knowledge_files.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['influencer_id'], ['influencers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_id', 'chunk_index', name='uq_file_chunk_index')
    )
    op.create_index(op.f('ix_influencer_knowledge_chunks_file_id'), 'influencer_knowledge_chunks', ['file_id'], unique=False)
    op.create_index('idx_knowledge_chunks_influencer', 'influencer_knowledge_chunks', ['influencer_id'], unique=False)
    # Create vector index for similarity search
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding ON influencer_knowledge_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_knowledge_chunks_embedding', table_name='influencer_knowledge_chunks')
    op.drop_index('idx_knowledge_chunks_influencer', table_name='influencer_knowledge_chunks')
    op.drop_index(op.f('ix_influencer_knowledge_chunks_file_id'), table_name='influencer_knowledge_chunks')
    op.drop_table('influencer_knowledge_chunks')
    op.drop_index(op.f('ix_influencer_knowledge_files_influencer_id'), table_name='influencer_knowledge_files')
    op.drop_table('influencer_knowledge_files')

