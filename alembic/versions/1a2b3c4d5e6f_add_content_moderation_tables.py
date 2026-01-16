"""add_content_moderation_tables

Revision ID: 1a2b3c4d5e6f
Revises: 
Create Date: 2026-01-16 10:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, None] = 'c51d43c1f19c'  # Link to current head
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add moderation fields to users table
    op.add_column('users', sa.Column('moderation_status', sa.String(), nullable=True, server_default='CLEAN'))
    op.add_column('users', sa.Column('violation_count', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('users', sa.Column('first_violation_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('last_violation_at', sa.DateTime(timezone=True), nullable=True))

    # Create content_violations table
    op.create_table('content_violations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('chat_id', sa.String(), nullable=False),
        sa.Column('influencer_id', sa.String(), nullable=True),
        sa.Column('message_content', sa.Text(), nullable=False),
        sa.Column('message_context', sa.Text(), nullable=True),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('severity', sa.String(), nullable=False),
        sa.Column('keyword_matched', sa.String(), nullable=True),
        sa.Column('ai_confidence', sa.Float(), nullable=True),
        sa.Column('ai_reasoning', sa.Text(), nullable=True),
        sa.Column('detection_tier', sa.String(), nullable=False),
        sa.Column('reviewed', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by', sa.String(), nullable=True),
        sa.Column('review_action', sa.String(), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_violations_user_created', 'content_violations', ['user_id', 'created_at'], unique=False)
    op.create_index('ix_violations_category', 'content_violations', ['category'], unique=False)
    op.create_index('ix_violations_reviewed', 'content_violations', ['reviewed'], unique=False)
    op.create_index(op.f('ix_content_violations_user_id'), 'content_violations', ['user_id'], unique=False)
    op.create_index(op.f('ix_content_violations_chat_id'), 'content_violations', ['chat_id'], unique=False)

    # Create moderation_keywords table
    op.create_table('moderation_keywords',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('pattern', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('severity', sa.String(), nullable=False, server_default='HIGH'),
        sa.Column('is_regex', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pattern')
    )
    op.create_index('ix_mod_keywords_category', 'moderation_keywords', ['category'], unique=False)
    op.create_index('ix_mod_keywords_active', 'moderation_keywords', ['is_active'], unique=False)


def downgrade() -> None:
    # Drop moderation_keywords
    op.drop_index('ix_mod_keywords_active', table_name='moderation_keywords')
    op.drop_index('ix_mod_keywords_category', table_name='moderation_keywords')
    op.drop_table('moderation_keywords')

    # Drop content_violations
    op.drop_index(op.f('ix_content_violations_chat_id'), table_name='content_violations')
    op.drop_index(op.f('ix_content_violations_user_id'), table_name='content_violations')
    op.drop_index('ix_violations_reviewed', table_name='content_violations')
    op.drop_index('ix_violations_category', table_name='content_violations')
    op.drop_index('ix_violations_user_created', table_name='content_violations')
    op.drop_table('content_violations')

    # Remove moderation fields from users
    op.drop_column('users', 'last_violation_at')
    op.drop_column('users', 'first_violation_at')
    op.drop_column('users', 'violation_count')
    op.drop_column('users', 'moderation_status')
