"""group_calls_and_float_duration

Revision ID: 5a8b6c4d2e1f
Revises: 4f7e4f4f2a3e
Create Date: 2025-12-10 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a8b6c4d2e1f'
down_revision: Union[str, None] = '4f7e4f4f2a3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add conversation_id to messages
    op.add_column('messages', sa.Column('conversation_id', sa.String(), nullable=True))
    op.create_foreign_key(None, 'messages', 'calls', ['conversation_id'], ['conversation_id'])

    # 2. Change call_duration_secs to Float
    # Using straight alter_column. Depending on DB (Postgres), a USING clause might be needed if there's data,
    # but implicit cast from Integer to Float usually works fine in Postgres.
    op.alter_column('calls', 'call_duration_secs',
               existing_type=sa.Integer(),
               type_=sa.Float(),
               existing_nullable=True)


def downgrade() -> None:
    # 1. Revert call_duration_secs to Integer
    op.alter_column('calls', 'call_duration_secs',
               existing_type=sa.Float(),
               type_=sa.Integer(),
               existing_nullable=True)

    # 2. Remove conversation_id from messages
    op.drop_constraint(None, 'messages', type_='foreignkey')
    op.drop_column('messages', 'conversation_id')
