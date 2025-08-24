"""add chat_id to calls with FK to chats, backfill

Revision ID: 8ecc284af443
Revises: f24e5ddb5269
Create Date: 2025-08-24 10:46:46.614622
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision: str = "8ecc284af443"
down_revision: Union[str, Sequence[str], None] = "f24e5ddb5269"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) adicionar a coluna (nullable primeiro para permitir backfill)
    op.add_column("calls", sa.Column("chat_id", sa.Integer(), nullable=True))
    op.create_index("ix_calls_chat_id", "calls", ["chat_id"], unique=False)
    op.create_foreign_key(
        "fk_calls_chat_id_chats",
        source_table="calls",
        referent_table="chats",
        local_cols=["chat_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )

    # 2) backfill: criar chats ausentes e linkar calls.chat_id
    conn = op.get_bind()
    conn.execute(text("""
        INSERT INTO chats (user_id, influencer_id, started_at)
        SELECT DISTINCT c.user_id, c.influencer_id, NOW()
        FROM calls c
        LEFT JOIN chats ch
          ON ch.user_id = c.user_id
         AND ch.influencer_id = c.influencer_id
        WHERE c.user_id IS NOT NULL
          AND c.influencer_id IS NOT NULL
          AND ch.id IS NULL
    """))

    conn.execute(text("""
        UPDATE calls c
           SET chat_id = ch.id
          FROM chats ch
         WHERE ch.user_id = c.user_id
           AND ch.influencer_id = c.influencer_id
           AND c.chat_id IS NULL
    """))

    # Se quiser endurecer depois:
    # op.alter_column("calls", "chat_id", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    op.drop_constraint("fk_calls_chat_id_chats", "calls", type_="foreignkey")
    op.drop_index("ix_calls_chat_id", table_name="calls")
    op.drop_column("calls", "chat_id")