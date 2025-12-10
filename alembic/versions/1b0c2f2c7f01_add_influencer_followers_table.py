"""Add influencer followers table

Revision ID: 1b0c2f2c7f01
Revises: 5f1e2c6c9a7b
Create Date: 2025-03-05 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1b0c2f2c7f01"
down_revision: Union[str, Sequence[str], None] = "5f1e2c6c9a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create influencer followers table."""
    op.create_table(
        "influencer_followers",
        sa.Column("influencer_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["influencer_id"], ["influencers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("influencer_id", "user_id"),
    )
    op.create_index(
        "ix_influencer_followers_user_id",
        "influencer_followers",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop influencer followers table."""
    op.drop_index("ix_influencer_followers_user_id", table_name="influencer_followers")
    op.drop_table("influencer_followers")
