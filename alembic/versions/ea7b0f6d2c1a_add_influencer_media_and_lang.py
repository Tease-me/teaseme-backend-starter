"""add influencer media and language fields

Revision ID: ea7b0f6d2c1a
Revises: 23649145b822
Create Date: 2025-02-18 01:05:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ea7b0f6d2c1a"
down_revision: Union[str, Sequence[str], None] = "8b4a0f3f7c7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("influencers", sa.Column("profile_photo_key", sa.String(), nullable=True))
    op.add_column("influencers", sa.Column("profile_video_key", sa.String(), nullable=True))
    op.add_column("influencers", sa.Column("native_language", sa.String(), nullable=True))
    op.add_column("influencers", sa.Column("date_of_birth", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("influencers", "date_of_birth")
    op.drop_column("influencers", "native_language")
    op.drop_column("influencers", "profile_video_key")
    op.drop_column("influencers", "profile_photo_key")
