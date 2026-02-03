"""add_identity_verification_didit

Revision ID: f3d4e5a6b7c8
Revises: ec78501d47f5
Create Date: 2026-01-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3d4e5a6b7c8'
down_revision: Union[str, Sequence[str], None] = 'ec78501d47f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add identity verification via Didit integration."""
    
    # Add verification fields to users table
    op.add_column('users', sa.Column('is_identity_verified', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('is_age_verified', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('verification_level', sa.String(), nullable=True))
    op.add_column('users', sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True))
    
    # Create identity_verifications table
    op.create_table(
        'identity_verifications',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('workflow_id', sa.String(), nullable=False),
        sa.Column('workflow_type', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('verification_result', sa.JSON(), nullable=True),
        sa.Column('verified_age', sa.Integer(), nullable=True),
        sa.Column('verified_identity_data', sa.JSON(), nullable=True),
        sa.Column('document_type', sa.String(), nullable=True),
        sa.Column('document_country', sa.String(), nullable=True),
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('aml_checked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('aml_result', sa.JSON(), nullable=True),
        sa.Column('ip_address', sa.String(), nullable=True),
        sa.Column('user_agent', sa.String(), nullable=True),
        sa.Column('webhook_payload', sa.JSON(), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    
    # Create indexes for identity_verifications
    op.create_index('ix_identity_ver_user_status', 'identity_verifications', ['user_id', 'status'])
    op.create_index('ix_identity_ver_session', 'identity_verifications', ['session_id'], unique=True)
    op.create_index('ix_identity_ver_created', 'identity_verifications', ['created_at'])
    
    # Remove server defaults after table creation
    op.alter_column('users', 'is_identity_verified', server_default=None)
    op.alter_column('users', 'is_age_verified', server_default=None)
    op.alter_column('identity_verifications', 'aml_checked', server_default=None)


def downgrade() -> None:
    """Downgrade schema - Remove identity verification tables and columns."""
    
    # Drop indexes
    op.drop_index('ix_identity_ver_created', table_name='identity_verifications')
    op.drop_index('ix_identity_ver_session', table_name='identity_verifications')
    op.drop_index('ix_identity_ver_user_status', table_name='identity_verifications')
    
    # Drop table
    op.drop_table('identity_verifications')
    
    # Remove columns from users table
    op.drop_column('users', 'verified_at')
    op.drop_column('users', 'verification_level')
    op.drop_column('users', 'is_age_verified')
    op.drop_column('users', 'is_identity_verified')
