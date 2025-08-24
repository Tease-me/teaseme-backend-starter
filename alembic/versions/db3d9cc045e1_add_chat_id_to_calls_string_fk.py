"""add chat_id to calls (string) + FK

Revision ID: db3d9cc045e1
Revises: f24e5ddb5269
Create Date: 2025-08-24 11:30:59.872205

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db3d9cc045e1'
down_revision = "f24e5ddb5269"
branch_labels = None
depends_on = None

def upgrade():
    # chats.id é VARCHAR => chat_id precisa ser String
    op.add_column("calls", sa.Column("chat_id", sa.String(), nullable=True))
    op.create_index("ix_calls_chat_id", "calls", ["chat_id"], unique=False)
    op.create_foreign_key(
        "fk_calls_chat_id_chats",
        source_table="calls",
        referent_table="chats",
        local_cols=["chat_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )

def downgrade():
    op.drop_constraint("fk_calls_chat_id_chats", "calls", type_="foreignkey")
    op.drop_index("ix_calls_chat_id", table_name="calls")
    op.drop_column("calls", "chat_id")