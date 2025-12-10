"""add password to pre_influencers

Revision ID: 77e47424f031
Revises: 47bd206940ce
Create Date: 2025-12-09 09:03:04.360574

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77e47424f031'
down_revision: Union[str, Sequence[str], None] = '47bd206940ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    op.add_column(
        "pre_influencers",
        sa.Column("password", sa.String(), nullable=True),
    )


def downgrade():
    op.drop_column("pre_influencers", "password")
