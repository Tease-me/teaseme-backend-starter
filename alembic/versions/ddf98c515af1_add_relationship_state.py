"""add relationship_state

Revision ID: ddf98c515af1
Revises: ab542e9c3f26
Create Date: 2025-12-12 21:42:13.394424

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ddf98c515af1'
down_revision: Union[str, Sequence[str], None] = 'ab542e9c3f26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade():
    op.create_table(
        "relationship_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),

        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("influencer_id", sa.String(), sa.ForeignKey("influencers.id", ondelete="CASCADE"), nullable=False),

        sa.Column("trust", sa.Float(), nullable=False, server_default="10"),
        sa.Column("closeness", sa.Float(), nullable=False, server_default="10"),
        sa.Column("attraction", sa.Float(), nullable=False, server_default="5"),
        sa.Column("safety", sa.Float(), nullable=False, server_default="95"),

        sa.Column("state", sa.String(), nullable=False, server_default="STRANGERS"),
        sa.Column("exclusive_agreed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("girlfriend_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),

        sa.Column("dtr_stage", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dtr_cooldown_until", sa.DateTime(timezone=True), nullable=True),

        sa.Column("last_interaction_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index(
        "ix_rel_user_influencer",
        "relationship_state",
        ["user_id", "influencer_id"],
        unique=True,
    )

def downgrade():
    op.drop_index("ix_rel_user_influencer", table_name="relationship_state")
    op.drop_table("relationship_state")
