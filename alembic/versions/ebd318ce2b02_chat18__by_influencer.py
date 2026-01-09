"""chat18+_by_influencer

Revision ID: ebd318ce2b02
Revises: 831d21ddebc3
Create Date: 2026-01-08 23:52:42.503968

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ebd318ce2b02'
down_revision: Union[str, Sequence[str], None] = '831d21ddebc3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    # 1) Add column to influencer_subscriptions
    op.add_column(
        "influencer_subscriptions",
        sa.Column(
            "is_18_selected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # 2) OPTIONAL: migrate existing data if user.is_18_selected existed
    # This copies the flag from users → influencer_subscriptions
    op.execute("""
        UPDATE influencer_subscriptions s
        SET is_18_selected = u.is_18_selected
        FROM users u
        WHERE s.user_id = u.id
    """)

    # 3) Remove column from users
    op.drop_column("users", "is_18_selected")


def downgrade():
    # 1) Re-add column to users
    op.add_column(
        "users",
        sa.Column(
            "is_18_selected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # 2) Restore data from influencer_subscriptions (best effort)
    op.execute("""
        UPDATE users u
        SET is_18_selected = s.is_18_selected
        FROM influencer_subscriptions s
        WHERE s.user_id = u.id
    """)

    # 3) Drop column from influencer_subscriptions
    op.drop_column("influencer_subscriptions", "is_18_selected")