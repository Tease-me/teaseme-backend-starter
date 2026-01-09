"""is_18_selected

Revision ID: 831d21ddebc3
Revises: a6d4bb445100
Create Date: 2026-01-08 02:07:53.107446

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '831d21ddebc3'
down_revision: Union[str, Sequence[str], None] = 'a6d4bb445100'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_18_selected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column("users", "is_18_selected", server_default=None)

def downgrade() -> None:
    op.drop_column("users", "is_18_selected")
