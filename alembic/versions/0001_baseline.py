"""baseline

Revision ID: 0001_baseline
Revises:
Create Date: 2026-01-12 10:48:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001_baseline'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    
    # --- users ---
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(), unique=True, nullable=True),
        sa.Column('full_name', sa.String(), nullable=True),
        sa.Column('date_of_birth', sa.DateTime(), nullable=True),
        sa.Column('gender', sa.String(), nullable=True),
        sa.Column('email', sa.String(), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('is_verified', sa.Boolean(), default=False, nullable=False),
        sa.Column('email_token', sa.String(), nullable=True),
        sa.Column('password_reset_token', sa.String(), nullable=True),
        sa.Column('password_reset_token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('profile_photo_key', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    # --- influencers ---
    op.create_table(
        'influencers',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('voice_id', sa.String(), nullable=True),
        sa.Column('prompt_template', sa.Text(), nullable=False),
        sa.Column('bio_json', postgresql.JSONB(), nullable=True),
        sa.Column('profile_photo_key', sa.String(), nullable=True),
        sa.Column('profile_video_key', sa.String(), nullable=True),
        sa.Column('native_language', sa.String(), nullable=True),
        sa.Column('date_of_birth', sa.DateTime(), nullable=True),
        sa.Column('daily_scripts', sa.JSON(), nullable=True),
        sa.Column('influencer_agent_id_third_part', sa.String(), nullable=True),
        sa.Column('fp_promoter_id', sa.String(), nullable=True),
        sa.Column('fp_ref_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    # --- chats ---
    op.create_table(
        'chats',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('influencer_id', sa.String(), sa.ForeignKey('influencers.id'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    )

    # --- calls (must exist before messages due to FK) ---
    op.create_table(
        'calls',
        sa.Column('conversation_id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False, index=True),
        sa.Column('influencer_id', sa.String(), nullable=True),
        sa.Column('chat_id', sa.String(), sa.ForeignKey('chats.id'), nullable=True, index=True),
        sa.Column('sid', sa.String(), nullable=True),
        sa.Column('status', sa.String(), default='pending', nullable=False),
        sa.Column('call_duration_secs', sa.Float(), nullable=True),
        sa.Column('transcript', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_calls_user_created', 'calls', ['user_id', 'created_at'])

    # --- messages ---
    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chat_id', sa.String(), sa.ForeignKey('chats.id'), nullable=False, index=True),
        sa.Column('sender', sa.String(), nullable=False),
        sa.Column('channel', sa.String(), default='text', nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('audio_url', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('embedding', postgresql.ARRAY(sa.Float()), nullable=True),  # pgvector handled separately
        sa.Column('conversation_id', sa.String(), sa.ForeignKey('calls.conversation_id'), nullable=True),
    )
    # Replace array with vector type
    op.execute('ALTER TABLE messages ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)')

    # --- chats_18 ---
    op.create_table(
        'chats_18',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('influencer_id', sa.String(), sa.ForeignKey('influencers.id'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    )

    # --- messages_18 ---
    op.create_table(
        'messages_18',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('chat_id', sa.String(), sa.ForeignKey('chats_18.id'), nullable=False, index=True),
        sa.Column('sender', sa.String(), nullable=False),
        sa.Column('channel', sa.String(), default='text_18', nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('audio_url', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('embedding', postgresql.ARRAY(sa.Float()), nullable=True),
    )
    op.execute('ALTER TABLE messages_18 ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)')

    # --- memories ---
    op.create_table(
        'memories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chat_id', sa.String(), sa.ForeignKey('chats.id'), nullable=False, index=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', postgresql.ARRAY(sa.Float()), nullable=False),
        sa.Column('sender', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.execute('ALTER TABLE memories ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)')

    # --- subscriptions ---
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('subscription_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )

    # --- pricing ---
    op.create_table(
        'pricing',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('feature', sa.String(), nullable=False),
        sa.Column('unit', sa.String(), nullable=False),
        sa.Column('price_cents', sa.Integer(), nullable=False),
        sa.Column('free_allowance', sa.Integer(), default=0, nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
    )

    # --- influencer_wallets ---
    op.create_table(
        'influencer_wallets',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('influencer_id', sa.String(), sa.ForeignKey('influencers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('is_18', sa.Boolean(), nullable=False, default=False, server_default='false'),
        sa.Column('balance_cents', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'influencer_id', name='uq_user_influencer_wallet'),
    )
    op.create_index('ix_infl_wallet_user_infl', 'influencer_wallets', ['user_id', 'influencer_id'])

    # --- influencer_credit_transactions ---
    op.create_table(
        'influencer_credit_transactions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('influencer_id', sa.String(), sa.ForeignKey('influencers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('feature', sa.String(), nullable=False),
        sa.Column('units', sa.Integer(), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('meta', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_infl_tx_user_infl_ts', 'influencer_credit_transactions', ['user_id', 'influencer_id', 'created_at'])

    # --- daily_usage ---
    op.create_table(
        'daily_usage',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('date', sa.DateTime(), primary_key=True),
        sa.Column('is_18', sa.Boolean(), primary_key=True, nullable=False, default=False, server_default='false'),
        sa.Column('free_allowance', sa.Integer(), default=0, nullable=False),
        sa.Column('text_count', sa.Integer(), default=0, nullable=False),
        sa.Column('voice_secs', sa.Integer(), default=0, nullable=False),
        sa.Column('live_secs', sa.Integer(), default=0, nullable=False),
    )

    # --- influencer_followers ---
    op.create_table(
        'influencer_followers',
        sa.Column('influencer_id', sa.String(), sa.ForeignKey('influencers.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_influencer_followers_user_id', 'influencer_followers', ['user_id'])

    # --- influencer_subscriptions ---
    op.create_table(
        'influencer_subscriptions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('influencer_id', sa.String(), sa.ForeignKey('influencers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('price_cents', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(), nullable=False, default='AUD'),
        sa.Column('interval', sa.String(), nullable=False, default='monthly'),
        sa.Column('status', sa.String(), nullable=False, default='active'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_payment_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_payment_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_reason', sa.String(), nullable=True),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('provider_customer_id', sa.String(), nullable=True, index=True),
        sa.Column('provider_subscription_id', sa.String(), nullable=True, index=True),
        sa.Column('meta', sa.JSON(), nullable=True),
        sa.Column('is_18_selected', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'influencer_id', name='uq_user_influencer_subscription'),
    )
    op.create_index('ix_inf_sub_user_infl', 'influencer_subscriptions', ['user_id', 'influencer_id'])
    op.create_index('ix_inf_sub_status_nextpay', 'influencer_subscriptions', ['status', 'next_payment_at'])

    # --- influencer_subscription_payments ---
    op.create_table(
        'influencer_subscription_payments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('subscription_id', sa.Integer(), sa.ForeignKey('influencer_subscriptions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('influencer_id', sa.String(), sa.ForeignKey('influencers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(), nullable=False, default='AUD'),
        sa.Column('kind', sa.String(), nullable=False, default='charge'),
        sa.Column('status', sa.String(), nullable=False, default='pending'),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('provider_event_id', sa.String(), nullable=True, unique=True, index=True),
        sa.Column('provider_payload', sa.JSON(), nullable=True),
        sa.Column('failure_code', sa.String(), nullable=True),
        sa.Column('failure_message', sa.Text(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_inf_sub_pay_user_infl_time', 'influencer_subscription_payments', ['user_id', 'influencer_id', 'occurred_at'])

    # --- system_prompts ---
    op.create_table(
        'system_prompts',
        sa.Column('key', sa.String(), primary_key=True),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # --- pre_influencers ---
    op.create_table(
        'pre_influencers',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('full_name', sa.String(), nullable=False),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('username', sa.String(), unique=True, nullable=False),
        sa.Column('email', sa.String(), unique=True, nullable=False),
        sa.Column('password', sa.String(), nullable=True),
        sa.Column('survey_token', sa.String(), nullable=True),
        sa.Column('survey_answers', sa.JSON(), nullable=True),
        sa.Column('survey_step', sa.Integer(), nullable=False, default=0),
        sa.Column('ig_user_id', sa.String(), nullable=True),
        sa.Column('ig_access_token', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('terms_agreement', sa.Boolean(), default=False, nullable=False),
        sa.Column('fp_promoter_id', sa.String(), nullable=True),
        sa.Column('fp_ref_id', sa.String(), nullable=True),
    )

    # --- relationship_state ---
    op.create_table(
        'relationship_state',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('influencer_id', sa.String(), sa.ForeignKey('influencers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('trust', sa.Float(), default=10.0, nullable=False),
        sa.Column('closeness', sa.Float(), default=10.0, nullable=False),
        sa.Column('attraction', sa.Float(), default=5.0, nullable=False),
        sa.Column('safety', sa.Float(), default=95.0, nullable=False),
        sa.Column('state', sa.String(), default='STRANGERS', nullable=False),
        sa.Column('exclusive_agreed', sa.Boolean(), default=False, nullable=False),
        sa.Column('girlfriend_confirmed', sa.Boolean(), default=False, nullable=False),
        sa.Column('dtr_stage', sa.Integer(), default=0, nullable=False),
        sa.Column('dtr_cooldown_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stage_points', sa.Float(), default=0.0, nullable=False),
        sa.Column('sentiment_score', sa.Float(), default=0.0, nullable=False),
        sa.Column('last_interaction_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_rel_user_influencer', 'relationship_state', ['user_id', 'influencer_id'], unique=True)

    # --- paypal_topups ---
    op.create_table(
        'paypal_topups',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('order_id', sa.String(), unique=True, nullable=False, index=True),
        sa.Column('cents', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), default='CREATED', nullable=False),
        sa.Column('credited', sa.Boolean(), default=False, nullable=False),
        sa.Column('fp_tracked', sa.Boolean(), nullable=False, default=False),
        sa.Column('influencer_id', sa.String(), sa.ForeignKey('influencers.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('paypal_topups')
    op.drop_table('relationship_state')
    op.drop_table('pre_influencers')
    op.drop_table('system_prompts')
    op.drop_table('influencer_subscription_payments')
    op.drop_table('influencer_subscriptions')
    op.drop_table('influencer_followers')
    op.drop_table('daily_usage')
    op.drop_table('influencer_credit_transactions')
    op.drop_table('influencer_wallets')
    op.drop_table('pricing')
    op.drop_table('subscriptions')
    op.drop_table('memories')
    op.drop_table('messages_18')
    op.drop_table('chats_18')
    op.drop_table('messages')
    op.drop_table('calls')
    op.drop_table('chats')
    op.drop_table('influencers')
    op.drop_table('users')
    op.execute('DROP EXTENSION IF EXISTS vector')
