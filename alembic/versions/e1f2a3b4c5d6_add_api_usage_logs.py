"""add api_usage_logs table

Revision ID: e1f2a3b4c5d6
Revises: d4e5f6a7b8c9
Create Date: 2026-02-12 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create api_usage_logs table."""
    # ── Individual logs (kept forever) ───────────────────────────
    op.create_table(
        'api_usage_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('model', sa.String(length=60), nullable=False),
        sa.Column('purpose', sa.String(length=40), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('estimated_cost_micros', sa.BigInteger(), nullable=True),
        sa.Column('duration_secs', sa.Float(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('success', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('influencer_id', sa.String(), nullable=True),
        sa.Column('chat_id', sa.String(), nullable=True),
        sa.Column('conversation_id', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_api_usage_cat_created', 'api_usage_logs', ['category', 'created_at'])
    op.create_index('ix_api_usage_model_created', 'api_usage_logs', ['model', 'created_at'])
    op.create_index('ix_api_usage_provider_created', 'api_usage_logs', ['provider', 'created_at'])
    op.create_index('ix_api_usage_user_created', 'api_usage_logs', ['user_id', 'created_at'])
    op.create_index('ix_api_usage_category', 'api_usage_logs', ['category'])
    op.create_index('ix_api_usage_model', 'api_usage_logs', ['model'])
    op.create_index('ix_api_usage_user_id', 'api_usage_logs', ['user_id'])
    op.create_index('ix_api_usage_influencer_id', 'api_usage_logs', ['influencer_id'])
    op.create_index('ix_api_usage_conversation', 'api_usage_logs', ['conversation_id'])


def downgrade() -> None:
    """Drop api_usage_logs table."""
    op.drop_index('ix_api_usage_conversation', table_name='api_usage_logs')
    op.drop_index('ix_api_usage_influencer_id', table_name='api_usage_logs')
    op.drop_index('ix_api_usage_user_id', table_name='api_usage_logs')
    op.drop_index('ix_api_usage_model', table_name='api_usage_logs')
    op.drop_index('ix_api_usage_category', table_name='api_usage_logs')
    op.drop_index('ix_api_usage_user_created', table_name='api_usage_logs')
    op.drop_index('ix_api_usage_provider_created', table_name='api_usage_logs')
    op.drop_index('ix_api_usage_model_created', table_name='api_usage_logs')
    op.drop_index('ix_api_usage_cat_created', table_name='api_usage_logs')
    op.drop_table('api_usage_logs')
