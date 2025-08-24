"""add chat_id to calls with FK to chats

Revision ID: 494a6471d032
Revises: db3d9cc045e1
Create Date: 2025-08-24 11:33:52.303330

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '494a6471d032'
down_revision: Union[str, Sequence[str], None] = 'db3d9cc045e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("chat_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_calls_chat_id_chats",
        "calls", "chats",
        ["chat_id"], ["id"],
        ondelete="SET NULL"
    )

def downgrade() -> None:
    op.drop_constraint("fk_calls_chat_id_chats", "calls", type_="foreignkey")
    op.drop_column("calls", "chat_id")
