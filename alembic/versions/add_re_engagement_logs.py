from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2a3b4c5d6e7f'
down_revision = '1a2b3c4d5e6f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        're_engagement_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('influencer_id', sa.String(), nullable=False),
        sa.Column('notification_type', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('media_url', sa.String(), nullable=True),
        sa.Column('delivered', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('delivery_error', sa.Text(), nullable=True),
        sa.Column('subscriptions_targeted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('subscriptions_succeeded', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('wallet_balance_cents', sa.Integer(), nullable=False),
        sa.Column('days_inactive', sa.Integer(), nullable=False),
        sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['influencer_id'], ['influencers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    
    op.create_index('ix_re_engagement_logs_user_id', 're_engagement_logs', ['user_id'])
    op.create_index('ix_re_engagement_logs_influencer_id', 're_engagement_logs', ['influencer_id'])
    op.create_index('ix_reeng_user_infl_triggered', 're_engagement_logs', ['user_id', 'influencer_id', 'triggered_at'])
    op.create_index('ix_reeng_triggered_at', 're_engagement_logs', ['triggered_at'])


def downgrade() -> None:
    op.drop_index('ix_reeng_triggered_at', table_name='re_engagement_logs')
    op.drop_index('ix_reeng_user_infl_triggered', table_name='re_engagement_logs')
    op.drop_index('ix_re_engagement_logs_influencer_id', table_name='re_engagement_logs')
    op.drop_index('ix_re_engagement_logs_user_id', table_name='re_engagement_logs')
    op.drop_table('re_engagement_logs')
