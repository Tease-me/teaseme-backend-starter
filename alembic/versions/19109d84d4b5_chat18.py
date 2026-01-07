"""chat18+

Revision ID: 19109d84d4b5
Revises: 2188ca984f3a
Create Date: 2026-01-07 06:02:01.567647

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '19109d84d4b5'
down_revision: Union[str, Sequence[str], None] = '2188ca984f3a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    # --- chats_18 ---
    op.create_table(
        "chats_18",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("influencer_id", sa.String(), sa.ForeignKey("influencers.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index("ix_chats_18_user", "chats_18", ["user_id"])
    op.create_index("ix_chats_18_influencer", "chats_18", ["influencer_id"])

    # --- messages_18 ---
    op.create_table(
        "messages_18",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "chat_id",
            sa.String(),
            sa.ForeignKey("chats_18.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False, server_default="text"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("audio_url", sa.String(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index("ix_messages_18_chat", "messages_18", ["chat_id"])


def downgrade():
    op.drop_index("ix_messages_18_chat", table_name="messages_18")
    op.drop_table("messages_18")

    op.drop_index("ix_chats_18_influencer", table_name="chats_18")
    op.drop_index("ix_chats_18_user", table_name="chats_18")
    op.drop_table("chats_18")
