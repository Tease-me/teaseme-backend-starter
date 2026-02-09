"""drop_gender_relevance_column

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-09 11:44:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the gender_relevance column — all personas are women."""
    op.drop_column("preference_catalog", "gender_relevance")


def downgrade() -> None:
    """Re-add gender_relevance column with default 'both'."""
    op.add_column(
        "preference_catalog",
        sa.Column("gender_relevance", sa.String(), nullable=False, server_default="both"),
    )
