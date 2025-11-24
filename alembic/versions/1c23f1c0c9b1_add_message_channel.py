"""Add message channel (text vs call)

Revision ID: 1c23f1c0c9b1
Revises: 750e4cf88da0
Create Date: 2025-02-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "1c23f1c0c9b1"
down_revision: Union[str, None] = "750e4cf88da0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column(
        "messages",
        sa.Column("channel", sa.String(), nullable=False, server_default="text"),
    )
    op.alter_column("messages", "channel", server_default=None)


def downgrade():
    op.drop_column("messages", "channel")

